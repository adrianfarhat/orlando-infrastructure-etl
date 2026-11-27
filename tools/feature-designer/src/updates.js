// Closed-document updates and their recovery (T-97 PR B2b-1, decisions D1-D8).
//
// A document open in this window is only ever changed through the editor (PR B2a). Documents that
// are not open are offered as one update, written by the design tooling's own `refresh-blocks`
// command (src/commands.js): every listed document, or rolled back, with a durable record from which an
// interrupted update is completed or undone. Recovery is always the person's explicit choice:
// nothing is preselected, each file's current state and what each action would do are shown
// first, and dismissing a notification or closing the panel never removes a record (D2, D8).
"use strict";
const vscode = require("vscode");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const presence = require("./presence");
const commands = require("./commands");

const windowId = crypto.randomBytes(8).toString("hex");
const held = new Map();              // repository root -> { paths: Set, records: [], unreadable: bool }
const closed = new Map();            // repository root -> the last closed-document note
const offered = new Set();           // record IDs already offered in a notification this session
const updating = new Set();          // roots with an update running from this window
const views = new Map();             // "update" | "recovery" -> WebviewPanel
const livePoll = new Set();          // roots being re-checked while an update runs elsewhere
const dirtyState = new Map();        // document uri -> whether it had unsaved changes when last seen
let deps = null;
let recount = null;
let heartbeat = null;

const key = (rel) => (process.platform === "win32" ? rel.toLowerCase() : rel);

function roots() {
  return (vscode.workspace.workspaceFolders || []).map((f) => f.uri.fsPath)
    .filter((r) => fs.existsSync(path.join(r, "tools", "design", "__main__.py")) && fs.existsSync(path.join(r, "designs")));
}

// ------------------------------------------------------------------ presence (D6)
let reported = false;
function publishAll() {
  if (!vscode.workspace.isTrusted) return;
  for (const root of roots()) {
    try { presence.publish(root, windowId, presence.openDocuments(vscode, root)); }
    catch (err) { if (!reported) { reported = true; deps.log(`[presence] ${root}: not published (${err.message})`); } }
  }
}
let soon = null;
const publishSoon = () => { clearTimeout(soon); soon = setTimeout(publishAll, 100); };
// Records of windows on this computer whose process has ended are removed here (the design tooling
// cannot check processes, and never ignores a record because of its age: a window that stops
// responding may be suspended or hung with unsaved changes). Done at the start, every minute and
// before every listing, so a crashed window does not hold its documents for longer than needed.
const SWEEP_EVERY = 12;                                           // heartbeats (5 s each)
let beats = 0;
function sweepAll() {
  for (const root of roots()) {
    try { const gone = presence.sweep(root, windowId); if (gone.length) deps.log(`[presence] removed the records of ended windows: ${gone.join(", ")}`); }
    catch (err) { deps.log(`[presence] ${root}: records of ended windows not checked (${err.message})`); }
  }
}
function heartbeatTick() {
  publishAll();
  if (++beats % SWEEP_EVERY === 0) sweepAll();
}

// ------------------------------------------------------------------ unresolved records (E16)
function isHeld(root, rel) {
  const h = held.get(root);
  return !!h && (h.unreadable || h.paths.has(key(rel)));
}

async function refreshHeld(root, { offer = true } = {}) {
  let r;
  try { r = await deps.ask(root, "transactions", {}, false); }
  catch (err) { deps.log(`[updates] records not checked: ${err.message}`); return; }
  const records = r.records || [];
  const paths = new Set();
  for (const rec of records) for (const f of rec.files || []) paths.add(key(f.path));
  held.set(root, { paths, records, unreadable: records.some((x) => !x.valid) });
  for (const [k, set] of deps.panels) {
    if (!set.size) continue;
    let docRoot;
    try { docRoot = deps.rootOf(vscode.Uri.parse(k)); } catch { continue; }
    if (docRoot !== root) continue;
    const rel = deps.relPath(root, vscode.Uri.parse(k));
    deps.postAll(k, { type: "heldNote", held: isHeld(root, rel), records: records.length });
  }
  if (views.get("recovery")) showRecovery(false, false);
  // An update still running in another process leaves no file event when that process ends (it may be
  // terminated): look again until it is no longer running, so its end is noticed and offered.
  if (records.some((x) => x.live) && !livePoll.has(root)) {
    livePoll.add(root);
    setTimeout(() => { livePoll.delete(root); refreshHeld(root).catch(() => {}); }, 5000);
  }
  const fresh = records.filter((x) => !offered.has(x.id) && !x.live);
  if (offer && fresh.length) {
    fresh.forEach((x) => offered.add(x.id));
    const review = "Review…";
    const n = records.reduce((s, x) => s + (x.files || []).length, 0);
    vscode.window.showWarningMessage(`An update of closed feature documents was interrupted${n ? ` (${n} document${n === 1 ? "" : "s"})` : ""}. ` +
      "Nothing more is written to those documents until you decide; the original and updated copies are preserved.", review)
      .then((a) => { if (a === review) showRecovery(); });          // dismissing keeps the record (D8)
  }
}

// ------------------------------------------------------------------ the closed-document update (C4)
function openHere(root) { return new Set(presence.openDocuments(vscode, root).map((d) => key(d.path))); }

async function listClosed(root) {
  sweepAll();
  const r = await deps.ask(root, "affected", { window: windowId }, false);
  const here = openHere(root);
  const eligible = [], excluded = [];
  for (const d of r.documents || []) {
    if (here.has(key(d.path))) excluded.push({ ...d, excluded: "open in this window: updated in the editor instead" });
    else if (d.excluded) excluded.push(d);
    else eligible.push(d);
  }
  return { eligible, excluded, token: r.sources_token, unknown: r.unknown_windows || [], unreadable: r.unreadable_records || [] };
}

async function offerClosed(root) {
  if (!vscode.workspace.isTrusted) return;
  let l;
  try { l = await listClosed(root); } catch (err) { deps.log(`[updates] closed documents not listed: ${err.message}`); return; }
  const note = { count: l.eligible.length, elsewhere: l.excluded.filter((d) => d.excluded.startsWith("open in a VS Code window")).length };
  closed.set(root, note);
  for (const [k, set] of deps.panels) {
    if (!set.size) continue;
    try { if (deps.rootOf(vscode.Uri.parse(k)) !== root) continue; } catch { continue; }
    deps.postAll(k, { type: "closedNote", ...note });
  }
  if (views.get("update")) await showUpdate(root, false, false);        // redrawn in place, never brought forward
}

function panel(kind, title, reveal = true) {
  let p = views.get(kind);
  if (p) { if (reveal) p.reveal(vscode.ViewColumn.Active); return p; }
  const ext = deps.context.extensionUri;
  p = vscode.window.createWebviewPanel(`featureDesigner.${kind}`, title, vscode.ViewColumn.Active,
    { enableScripts: true, enableCommandUris: false, retainContextWhenHidden: true, localResourceRoots: [vscode.Uri.joinPath(ext, "media")] });
  const nonce = crypto.randomBytes(18).toString("base64");
  const uri = (f) => p.webview.asWebviewUri(vscode.Uri.joinPath(ext, "media", f));
  const csp = [`default-src 'none'`, `style-src ${p.webview.cspSource}`, `script-src 'nonce-${nonce}'`, `base-uri 'none'`, `form-action 'none'`].join("; ");
  p.webview.html = `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta http-equiv="Content-Security-Policy" content="${csp}">
<link rel="stylesheet" href="${uri("updates.css")}"><title>${title}</title></head><body><main id="main" data-kind="${kind}"></main>
<script nonce="${nonce}" src="${uri("updates.js")}"></script></body></html>`;
  p.onDidDispose(() => views.delete(kind));                       // closing keeps every record (D8)
  p.webview.onDidReceiveMessage((m) => onPanelMessage(kind, m).catch((err) => {
    deps.log(`[updates] ${err.stack || err}`);
    p.webview.postMessage({ type: "result", ok: false, message: String(err.message || err) });
  }));
  views.set(kind, p);
  return p;
}

async function showUpdate(root, force = false, reveal = true) {
  const l = await listClosed(root);
  const p = panel("update", "Update Closed Documents", reveal);
  p.root = root;
  p.webview.postMessage({ type: "update", root, ...l, busy: updating.has(root), force });
}

async function runUpdate(root, files, token) {
  if (updating.has(root)) throw new Error("an update is already running");
  const now = await listClosed(root);                           // exactly what was confirmed, or nothing
  const current = new Map(now.eligible.map((d) => [d.path, d.sha256]));
  if (now.token !== token || files.length !== now.eligible.length || files.some((f) => current.get(f.path) !== f.sha256)) {
    await showUpdate(root);
    throw new Error("The documents or their diagram sources changed since the list was shown; nothing was changed. Check the new list and confirm again.");
  }
  publishAll();                                                   // this window's open documents, as of now
  updating.add(root);
  try {
    const bridge = await deps.bridgeFor(root);
    const r = await commands.refreshBlocks({ python: bridge.python, root }, { files, token });
    deps.log(`[updates] ${r.id}: updated ${r.files.map((f) => f.path).join(", ")}`);
    vscode.window.showInformationMessage(`Updated ${r.files.length} closed document${r.files.length === 1 ? "" : "s"} from their diagram sources ` +
      "(written on disk; not committed).");
    // The update is complete and verified; only secondary maintenance (removing its record) may be pending.
    const warnings = Array.isArray(r.warnings) ? r.warnings.filter((w) => typeof w === "string") : [];
    for (const w of warnings) { deps.log(`[updates] ${r.id}: warning: ${w}`); vscode.window.showWarningMessage(`Feature Designer: ${w}`); }
    return { ok: true, message: `Updated ${r.files.length} document(s).` + warnings.map((w) => ` Warning: ${w}`).join(""), files: r.files };
  } catch (err) {
    deps.log(`[updates] update refused or failed: ${err.message}`);
    await refreshHeld(root);                                      // a partial outcome leaves a record to resolve
    return { ok: false, message: err.message };
  } finally {
    updating.delete(root);
    await offerClosed(root);
  }
}

// ------------------------------------------------------------------ recovery (D2, D8)
async function showRecovery(force = false, reveal = true) {
  const p = panel("recovery", "Resolve Interrupted Update", reveal);
  const all = [];
  for (const root of roots()) {
    let r;
    try { r = await deps.ask(root, "transactions", {}, false); } catch (err) { all.push({ root, error: String(err.message || err) }); continue; }
    for (const rec of r.records || []) all.push({ root, ...rec });
  }
  p.webview.postMessage({ type: "recovery", records: all, force });
}

async function runResolve(root, id, action, token) {
  if (!roots().includes(root)) throw new Error("that repository is not open in this window");
  const bridge = await deps.bridgeFor(root);
  const r = await commands.resolveTransaction({ python: bridge.python, root }, { action, id, token });
  deps.log(`[updates] ${id}: ${action}: ${r.message}`);
  await refreshHeld(root, { offer: false });
  await offerClosed(root);
  return r;
}

async function onPanelMessage(kind, m) {
  if (!m || typeof m.type !== "string") return;
  const p = views.get(kind);
  if (m.type === "ready") { if (kind === "recovery") await showRecovery(true); else if (p && p.root) await showUpdate(p.root, true); return; }
  if (m.type === "close") { if (p) p.dispose(); return; }
  if (m.type === "confirmUpdate" && kind === "update" && p && p.root) {
    if (!Array.isArray(m.files) || typeof m.token !== "string") return;
    const files = m.files.map((f) => ({ path: String(f.path), sha256: String(f.sha256) }));
    const r = await runUpdate(p.root, files, m.token);
    if (views.get("update") === p) p.webview.postMessage({ type: "result", ...r });    // unless it was closed meanwhile
    if (views.get("update") === p) await showUpdate(p.root, true, false);   // drawn again: the buttons work again
    return;
  }
  if (m.type === "resolve" && kind === "recovery") {
    if (typeof m.root !== "string" || !["complete", "undo", "abandon"].includes(m.action)) return;
    try {
      const r = await runResolve(m.root, m.id, m.action, m.token);
      if (views.get("recovery") === p) p.webview.postMessage({ type: "result", ok: r.ok, message: r.message, files: r.files || [], note: r.note || "" });
    } catch (err) {
      if (views.get("recovery") === p) p.webview.postMessage({ type: "result", ok: false, message: String(err.message || err) });
    }
    await showRecovery(true, false);
  }
}

// ------------------------------------------------------------------ activation
function activate(context, d) {
  deps = { ...d, context };
  const watch = vscode.workspace.createFileSystemWatcher("**/designs/diagrams/.transactions/**");
  let timer = null;
  const changed = (uri) => {
    if (/[\\/]windows[\\/]/.test(uri.fsPath)) return;          // heartbeats of the windows
    clearTimeout(timer);
    timer = setTimeout(() => { for (const root of roots()) refreshHeld(root).catch(() => {}); }, 300);
  };
  context.subscriptions.push(
    watch, watch.onDidCreate(changed), watch.onDidChange(changed), watch.onDidDelete(changed),
    vscode.window.tabGroups.onDidChangeTabs(() => {                  // what is open changed: publish it, recount the strip
      publishSoon();
      clearTimeout(recount);
      recount = setTimeout(() => {
        if (![...deps.panels.values()].some((s) => s.size)) return;
        for (const r of roots()) if (closed.has(r)) offerClosed(r).catch(() => {});
      }, 1000);
    }),
    vscode.workspace.onDidChangeTextDocument((e) => {                 // only when its unsaved state changes
      const k = e.document.uri.toString();
      if (dirtyState.get(k) !== e.document.isDirty) { dirtyState.set(k, e.document.isDirty); publishSoon(); }
    }),
    vscode.workspace.onDidSaveTextDocument(publishSoon),
    vscode.workspace.onDidCloseTextDocument(publishSoon),
    vscode.workspace.onDidGrantWorkspaceTrust(() => { publishAll(); for (const r of roots()) refreshHeld(r).catch(() => {}); }),
    vscode.workspace.onDidChangeConfiguration((e) => {     // an interpreter chosen after start-up: check for records now
      if (e.affectsConfiguration("featureDesigner.pythonPath")) setTimeout(() => { for (const r of roots()) refreshHeld(r).catch(() => {}); }, 500);
    }),
    vscode.commands.registerCommand("featureDesigner.updateClosedDocuments", async () => {
      const rs = roots();
      if (!rs.length) { vscode.window.showInformationMessage("Open the repository folder first."); return; }
      await showUpdate(rs[0]);
    }),
    vscode.commands.registerCommand("featureDesigner.resolveUpdate", () => showRecovery()),
    { dispose: () => { clearInterval(heartbeat); for (const r of roots()) presence.remove(r, windowId); } },
  );
  sweepAll();
  publishAll();
  heartbeat = setInterval(heartbeatTick, presence.HEARTBEAT_MS);
  setTimeout(() => { for (const r of roots()) refreshHeld(r).catch((err) => deps.log(`[updates] ${err.message}`)); }, 1500);
  return {
    windowId: () => windowId,
    isHeld, refreshHeld, offerClosed, showUpdate, showRecovery,
    heldPaths: (root) => [...((held.get(root) || {}).paths || [])],
    closedNote: (root) => closed.get(root) || null,
    publishNow: publishAll,
  };
}

function deactivate() { clearInterval(heartbeat); for (const r of roots()) presence.remove(r, windowId); }

module.exports = { activate, deactivate };
