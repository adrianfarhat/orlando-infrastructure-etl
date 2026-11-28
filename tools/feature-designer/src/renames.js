// Renames of diagram sources (T-97 PR B2b-2b; decisions C6, R2, D2, G1-G12; diagram library section 7.5).
//
// VS Code cannot cancel a rename. Before it happens (onWillRenameFiles) Feature Designer takes a bounded,
// read-only snapshot through the design tooling (`rename-preview`): which registered sources the batch
// affects (folders expanded), each one's SHA-256 and the registry revision, and what to warn about.
// After it happened (onDidRenameFiles) the window where it happened checks the files on disk and shows ONE
// modal prompt for the batch, with nothing that writes as the default:
//   Not now (nothing is written; G3) · Update the registry (only the registry follows: `registry
//   adopt-moves --sha256`) · Update the registry and N closed documents (then the Update Closed Documents
//   confirmation) · Move the files back (`registry move-back`, a recorded move; the registry is unchanged).
// Every write is a one-shot design-tooling command (src/commands.js, decision B1); the long-running
// designer process stays read-only. Renames made elsewhere (Git, the file explorer, another editor) and
// declined prompts show "N moved sources: registry not updated" in every Feature Designer window (E6,
// derived from disk by the read-only `moved` operation, so it survives restarts), with the same prompt.
// Open documents follow the registry through the existing B2a refresh (C1, C5); closed documents only
// through the explicit Update Closed Documents confirmation. Formats are whatever the tooling returns (G12).
"use strict";
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const SNAPSHOT_MS = 4000;                        // the longest a rename waits for the snapshot (never indefinitely)
const SCOPE = /^(designs|docs\/architecture)(\/|$)/;
const SCOPE_CI = /^(designs|docs\/architecture)(\/|$)/i;
/** Whether a repository path may concern diagram sources (letter case ignored on Windows, QA). */
const inScope = (rel, platform = process.platform) => (platform === "win32" ? SCOPE_CI : SCOPE).test(rel);
const ARCH_NOTICE = "Architecture diagram sources change only through technical-lead's documentation workflow (M1); " +
  "the registry was not changed.";
const CHOICES = {
  notNow: "Not now",
  registry: "Update the registry",
  back: "Move the files back",
};
const closedLabel = (n) => `Update the registry and ${n} closed document${n === 1 ? "" : "s"}`;
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const sha256 = (buf) => crypto.createHash("sha256").update(buf).digest("hex");
const keyOf = (rel) => (process.platform === "win32" ? rel.toLowerCase() : rel);

// ------------------------------------------------------------------ pure model (tested in test/unit/renames.test.js)

function relIn(root, uri) {
  if (!uri || uri.scheme !== "file") return null;
  const r = path.relative(root, uri.fsPath);
  if (!r || r.startsWith("..") || path.isAbsolute(r)) return null;
  return r.split(path.sep).join("/");
}

/** The repository-relative pairs of a rename event under `root` that may concern diagram sources. */
function batchOf(root, files, platform = process.platform) {
  const out = [];
  for (const f of files || []) {
    const from = relIn(root, f.oldUri), to = relIn(root, f.newUri);
    if (from === null || to === null) continue;
    if (inScope(from, platform) || inScope(to, platform)) out.push({ from, to });
  }
  return out;
}

/** In-scope paths of `root` that a rename moved out of it (out of the workspace folder, or to another file
 *  system): {from, to} with `to` as VS Code shows it. Not part of a batch: the registry cannot follow them (QA). */
function leftOf(root, files, platform = process.platform) {
  const out = [];
  for (const f of files || []) {
    const from = relIn(root, f.oldUri);
    if (from === null || !inScope(from, platform) || relIn(root, f.newUri) !== null) continue;
    out.push({ from, to: f.newUri ? (f.newUri.scheme === "file" ? f.newUri.fsPath : String(f.newUri)) : "" });
  }
  return out;
}

/** The notice for registered sources that left the design workspace (null when none did). `missing`: the
 *  `moved` answer's missing entries after the rename. */
function leftNotice(left, missing) {
  const gone = (missing || []).filter((m) => left.some((l) => keyOf(m.from) === keyOf(l.from) || keyOf(m.from).startsWith(keyOf(l.from) + "/")));
  if (!gone.length) return null;
  return `${plural(gone.length, "registered diagram source", "registered diagram sources")} left the design workspace ` +
    `(${gone.map((g) => `${g.diagram_id} ${g.from}`).join("; ")} → ${[...new Set(left.map((l) => l.to))].join("; ")}). The registry is not ` +
    "updated: a source outside the repository cannot be registered. Move it back into a diagrams/ folder under designs/features/ " +
    "(Undo in the Explorer); until then `check` reports it as missing (E7).";
}

/** C5: mark the storm before the command runs (its registry change triggers the refresh, possibly before the
 *  command's process has returned), and take the mark back if the command fails or is refused (QA). */
async function withStormMark(count, limit, mark, unmark, run) {
  const marked = count > limit;
  if (marked) mark(count);
  try { return await run(); } catch (err) { if (marked) unmark(count); throw err; }
}

/** One key per batch, the same before and after the rename. */
function batchKey(root, pairs) {
  return keyOf(`${root}|${pairs.map((p) => `${p.from}>${p.to}`).sort().join("|")}`);
}

/** Whether a repository path is one of the batch's paths or under one (for the storm guard, C5). */
function inBatch(pairs, rel) {
  const k = keyOf(rel);
  return pairs.some((p) => [p.from, p.to].some((x) => { const b = keyOf(x); return k === b || k.startsWith(b + "/"); }));
}

/** SHA-256 of the file at exactly `rel` (its letter case as listed by its folder), "" for something else
 *  there (a folder, a link, unreadable), null when nothing has exactly that name. */
function exactSha(root, rel, fsImpl = fs) {
  const p = path.join(root, ...rel.split("/"));
  try { if (!fsImpl.readdirSync(path.dirname(p)).includes(path.basename(p))) return null; } catch { return null; }
  try {
    const st = fsImpl.lstatSync(p);
    if (st.isSymbolicLink() || !st.isFile()) return "";
    return sha256(fsImpl.readFileSync(p));
  } catch { return ""; }
}

/** `rel` with the letter case it has on disk now (each part as its folder lists it; a part that does not
 *  exist is kept as given). VS Code reports a case-only rename with the file's old letter case on a
 *  case-insensitive file system (its URIs are canonicalised), so the new case is taken from disk. */
function diskCase(root, rel, fsImpl = fs) {
  let here = root;
  const out = [];
  for (const part of rel.split("/")) {
    let names = [];
    try { names = fsImpl.readdirSync(here); } catch { names = []; }
    const hit = names.includes(part) ? part : names.find((n) => n.toLowerCase() === part.toLowerCase()) || part;
    out.push(hit);
    here = path.join(here, hit);
  }
  return out.join("/");
}

/** Each source of the snapshot judged on disk after the rename: "ok" (at its new path with the bytes it had
 *  before, and gone from the old one), or why not; never guessed. */
function verify(root, sources, fsImpl = fs) {
  return sources.map((s) => {
    const now = exactSha(root, s.to, fsImpl), old = exactSha(root, s.from, fsImpl);
    const caseOnly = keyOf(s.from) === keyOf(s.to) && s.from !== s.to;
    let state = "ok", why = "";
    if (now === null) { state = "missing"; why = `there is no file at ${s.to}`; }
    else if (now === "") { state = "changed"; why = `${s.to} is not a plain file`; }
    else if (old !== null && !caseOnly) { state = "changed"; why = `${s.from} still exists (a copy is not a move)`; }
    else if (s.sha256 && now !== s.sha256) { state = "changed"; why = `${s.to} does not have the content it had before the rename`; }
    return { ...s, state, why, sha256: s.sha256 || null, unknownBefore: !s.sha256 };
  });
}

/** Feature documents referencing the diagrams, from the tooling's reference lines ("<path> line N: ..."),
 *  split into those open in this window and the closed ones. */
function referencingDocuments(references, ids, openHere) {
  const docs = new Set();
  for (const id of ids)
    for (const line of (references || {})[id] || []) {
      const m = /^(designs\/features\/.+?\.md) line \d+:/.exec(line);
      if (m) docs.add(m[1]);
    }
  const open = [], closed = [];
  for (const d of [...docs].sort()) (openHere.has(keyOf(d)) ? open : closed).push(d);
  return { open, closed };
}

/** The one prompt for a batch: its message, detail and choices (labels in order; the first one, which VS
 *  Code focuses, writes nothing). `adopt` and `restore` are the plans (possible, moves, problems). */
function promptModel({ sources, adopt, restore, docs, warnings = [], held = [], skipped = [], external = false,
                       notes = [], unmatched = 0 }) {
  const shown = sources.length + unmatched;       // unmatched: moved sources found ambiguous or missing (never adopted)
  const message = external
    ? `${plural(shown, "diagram source is", "diagram sources are")} not at the registered ${shown === 1 ? "path" : "paths"}: the registry still names the old ${shown === 1 ? "path" : "paths"}`
    : `${plural(shown, "diagram source was", "diagram sources were")} renamed: the registry still names the old ${shown === 1 ? "path" : "paths"}`;
  const lines = [];
  const adopting = new Set((adopt.moves || []).map((m) => keyOf(`${m.from}>${m.to}`)));
  if (sources.length) lines.push("Renamed (old → new):");
  for (const s of sources) {
    const ok = adopting.has(keyOf(`${s.from}>${s.to}`));
    lines.push(`  ${s.diagram_id}${s.title ? ` "${s.title}"` : ""}: ${s.from} → ${s.to}${ok ? "" : "  [not adopted]"}`);
  }
  const problems = [];
  for (const s of sources) if (s.state && s.state !== "ok") problems.push(`${s.diagram_id}: changed — ${s.why}; it is not adopted`);
  for (const x of adopt.excluded || []) for (const p of x.problems) problems.push(p);
  if (!adopt.possible) for (const p of adopt.problems || []) problems.push(p);
  for (const p of skipped) problems.push(p);
  if (problems.length) { lines.push("", "Problems:"); for (const p of [...new Set(problems)]) lines.push(`  - ${p}`); }
  const warn = [...warnings, ...held.map((h) => `${h.path} is held by the unresolved record ${h.record || "(unreadable)"}: VS Code cannot ` +
    "prevent the rename; its recovery reports the old path as missing and never writes it or the new path (G9)")];
  if (warn.length) { lines.push("", "Warnings:"); for (const w of [...new Set(warn)]) lines.push(`  - ${w}`); }
  if (notes.length) { lines.push(""); for (const n of notes) lines.push(n); }
  lines.push("", `Referenced by: ${docs.open.length ? `${plural(docs.open.length, "open document", "open documents")} (${docs.open.join(", ")})` : "no open document"}; ` +
    `${docs.closed.length ? `${plural(docs.closed.length, "closed document", "closed documents")} (${docs.closed.join(", ")})` : "no closed document"}.`);
  const choices = [CHOICES.notNow];
  lines.push("", `${CHOICES.notNow}: nothing is written; "moved sources: registry not updated" stays in the status strip until it is resolved.`);
  if (adopt.possible) {
    choices.push(CHOICES.registry);
    lines.push(`${CHOICES.registry}: only the path of ${plural(adopt.moves.length, "registry entry", "registry entries")} changes ` +
      "(the ID, owner, title and category stay the same). Open documents then refresh their diagram captions and links " +
      "(automatically only when they have no unsaved changes and are shown only in Feature Designer).");
    if (docs.closed.length) {
      choices.push(closedLabel(docs.closed.length));
      lines.push(`${closedLabel(docs.closed.length)}: the same, then the closed documents to update are listed for your confirmation (Update Closed Documents); nothing is written to them before you confirm.`);
    }
  } else lines.push(`${CHOICES.registry}: not possible now (see Problems).`);
  if (restore.possible) {
    choices.push(CHOICES.back);
    lines.push(`${CHOICES.back}: the tooling renames ${shown === 1 ? "the file" : "the files"} back to the old ${shown === 1 ? "path" : "paths"} as one recorded, recoverable move; the registry is not changed.`);
  } else if (restore.reason) lines.push(`${CHOICES.back}: not possible (${restore.reason}).`);
  if (external && sources.some((s) => s.unknownBefore))
    lines.push("", "The content these files had before they were moved is not known here: the adoption checks their identity and that each is a well-formed source.");
  return { message, detail: lines.join("\n"), choices };
}

/** The choice for a clicked label (Escape, Cancel and closing the prompt: Not now). */
function choiceOf(label) {
  if (label === CHOICES.registry) return "registry";
  if (typeof label === "string" && /^Update the registry and \d+ closed documents?$/.test(label)) return "registry-and-closed";
  if (label === CHOICES.back) return "back";
  return "not-now";
}

/** The E6 strip row from the `moved` answer (null when nothing is moved or missing). Architecture
 *  sources are never offered here (G5). */
function movedNote(r) {
  if (!r) return null;
  const matches = r.matches || [], ambiguous = r.ambiguous || [], missing = r.missing || [];
  const count = matches.length + ambiguous.length;
  if (!count && !missing.length) return null;
  const parts = [];
  if (count) parts.push(`${plural(count, "moved source", "moved sources")}: registry not updated`);
  if (ambiguous.length) parts.push(`${ambiguous.length} found at several paths (never guessed)`);
  if (missing.length) parts.push(`${plural(missing.length, "source is", "sources are")} missing with no file holding ${missing.length === 1 ? "its" : "their"} ID (E7)`);
  return { count, ambiguous: ambiguous.length, missing: missing.length, text: parts.join("; ") + ".",
           ids: [...matches, ...ambiguous].map((m) => m.diagram_id), adoptable: matches.filter((m) => !m.problem).length };
}

/** The sources of an external move (E6), as the prompt shows them, and what cannot be adopted. */
function externalSources(r, remembered = new Map()) {
  const sources = [], skipped = [];
  for (const m of r.matches || []) {
    const h = remembered.get(keyOf(`${m.diagram_id}|${m.from}|${m.to}`)) || null;
    sources.push({ diagram_id: m.diagram_id, from: m.from, to: m.to, sha256: h, problem: m.problem || "" });
  }
  for (const a of r.ambiguous || [])
    skipped.push(`${a.diagram_id}: its registered source ${a.from} is missing and its ID is at ${a.candidates.length} unregistered paths ` +
      `(${a.candidates.join(", ")}): nothing is guessed; keep one of them (or run python -m tools.design registry relink)`);
  for (const x of r.missing || [])
    skipped.push(`${x.diagram_id}: ${x.from} is missing and no file holds its ID (E7): never relinked automatically ` +
      "(python -m tools.design registry relink or registry retire)");
  return { sources, skipped };
}

/** What the person is told after the registry was updated (never claims an index regeneration that did not happen). */
function adoptedMessage(result, back = false) {
  const n = result.renames.length;
  const head = back
    ? `Moved back ${plural(n, "diagram source", "diagram sources")} to ${n === 1 ? "its registered path" : "their registered paths"}: ` +
      result.renames.map((r) => `${r.diagram_id} ${r.from} → ${r.to}`).join("; ") + ". The registry was not changed."
    : `Registry updated: ${result.renames.map((r) => `${r.diagram_id} ${r.from} → ${r.to}`).join("; ")}. Only the ${n === 1 ? "path" : "paths"} changed.`;
  const index = result.index.regenerated
    ? (back ? "" : " designs/index/diagram-index.md was regenerated.")
    : ` designs/index/diagram-index.md was NOT regenerated (${result.index.problem || "unknown reason"}); run python -m tools.design index.`;
  return head + index + " Nothing was staged or committed.";
}

// ------------------------------------------------------------------ VS Code wiring

let vscode = null, deps = null;
const snapshots = new Map();                     // batch key -> { pairs, preview | error }
const remembered = new Map();                    // "<id>|<old>|<new>" -> SHA-256 before the rename (this session only)
const notes = new Map();                         // repository root -> the E6 strip row
const prompting = new Set();                     // roots with a prompt open in this window

function withTimeout(promise, ms) {
  let t;
  return Promise.race([promise, new Promise((res) => { t = setTimeout(() => res({ timeout: true }), ms); })]).finally(() => clearTimeout(t));
}

function roots() {
  return (vscode.workspace.workspaceFolders || []).map((f) => f.uri.fsPath)
    .filter((r) => fs.existsSync(path.join(r, "tools", "design", "__main__.py")) && fs.existsSync(path.join(r, "designs")));
}

function onWillRename(e) {
  if (!vscode.workspace.isTrusted) return;
  const tasks = [];
  for (const [k, v] of snapshots) if (Date.now() - v.time > 120000) snapshots.delete(k);   // a rename that never happened
  for (const root of roots()) {
    const pairs = batchOf(root, e.files);
    if (!pairs.length) continue;
    deps.noteBatch(root, pairs);                 // C5: the batch's file events count as one event
    const key = batchKey(root, pairs);
    const task = withTimeout(deps.ask(root, "rename-preview", { moves: pairs, window: deps.windowId() }, false), SNAPSHOT_MS)
      .then((r) => { snapshots.set(key, r && r.timeout ? { pairs, time: Date.now(), error: `the snapshot took longer than ${SNAPSHOT_MS / 1000} s` }
                                                        : { pairs, time: Date.now(), preview: r }); },
            (err) => { snapshots.set(key, { pairs, time: Date.now(), error: String(err.message || err) }); });
    tasks.push(task);
  }
  if (tasks.length) e.waitUntil(Promise.all(tasks));   // bounded: VS Code renames once the snapshot is taken or timed out
}

function onDidRename(e) {
  if (!vscode.workspace.isTrusted) return;
  for (const root of roots()) {
    const left = leftOf(root, e.files);
    if (left.length) notifyLeft(root, left).catch((err) => deps.log(`[renames] ${err.message}`));
    const pairs = batchOf(root, e.files);
    if (!pairs.length) continue;
    const key = batchKey(root, pairs);
    const snap = snapshots.get(key) || { pairs, error: "no snapshot was taken before the rename" };
    snapshots.delete(key);
    afterRename(root, pairs, snap).catch((err) => { deps.log(`[renames] ${err.stack || err}`); vscode.window.showErrorMessage(`Feature Designer: ${err.message}`); })
      .finally(() => refreshMoved(root).catch(() => {}));
  }
}

async function notifyLeft(root, left) {
  deps.log(`[renames] left the workspace: ${left.map((l) => `${l.from} → ${l.to}`).join(", ")}`);
  const r = await deps.ask(root, "moved", {}, false);
  const text = leftNotice(left, r.missing);
  if (text) vscode.window.showWarningMessage(`Feature Designer: ${text}`);
}

async function plan(root, mode, moves) {
  const r = await deps.ask(root, "move-plan", { mode, moves: moves.map((m) => (m.sha256 ? m : { from: m.from, to: m.to })) }, false);
  return { possible: !!r.possible, problems: r.problems || [], token: r.token || "", renames: r.renames || [], references: r.references || {} };
}

/** The largest part of the batch that can be carried out: all of it, or the moves that are possible one by
 *  one (the others are listed with their problems; a part is offered only when it is possible as a whole). */
async function planBatch(root, mode, moves) {
  if (!moves.length) return { possible: false, problems: [], moves: [], excluded: [], token: "" };
  const all = await plan(root, mode, moves);
  if (all.possible || moves.length === 1) return { ...all, moves: all.possible ? moves : [], excluded: [] };
  const ok = [], excluded = [];
  for (const m of moves) { const one = await plan(root, mode, [m]); if (one.possible) ok.push(m); else excluded.push({ move: m, problems: one.problems }); }
  if (!ok.length) return { possible: false, problems: all.problems, moves: [], excluded };
  const some = await plan(root, mode, ok);
  return some.possible ? { ...some, moves: ok, excluded } : { possible: false, problems: some.problems, moves: [], excluded };
}

function openHere(root) { return new Set(require("./presence").openDocuments(vscode, root).map((d) => keyOf(d.path))); }

async function afterRename(root, pairs, snap) {
  const pre = snap.preview;
  if (!pre) {                                    // no snapshot: identify the sources from disk (E6), without their old bytes
    deps.log(`[renames] ${pairs.map((p) => `${p.from} → ${p.to}`).join(", ")}: ${snap.error}; continuing from what is on disk`);
    const moved = await deps.ask(root, "moved", {}, false);
    const mine = (moved.matches || []).filter((m) => pairs.some((p) => keyOf(m.from) === keyOf(p.from) || keyOf(m.from).startsWith(keyOf(p.from) + "/")));
    if (!mine.length) return;
    return review(root, { matches: mine, ambiguous: [], missing: [] }, { note: `The content before the rename could not be recorded (${snap.error}).` });
  }
  if (pre.architecture.length) {
    deps.log(`[renames] architecture: ${pre.architecture.map((a) => `${a.diagram_id || ""} ${a.from} → ${a.to}`).join(", ")}`);
    vscode.window.showInformationMessage(`${ARCH_NOTICE} (${pre.architecture.map((a) => `${a.from} → ${a.to}`).join("; ")})`);
  }
  if (pre.held.length && !pre.sources.length) {
    const reviewLabel = "Review…";
    vscode.window.showWarningMessage(`${pre.held.map((h) => h.path).join(", ")} ${pre.held.length === 1 ? "is" : "are"} held by an unresolved ` +
      "record and VS Code cannot prevent the rename: its recovery reports the old path as missing and never writes it or the new path (G9).", reviewLabel)
      .then((a) => { if (a === reviewLabel) deps.upd.showRecovery(); });
  }
  if (!pre.sources.length) return;
  // the new paths as they are on disk (a case-only rename keeps the old case in VS Code's event); a source
  // whose path did not change at all was not renamed
  const renamed = pre.sources.map((s) => ({ ...s, to: diskCase(root, s.to) })).filter((s) => s.to !== s.from);
  if (!renamed.length) return;
  for (const s of renamed) if (s.sha256) remembered.set(keyOf(`${s.diagram_id}|${s.from}|${s.to}`), s.sha256);
  const checked = verify(root, renamed);
  await decide(root, { sources: checked, warnings: pre.warnings, held: pre.held, skipped: pre.skipped || [], references: pre.references,
                       preProblems: pre.sources.filter((s) => s.problem) });
}

/** The prompt for renames made elsewhere, or declined before (the E6 strip row's Review…). */
async function review(root, moved, { note = "" } = {}) {
  const r = moved || await deps.ask(root, "moved", {}, false);
  const { sources, skipped } = externalSources(r, remembered);
  if (!sources.length && !skipped.length) { vscode.window.showInformationMessage("No moved diagram source: the registry names every source's path."); return; }
  const checked = sources.map((s) => ({ ...s, state: "ok", why: "", unknownBefore: !s.sha256 }));
  await decide(root, { sources: checked, warnings: [], held: [], skipped, references: {}, external: true, note, unmatched: skipped.length,
                       preProblems: checked.filter((s) => s.problem) });
}

async function decide(root, { sources, warnings, held, skipped, references, external = false, note = "", preProblems = [], unmatched = 0 }) {
  if (prompting.has(root)) { deps.log("[renames] a rename prompt is already open; this batch is shown by the strip row"); return; }
  prompting.add(root);
  try {
    const verified = sources.filter((s) => s.state === "ok" && !s.problem);
    // all moves with their checksum before the rename, or none with it (never a mixture)
    const withSha = verified.every((s) => s.sha256);
    const adopt = await planBatch(root, "adopt", verified.map((s) => ({ from: s.from, to: s.to, sha256: withSha ? s.sha256 : null })));
    const allOk = sources.length > 0 && sources.every((s) => s.state === "ok");
    let restore = { possible: false, moves: [], reason: !sources.length ? "" : allOk ? "" : "a file is not as it was renamed" };
    if (allOk) {
      const backSha = sources.every((s) => s.sha256);
      const moves = sources.map((s) => ({ from: s.to, to: s.from, sha256: backSha ? s.sha256 : null }));
      const p = await plan(root, "restore", moves);
      restore = p.possible ? { ...p, moves } : { possible: false, moves: [], reason: p.problems.join("; ") };
    }
    const ids = (adopt.moves || []).map((m) => (sources.find((s) => s.from === m.from) || {}).diagram_id).filter(Boolean);
    const docs = referencingDocuments({ ...(references || {}), ...(adopt.references || {}) }, ids.length ? ids : sources.map((s) => s.diagram_id),
                                      openHere(root));
    const model = promptModel({ sources, adopt, restore, docs, warnings, held, external, unmatched,
                                skipped: [...skipped, ...preProblems.map((s) => s.problem)], notes: note ? [note] : [] });
    deps.log(`[renames] prompt: ${model.message} | choices: ${model.choices.join(" / ")} | ${model.detail.split("\n").filter(Boolean).join(" | ")}`);
    const answer = await vscode.window.showWarningMessage(model.message, { modal: true, detail: model.detail }, ...model.choices);
    const choice = choiceOf(answer);
    deps.log(`[renames] choice: ${choice}${answer ? ` (${answer})` : " (dismissed)"}`);
    if (choice === "not-now") return;
    const bridge = await deps.bridgeFor(root);
    if (choice === "back") {
      await carryOut(root, bridge, "restore", restore, true);
      return;
    }
    const ok = await carryOut(root, bridge, "adopt", adopt, false);
    if (ok && choice === "registry-and-closed") await deps.upd.showUpdate(root);   // the existing confirmation; never silent
  } finally { prompting.delete(root); }
}

async function carryOut(root, bridge, mode, p, back) {
  try {
    // C5: one summary, no automatic refresh, for a batch of more than STORM_COUNT sources; withdrawn on a failure
    const r = await withStormMark(mode === "adopt" ? p.moves.length : 0, deps.stormCount, (n) => deps.markStorm(root, n),
                                  (n) => deps.unmarkStorm(root, n),
                                  () => require("./commands").moveSources({ python: bridge.python, root }, { mode, moves: p.moves, token: p.token }));
    deps.log(`[renames] ${r.id}: ${mode} ${r.renames.map((x) => `${x.diagram_id} ${x.from} → ${x.to}`).join(", ")}; index ${r.index.regenerated ? "regenerated" : `not regenerated (${r.index.problem})`}`);
    vscode.window.showInformationMessage(adoptedMessage(r, back));
    for (const w of (r.warnings || []).filter((x) => typeof x === "string")) vscode.window.showWarningMessage(`Feature Designer: ${w}`);
    return true;
  } catch (err) {
    deps.log(`[renames] ${mode} refused or failed: ${err.message}`);
    await deps.upd.refreshHeld(root, { offer: false });
    // The tooling's message says exactly what was and was not done (refused before anything was written, or
    // partly done with a record kept); an unresolved record is offered for review.
    const recs = deps.upd.records(root);
    const reviewLabel = "Review…";
    const kept = recs.some((x) => x.valid && x.tool === "registry-move")
      ? " An interrupted registry move is recorded: nothing more changes until you complete, undo or abandon it (Review…)." : "";
    // not awaited: the notification may stay up for long, and a later prompt (Review… in the strip) must not wait for it
    vscode.window.showErrorMessage(`Feature Designer (${back ? "Move the files back" : "Update the registry"}): ${err.message}${kept}`,
                                   ...(recs.length ? [reviewLabel] : []))
      .then((a) => { if (a === reviewLabel) deps.upd.showRecovery(); });
    return false;
  }
}

// ------------------------------------------------------------------ the E6 strip row

/** Which root Review Moved Diagram Sources acts on without asking: the only one with moved sources, the only
 *  root at all (it then says there is nothing), or null when none has any; undefined: ask (several have some). */
function pickRoot(found, only) {
  if (found.length === 1) return found[0];
  if (found.length > 1) return undefined;
  return only;
}

async function refreshMoved(root) {
  if (!vscode.workspace.isTrusted) return;
  let r;
  try { r = await deps.ask(root, "moved", {}, false); }
  catch (err) { deps.log(`[renames] moved sources not checked: ${err.message}`); return; }
  const note = movedNote(r);
  notes.set(root, note);
  for (const [k, set] of deps.panels) {
    if (!set.size) continue;
    try { if (deps.rootOf(vscode.Uri.parse(k)) !== root) continue; } catch { continue; }
    deps.postAll(k, { type: "movedNote", note });
  }
}

function activate(context, d) {
  vscode = require("vscode");
  deps = d;
  let timer = null;
  const soon = () => { clearTimeout(timer); timer = setTimeout(() => { for (const r of roots()) refreshMoved(r).catch(() => {}); }, 700); };
  const watchers = ["**/designs/**/*.md", "**/designs/diagrams/registry.yml"].map((g) => vscode.workspace.createFileSystemWatcher(g));
  context.subscriptions.push(
    vscode.workspace.onWillRenameFiles(onWillRename),
    vscode.workspace.onDidRenameFiles(onDidRename),
    ...watchers, ...watchers.flatMap((w) => [w.onDidCreate(soon), w.onDidDelete(soon), w.onDidChange((u) => { if (/registry\.yml$/.test(u.fsPath)) soon(); })]),
    vscode.workspace.onDidGrantWorkspaceTrust(soon),
    vscode.workspace.onDidChangeConfiguration((e) => { if (e.affectsConfiguration("featureDesigner.pythonPath")) soon(); }),
    vscode.commands.registerCommand("featureDesigner.reviewMovedSources", async () => {
      const rs = roots();
      if (!rs.length) { vscode.window.showInformationMessage("Open the repository folder first."); return; }
      // every design root with moved (or missing) sources; a quick pick when there is more than one (QA)
      const found = [];
      for (const r of rs) { await refreshMoved(r).catch(() => {}); if (notes.get(r)) found.push(r); }
      const auto = pickRoot(found, rs.length === 1 ? rs[0] : null);
      const chosen = auto !== undefined ? auto
        : ((await vscode.window.showQuickPick(found.map((r) => ({ label: path.basename(r), description: r, detail: notes.get(r).text, r })),
                                              { placeHolder: "Which repository's moved diagram sources?" })) || {}).r;
      if (!chosen) { if (!found.length) vscode.window.showInformationMessage("No moved diagram source: the registry names every source's path."); return; }
      await review(chosen).catch((err) => vscode.window.showErrorMessage(`Feature Designer: ${err.message}`));
      await refreshMoved(chosen).catch(() => {});
    }),
  );
  setTimeout(soon, 1500);                         // on start: derived from disk, so a declined prompt is offered again
  return {
    note: (root) => notes.get(root) || null,
    review: (root) => review(root).catch((err) => vscode.window.showErrorMessage(`Feature Designer: ${err.message}`)).finally(() => refreshMoved(root).catch(() => {})),
    refreshMoved,
    pendingSnapshots: () => snapshots.size,
  };
}

module.exports = { activate, inScope, leftOf, leftNotice, withStormMark, pickRoot, batchOf, batchKey, inBatch, exactSha, diskCase, verify, referencingDocuments, promptModel, choiceOf, movedNote,
                   externalSources, adoptedMessage, CHOICES, ARCH_NOTICE, SNAPSHOT_MS };
