// One-shot runs of the design tooling's write commands (T-97 PR B, decision B1). The long-running
// designer process stays read-only; a file is created only by the same command a person would run
// (`python -m tools.design new diagram …`), so its lock, all-or-nothing creation, registry checks and
// the docs/architecture/ write guard all apply unchanged. Only the commands defined here can run:
// arguments are validated, passed as an argument array (never through a shell), and each run has a
// timeout. The result is the command's JSON output.
"use strict";
const { execFile } = require("child_process");

const FEATURE_ID = /^FD-\d{4}$/;
const DIAGRAM_ID = /^FD-\d{4}-D[1-9]\d*$/;
const CATEGORIES = ["system-architecture", "data-model", "process", "sequence", "state", "ui", "legend", "other"];
const MAX_TITLE = 200;                       // the design tooling applies its own, stricter limit
const TIMEOUT_MS = 60000;

/** The arguments of `new diagram` for these values (throws when one is not acceptable). */
function newDiagramArgs({ owner, title, category } = {}) {
  if (typeof owner !== "string" || !FEATURE_ID.test(owner)) throw new Error("the owner must be a feature ID such as FD-0001");
  if (typeof title !== "string" || !title.trim()) throw new Error("the diagram needs a name");
  if (title.length > MAX_TITLE) throw new Error(`the diagram name is longer than ${MAX_TITLE} characters`);
  if (/[\u0000-\u001f\u007f-\u009f]/.test(title)) throw new Error("the diagram name contains a line break or control character");
  if (!CATEGORIES.includes(category)) throw new Error(`the category must be one of ${CATEGORIES.join(", ")}`);
  // `--name=value` keeps a value that starts with "-" from being read as an option.
  return ["new", "diagram", `--feature=${owner}`, `--title=${title}`, `--category=${category}`, "--json"];
}

const FEATURE_DOC = /^designs\/features\/(?:[^\\/\0:]+\/)*[^\\/\0:]+\.md$/;   // no backslash, NUL or colon
const HEX64 = /^[0-9a-f]{64}$/, HEX16 = /^[0-9a-f]{16}$/, RECORD_ID = /^tx-\d{8}T\d{6}Z-[0-9a-f]{8}$/;

/** The arguments of `refresh-blocks` (T-97 PR B2b-1) for a confirmed list of closed documents. */
function refreshBlocksArgs({ files, token } = {}) {
  if (!Array.isArray(files) || !files.length || files.length > 200) throw new Error("no documents to update");
  const args = ["refresh-blocks"];
  for (const f of files) {
    if (!f || typeof f.path !== "string" || !FEATURE_DOC.test(f.path) || f.path.split("/").some((x) => x === ".." || x === "."))
      throw new Error("not a feature document path");
    if (typeof f.sha256 !== "string" || !HEX64.test(f.sha256)) throw new Error("not a SHA-256");
    args.push(`--file=${f.path}`, `--expect=${f.sha256}`);
  }
  if (typeof token !== "string" || !HEX16.test(token)) throw new Error("not a sources token");
  return [...args, `--sources-token=${token}`, "--json"];
}

/** The arguments of `transaction complete|undo|abandon ID --confirm TOKEN` (an explicit decision, D2). */
function transactionArgs({ action, id, token } = {}) {
  if (!["complete", "undo", "abandon"].includes(action)) throw new Error("the action must be complete, undo or abandon");
  if (typeof id !== "string" || !RECORD_ID.test(id)) throw new Error("not an update record ID");
  if (typeof token !== "string" || !HEX16.test(token)) throw new Error("not a decision token");
  return ["transaction", action, id, `--confirm=${token}`, "--json"];
}

// A repository path a move may name (T-97 PR B2b-2b). Only its shape is checked here (no backslash, NUL,
// colon, "." or ".." part, under designs/features/); which files may move (the folder, the format, the
// file name) is decided by the design tooling, which refuses everything else (G12: no format assumption).
const MOVE_PATH = /^designs\/features\/(?:[^\\/\0:]+\/)*[^\\/\0:]+$/;
const ID_OR_PATH = /^(?:[A-Z]{2}-\d{4}(?:-D\d+)?|designs\/features\/(?:[^\\/\0:]+\/)*[^\\/\0:]+)$/;
const cleanPath = (p, re) => typeof p === "string" && re.test(p) && !p.split("/").some((x) => x === ".." || x === ".");

/** The arguments of `registry adopt-moves` (mode adopt) or `registry move-back` (mode restore) for a confirmed plan:
 *  one --from/--to pair per source, each with the SHA-256 known for it (adopt: from before the rename). */
function moveArgs({ mode, moves, token } = {}) {
  if (!["adopt", "restore"].includes(mode)) throw new Error("the mode must be adopt or restore");
  if (!Array.isArray(moves) || !moves.length || moves.length > 200) throw new Error("no sources to move");
  const args = ["registry", mode === "adopt" ? "adopt-moves" : "move-back"];
  const withSha = moves.every((m) => m && m.sha256 !== undefined && m.sha256 !== null);
  for (const m of moves) {
    if (!m) throw new Error("not a move");
    const from = mode === "adopt" ? cleanPath(m.from, ID_OR_PATH) : cleanPath(m.from, MOVE_PATH);
    const to = mode === "adopt" ? cleanPath(m.to, MOVE_PATH) : cleanPath(m.to, ID_OR_PATH);
    if (!from || !to) throw new Error("not a diagram source path");
    args.push(`--from=${m.from}`, `--to=${m.to}`);
    if (withSha) {
      if (typeof m.sha256 !== "string" || !HEX64.test(m.sha256)) throw new Error("not a SHA-256");
      args.push(`--sha256=${m.sha256}`);
    } else if (m.sha256 !== undefined && m.sha256 !== null) throw new Error("give a SHA-256 for every source or for none");
  }
  if (typeof token !== "string" || !HEX16.test(token)) throw new Error("not a confirmation token");
  return [...args, `--confirm=${token}`, "--json"];
}

const UNSURE_MOVE = "it may or may not have changed the registry or moved files: run python -m tools.design transaction status";

/** Adopt observed renames (the registry follows) or move sources back; resolves to the command's JSON result. */
async function moveSources(opts, fields) {
  const r = await run({ ...opts, args: moveArgs(fields), timeoutMs: 120000, unsure: UNSURE_MOVE });
  if (!r || r.ok !== true || !Array.isArray(r.renames) || !r.index || typeof r.index.regenerated !== "boolean")
    throw new Error("the design tooling returned an unexpected result");
  return r;
}

/** Run `python -B -E -m tools.design <args> --root <root>` once and parse its JSON output. Exit code 1
 *  with a JSON answer (a recovery that was only partly possible) resolves when `jsonOnProblems` is set. */
function run({ python, root, args, timeoutMs = TIMEOUT_MS, execFileImpl = execFile, jsonOnProblems = false,
               unsure = "it may or may not have created the diagram: run python -m tools.design check" }) {
  if (typeof python !== "string" || !python) return Promise.reject(new Error("no Python interpreter is configured"));
  if (typeof root !== "string" || !root) return Promise.reject(new Error("no repository root"));
  const argv = ["-B", "-E", "-m", "tools.design", ...args, "--root", root];
  const options = { cwd: root, windowsHide: true, shell: false, timeout: timeoutMs, maxBuffer: 1 << 20, encoding: "utf8" };
  return new Promise((resolve, reject) => {
    execFileImpl(python, argv, options, (err, stdout, stderr) => {
      if (err && jsonOnProblems && err.code === 1) {
        try { resolve(JSON.parse(String(stdout))); return; } catch { /* reported below */ }
      }
      if (err) {
        const said = String(stderr || "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean).pop() || "";
        const overflow = err.code === "ERR_CHILD_PROCESS_STDIO_MAXBUFFER";
        const stopped = !overflow && (err.killed || err.signal);
        const message = overflow ? `the design tooling printed more output than expected and was stopped; ${unsure}`
          : stopped ? `the design tooling did not finish within ${Math.round(timeoutMs / 1000)} s and was stopped; ${unsure}`
          : said.replace(/^design: error: /, "") || `the design tooling failed (${err.code ?? err.message})`;
        const e = new Error(message);
        e.refused = !(overflow || stopped);
        reject(e);
        return;
      }
      let value;
      try { value = JSON.parse(String(stdout)); } catch { reject(new Error("the design tooling did not answer with JSON")); return; }
      resolve(value);
    });
  });
}

/** Create and register one standalone Mermaid diagram; resolves to {path, diagram_id, owner, category}. */
async function newDiagram(opts, fields) {
  const made = await run({ ...opts, args: newDiagramArgs(fields) });
  if (!made || typeof made.path !== "string" || !made.path.startsWith("designs/features/") || made.path.includes("..") ||
      typeof made.diagram_id !== "string" || !DIAGRAM_ID.test(made.diagram_id) || made.owner !== fields.owner)
    throw new Error("the design tooling returned an unexpected result");
  return made;
}

const UNSURE_UPDATE = "it may or may not have updated documents: run python -m tools.design transaction status";

/** Update the listed closed documents as one transaction; resolves to {ok, id, files}. */
async function refreshBlocks(opts, fields) {
  const r = await run({ ...opts, args: refreshBlocksArgs(fields), timeoutMs: 120000, unsure: UNSURE_UPDATE });
  if (!r || r.ok !== true || !Array.isArray(r.files)) throw new Error("the design tooling returned an unexpected result");
  return r;
}

/** Complete, Undo or Abandon one interrupted update; resolves to {ok, message, files, ...}. */
async function resolveTransaction(opts, fields) {
  const r = await run({ ...opts, args: transactionArgs(fields), timeoutMs: 120000, jsonOnProblems: true, unsure: UNSURE_UPDATE });
  if (!r || typeof r.ok !== "boolean" || typeof r.message !== "string") throw new Error("the design tooling returned an unexpected result");
  return r;
}

module.exports = { newDiagram, newDiagramArgs, refreshBlocks, refreshBlocksArgs, resolveTransaction, transactionArgs, run,
                   moveArgs, moveSources, CATEGORIES, TIMEOUT_MS };
