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

/** Run `python -B -E -m tools.design <args> --root <root>` once and parse its JSON output. */
function run({ python, root, args, timeoutMs = TIMEOUT_MS, execFileImpl = execFile }) {
  if (typeof python !== "string" || !python) return Promise.reject(new Error("no Python interpreter is configured"));
  if (typeof root !== "string" || !root) return Promise.reject(new Error("no repository root"));
  const argv = ["-B", "-E", "-m", "tools.design", ...args, "--root", root];
  const options = { cwd: root, windowsHide: true, shell: false, timeout: timeoutMs, maxBuffer: 1 << 20, encoding: "utf8" };
  return new Promise((resolve, reject) => {
    execFileImpl(python, argv, options, (err, stdout, stderr) => {
      if (err) {
        const said = String(stderr || "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean).pop() || "";
        const overflow = err.code === "ERR_CHILD_PROCESS_STDIO_MAXBUFFER";
        const stopped = !overflow && (err.killed || err.signal);
        const unsure = "it may or may not have created the diagram: run python -m tools.design check";
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

module.exports = { newDiagram, newDiagramArgs, run, CATEGORIES, TIMEOUT_MS };
