// Feature Designer (T-97 Phase 2): a custom *text* editor for designs/features/**/*.md.
// The Markdown TextDocument is the only model: the webview renders VS Code's current buffer
// (including unsaved changes made in the text editor or Mark Sharp) and sends intents; this
// host asks `python -m tools.design designer --serve` for the edit and applies it as one
// WorkspaceEdit (one undo step), only to the exact text it was computed from. Diagram blocks are
// rendered from their authoritative sources (T-97 PR B); the only file this extension creates is
// a new diagram, through the design tooling's own `new diagram` command (src/commands.js).
"use strict";
const vscode = require("vscode");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { Bridge } = require("./bridge");
const { replacements, sha256, StaleEditError } = require("./edits");
const { ensurePython, pickInterpreter, interpreterProblem, SETTING } = require("./python");
const commands = require("./commands");
const sync = require("./sync");

const VIEW_TYPE = "featureDesigner.editor";
const INDEX = "designs/index/feature-index.md";
const FEATURES = "designs/features/";
let output;
const bridges = new Map();                       // repository root -> Bridge
const panels = new Map();                        // document uri -> Set<WebviewPanel>
const acknowledged = new Set();                  // document uris whose "also open elsewhere" warning was accepted
// Fault injection for the automated tests only (see activate): nothing here is set in normal use.
const testFaults = { failNextInsertion: false, failNextReconcileDocument: false, autoRefreshDelayMs: 0 };
const storm = new sync.StormGuard();             // C5: many sources changed at once
const busy = new Set();                          // document uris being reconciled: never refreshed meanwhile
let recoveryDir = null;                          // durable records of Apply to source until it completes (C3)

const log = (s) => output && output.appendLine(`${new Date().toISOString()} ${s}`);

function rootOf(uri) {
  const folder = vscode.workspace.getWorkspaceFolder(uri);
  if (!folder) throw new Error("open the repository folder in VS Code first (File → Open Folder)");
  if (!fs.existsSync(path.join(folder.uri.fsPath, "tools", "design", "__main__.py")))
    throw new Error("this folder does not contain the design tooling (tools/design)");
  return folder.uri.fsPath;
}

function relPath(root, uri) { return path.relative(root, uri.fsPath).split(path.sep).join("/"); }
function eolOf(doc) { return doc.eol === vscode.EndOfLine.CRLF ? "\r\n" : "\n"; }

async function bridgeFor(root, prompt = true) {
  // Restricted Mode: never run the repository's tooling. (The manifest also declares this, but VS Code does
  // not enforce it for extensions loaded in development mode, which is how Feature Designer runs before release.)
  if (!vscode.workspace.isTrusted) throw new Error("this workspace is not trusted, so Feature Designer does not run the design tooling");
  let b = bridges.get(root);
  if (!b) {
    const isFile = (p) => { try { return fs.statSync(p).isFile(); } catch { return false; } };
    const python = await ensurePython(vscode, root, log, (p) => fs.existsSync(p), prompt, isFile);
    b = new Bridge({ python, root, log });
    bridges.set(root, b);
  }
  return b;
}

async function ask(root, op, fields, prompt = true) {
  let bridge;
  try { bridge = await bridgeFor(root, prompt); } catch (err) { throw err; }
  let response;
  try { response = await bridge.request(op, fields); }
  catch (err) {                                    // a failed start: forget this process so a retry starts afresh
    if (err.startup) {
      if (bridges.get(root) === bridge) bridges.delete(root);   // never drop a replacement another request created
      bridge.dispose();
      err.interpreter = true;
    }
    throw err;
  }
  if (!response.ok) {
    const e = new Error(response.error ? response.error.message : "the design tooling refused the request");
    e.refused = true;
    throw e;
  }
  return response;
}

/** Apply a designer response to `doc` as one WorkspaceEdit, only if `doc` still has the text it was computed from. */
async function applyResponse(doc, response) {
  const reps = replacements(doc.getText(), response, eolOf(doc));      // throws StaleEditError
  if (!reps.length) return false;
  const edit = new vscode.WorkspaceEdit();
  for (const r of reps) edit.replace(doc.uri, new vscode.Range(doc.positionAt(r.start), doc.positionAt(r.end)), r.text);
  if (!(await vscode.workspace.applyEdit(edit))) throw new Error("VS Code refused the edit; nothing was changed");
  return true;
}

/** Tabs that show the same file in another custom editor (for example Mark Sharp). */
function otherCustomEditors(uri) {
  const names = [];
  for (const group of vscode.window.tabGroups.all)
    for (const tab of group.tabs)
      if (tab.input instanceof vscode.TabInputCustom && tab.input.uri.toString() === uri.toString() && tab.input.viewType !== VIEW_TYPE)
        names.push(tab.input.viewType === "msharp.customEditor" ? "Mark Sharp" : tab.input.viewType);
  return [...new Set(names)];
}

/** The start of a diagram block's marker for `id`, with or without its fingerprint (diagram library U13). */
const markerOf = (id) => `<!-- diagram:start ${id} `;

/** Before changing a document that is also open in another custom editor (Mark Sharp), ask once. */
async function confirmOtherEditors(document, action) {
  const others = otherCustomEditors(document.uri);
  if (!others.length || acknowledged.has(document.uri.toString())) return true;
  const answer = await vscode.window.showWarningMessage(
    `This file is also open in ${others.join(", ")}. Feature Designer edits VS Code's shared document, but text you are ` +
    `still typing in ${others.join(", ")} may not have reached it yet. Pause typing there (or save) before inserting.`,
    { modal: true }, action);
  if (answer !== action) return false;
  acknowledged.add(document.uri.toString());
  return true;
}

/** Open a diagram's authoritative source at its Mermaid block (Edit Diagram). Never opens a diagram with a problem. */
async function openSource(root, id) {
  const r = await ask(root, "resolve", { diagram_id: id });
  if (r.problem) { const e = new Error(`Diagram ${id} cannot be opened: it ${r.problem}`); e.refused = true; throw e; }
  const target = path.resolve(root, ...String(r.path).split("/"));
  if (!target.startsWith(root + path.sep)) throw new Error("the diagram source is outside the repository");
  const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(target));
  const pos = new vscode.Position(Math.max(0, (r.line || 1) - 1), 0);
  await vscode.window.showTextDocument(doc, { selection: new vscode.Range(pos, pos), preview: false, viewColumn: vscode.ViewColumn.Beside });
  if (r.editor === "architecture-docs")                  // decision B6: never written from here
    vscode.window.showInformationMessage(`${r.id} is an architecture diagram in ${r.path}. Changes to it go through ` +
      "technical-lead's documentation workflow; Feature Designer never writes under docs/architecture/.");
  log(`[edit] ${id} → ${r.path}:${r.line}`);
  return r;
}

const sha256Bytes = (buf) => crypto.createHash("sha256").update(buf).digest("hex");
const postAll = (key, msg) => { for (const p of panels.get(key) || []) p.webview.postMessage(msg); };
const fullRange = (doc) => new vscode.Range(doc.positionAt(0), doc.positionAt(doc.getText().length));
function refused(message) { const e = new Error(message); e.refused = true; return e; }

/** Whether the document is also open in a plain text editor tab. */
function textEditorOpen(uri) {
  return vscode.window.tabGroups.all.some((g) => g.tabs.some((t) => t.input instanceof vscode.TabInputText && t.input.uri.toString() === uri.toString()));
}

// ------------------------------------------------------------------ source changes (B3, C1, C2, C5)
const sourceTimers = new Map();                  // repository root -> pending sync

/** A file changed on disk: if it is a diagram source, refresh the open documents (debounced). */
function onSourceEvent(uri) {
  const folder = vscode.workspace.getWorkspaceFolder(uri);
  if (!folder) return;
  const root = folder.uri.fsPath, rel = relPath(root, uri);
  if (!sync.isSourcePath(rel)) return;           // a feature document's own save never triggers a refresh
  storm.record(`${root}|${rel}`, Date.now());
  clearTimeout(sourceTimers.get(root));
  sourceTimers.set(root, setTimeout(() => syncOpenDocuments(root).catch((err) => log(`[sync] ${err.stack || err}`)), 400));
}

/** Every open feature document shown in Feature Designer under `root`, refreshed or offered a refresh. */
async function syncOpenDocuments(root, { manual = false } = {}) {
  if (!vscode.workspace.isTrusted) return;
  const now = Date.now();
  const isStorm = !manual && storm.isStorm(now), count = storm.size(now);
  if (isStorm) log(`[sync] ${count} diagram sources changed within ${sync.STORM_WINDOW_MS / 1000} s: no automatic refresh`);
  for (const [key, set] of panels) {
    if (!set.size) continue;
    const doc = vscode.workspace.textDocuments.find((d) => d.uri.toString() === key);
    if (!doc) continue;
    let docRoot;
    try { docRoot = rootOf(doc.uri); } catch { continue; }
    if (docRoot !== root) continue;
    await refreshOpenDocument(doc, { storm: isStorm, sources: count }).catch((err) => log(`[sync] ${relPath(root, doc.uri)}: ${err.message}`));
  }
}

/** C1: automatic only for a clean document shown exclusively in Feature Designer, as one undoable
 *  edit that is never saved; otherwise the document is left alone and "Refresh now" is offered. */
async function refreshOpenDocument(doc, { storm: isStorm = false, sources = 0 } = {}) {
  const key = doc.uri.toString(), root = rootOf(doc.uri), rel = relPath(root, doc.uri);
  const version = doc.version;
  const r = await ask(root, "refresh", { path: rel, text: doc.getText() }, false);
  if (!r.edits.length) { postAll(key, { type: "syncNote", note: null, unless: "partial" }); return "none"; }
  const ids = sync.idsOfEdits(r.edits);
  const now = () => ({ busy: busy.has(key), storm: isStorm, dirty: doc.isDirty, otherEditors: otherCustomEditors(doc.uri),
                       textEditor: textEditorOpen(doc.uri), designerViews: (panels.get(key) || new Set()).size });
  let d = sync.decide(now());
  if (d.action === "skip") return "skip";
  if (d.action === "auto") {
    if (testFaults.autoRefreshDelayMs) { const ms = testFaults.autoRefreshDelayMs; testFaults.autoRefreshDelayMs = 0; await new Promise((res) => setTimeout(res, ms)); }
    d = sync.decide(now());                       // checked again immediately before applying
    if (d.action === "auto" && doc.version === version) {
      try {
        await applyResponse(doc, r);              // the base-text guard: only the exact text it was computed from
        log(`[sync] ${rel}: refreshed ${ids.join(", ")} from their sources (one edit, not saved)`);
        postAll(key, { type: "syncNote", note: { kind: "auto", ids } });
        return "auto";
      } catch (err) { log(`[sync] ${rel}: not refreshed automatically (${err.message})`); d = { action: "manual", reason: "changed" }; }
    } else if (d.action === "auto" || d.action === "skip") d = { action: d.action === "skip" ? "skip" : "manual", reason: "changed" };
    if (d.action === "skip") return "skip";
  }
  log(`[sync] ${rel}: ${ids.join(", ")} out of date; not refreshed automatically (${d.reason})`);
  postAll(key, { type: "syncNote", note: { kind: "manual", reason: d.reason, ids, sources, editors: d.editors || [] } });
  return "manual";
}

// ------------------------------------------------------------------ Apply to source: recovery records (C3)
function saveRecovery(meta, original) {
  fs.mkdirSync(recoveryDir, { recursive: true });
  const id = `${Date.now()}-${crypto.randomBytes(4).toString("hex")}`;
  fs.writeFileSync(path.join(recoveryDir, `${id}.original`), original);           // the source exactly as it was
  const record = { id, time: new Date().toISOString(), state: "started", ...meta };
  fs.writeFileSync(path.join(recoveryDir, `${id}.json`), JSON.stringify(record, null, 2));
  return record;
}
function updateRecovery(record) { fs.writeFileSync(path.join(recoveryDir, `${record.id}.json`), JSON.stringify(record, null, 2)); }
function dropRecovery(id) { for (const ext of [".json", ".original"]) { try { fs.unlinkSync(path.join(recoveryDir, id + ext)); } catch { /* gone */ } } }
function listRecovery() {
  if (!recoveryDir || !fs.existsSync(recoveryDir)) return [];
  return fs.readdirSync(recoveryDir).filter((n) => n.endsWith(".json"))
    .map((n) => { try { return JSON.parse(fs.readFileSync(path.join(recoveryDir, n), "utf8")); } catch { return null; } })
    .filter((r) => r && typeof r.id === "string" && /^[0-9]+-[0-9a-f]{8}$/.test(r.id));
}
const recoveryOriginal = (id) => path.join(recoveryDir, `${id}.original`);

/** Write `bytesOrText` into a source through the editor and save it; true only when the file on disk is exactly that. */
async function writeSourceThroughEditor(srcDoc, srcPath, text) {
  const edit = new vscode.WorkspaceEdit();
  edit.replace(srcDoc.uri, fullRange(srcDoc), text);
  if (!(await vscode.workspace.applyEdit(edit))) throw new Error("VS Code refused the edit");
  if (!(await srcDoc.save())) throw new Error("VS Code did not save the file");
  if (!fs.readFileSync(srcPath).equals(Buffer.from(text, "utf8"))) throw new Error("the saved file is not what was written");
}

/** Recovery after a partial Apply to source: "finish" updates the block, "restore" puts the original
 *  source back (only if the source is still exactly what was written), "open" shows the preserved
 *  original, "dismiss" keeps the current source and forgets the record. Each step is guarded. */
async function recoveryAction(id, kind) {
  const record = listRecovery().find((r) => r.id === id);
  if (!record) { vscode.window.showInformationMessage("That interrupted operation was already resolved."); return; }
  const srcPath = path.join(record.root, ...record.source.split("/"));
  if (kind === "open") {
    await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(vscode.Uri.file(recoveryOriginal(id))), { preview: true });
    return;
  }
  if (kind === "dismiss") {
    const keep = "Keep the current source";
    if ((await vscode.window.showWarningMessage(`Forget the preserved original of ${record.source}? The current source stays as it is.`, { modal: true }, keep)) !== keep) return;
    dropRecovery(id); log(`[recovery] ${id}: dismissed; ${record.source} kept as is`);
    return;
  }
  if (kind === "restore") {
    const srcDoc = await vscode.workspace.openTextDocument(vscode.Uri.file(srcPath));
    if (srcDoc.isDirty) throw refused(`${record.source} has unsaved changes; save or revert it first. Nothing was restored.`);
    if (!fs.existsSync(srcPath) || sha256Bytes(fs.readFileSync(srcPath)) !== record.writtenSha)
      throw refused(`${record.source} changed after Apply to source, so it was not restored automatically. The original is preserved: use "Open the preserved original".`);
    const original = fs.readFileSync(recoveryOriginal(id));
    await writeSourceThroughEditor(srcDoc, srcPath, original.toString("utf8"));
    dropRecovery(id);
    log(`[recovery] ${id}: restored the original ${record.source}`);
    vscode.window.showInformationMessage(`Restored the original ${record.source}. The feature document was not changed.`);
    for (const [key] of panels) postAll(key, { type: "syncNote", note: null, only: "partial" });
    return;
  }
  if (kind === "finish") {
    const docUri = vscode.Uri.file(path.join(record.root, ...record.document.split("/")));
    const doc = await vscode.workspace.openTextDocument(docUri);
    const r = await ask(record.root, "refresh", { path: record.document, text: doc.getText() });
    const mine = r.edits.filter((e) => sync.idsOfEdits([e])[0] === record.diagram);
    if (mine.length) await applyResponse(doc, { ...r, edits: mine });
    const after = await ask(record.root, "blocks", { path: record.document, text: doc.getText() });
    const states = after.blocks.filter((b) => b.id === record.diagram).map((b) => b.state);
    if (!states.length || states.some((s) => s !== "current"))
      throw refused(`The ${record.diagram} block in ${record.document} still differs from its source (${states.join(", ") || "not found"}): review it again. The record is kept.`);
    dropRecovery(id);
    log(`[recovery] ${id}: the ${record.diagram} block in ${record.document} now matches its source`);
    vscode.window.showInformationMessage(`Completed: the ${record.diagram} block in ${record.document} now matches the saved source (not saved).`);
    postAll(docUri.toString(), { type: "syncNote", note: null, only: "partial" });
  }
}

async function offerRecovery() {
  const pending = listRecovery();
  if (!pending.length) return;
  const review = "Review…";
  const answer = await vscode.window.showWarningMessage(`${pending.length} Apply to source operation(s) did not complete. The original source content is preserved.`, review);
  if (answer === review) await vscode.commands.executeCommand("featureDesigner.recovery");
}

/** After an insertion, warn if another editor rewrites the document and drops the inserted block. */
function watchForOverwrite(doc, marker) {
  const count = (t) => t.split(marker).length - 1;
  const expected = count(doc.getText());
  const sub = vscode.workspace.onDidChangeTextDocument((e) => {
    if (e.document.uri.toString() !== doc.uri.toString()) return;
    if (e.reason === vscode.TextDocumentChangeReason.Undo || e.reason === vscode.TextDocumentChangeReason.Redo) {
      sub.dispose();                                 // the user's own Undo/Redo is not another editor's overwrite
      return;
    }
    if (count(e.document.getText()) < expected) {
      sub.dispose();
      log(`[interop] ${relPath(rootOf(doc.uri), doc.uri)}: an inserted diagram block disappeared after another change`);
      vscode.window.showWarningMessage("The diagram block just inserted by Feature Designer was removed by another change to this file " +
        "(possibly another editor writing its own copy). Nothing else was changed; insert it again or use Undo in that editor.");
    }
  });
  setTimeout(() => sub.dispose(), 8000);
}

class DesignerEditor {
  constructor(context) { this.context = context; }

  async resolveCustomTextEditor(document, panel) {
    if (!vscode.workspace.isTrusted) {                // a static notice: no scripts, no Python
      panel.webview.options = { enableScripts: false, enableCommandUris: false, localResourceRoots: [] };
      panel.webview.html = restrictedHtml();
      const sub = vscode.workspace.onDidGrantWorkspaceTrust(() => { sub.dispose(); panel.webview.html = restrictedHtml(true); });
      panel.onDidDispose(() => sub.dispose());
      log(`[trust] ${document.uri.fsPath}: not opened (Restricted Mode)`);
      return;
    }
    const key = document.uri.toString();
    if (!panels.has(key)) panels.set(key, new Set());
    panels.get(key).add(panel);
    const ext = this.context.extensionUri;
    const roots = [vscode.Uri.joinPath(ext, "media"), ...["markdown-it", "dompurify", "mermaid"].map((m) => vscode.Uri.joinPath(ext, "node_modules", m, "dist"))];
    panel.webview.options = { enableScripts: true, enableCommandUris: false, localResourceRoots: roots };
    panel.webview.html = html(panel.webview, ext);
    let timer = null, checkTimer = null;
    const send = () => panel.webview.postMessage({ type: "doc", text: document.getText(), version: document.version,
                                                   others: otherCustomEditors(document.uri) });
    // The state of every diagram block (PR B): each is rendered from its authoritative source, and a
    // copy that differs is shown as such. Blocks that no longer match their sources are reported,
    // never repaired silently. Read only: nothing here changes the document.
    const updateBlocks = async () => {
      const text = document.getText(), version = document.version;
      if (!/<!--\s*diagram:start/.test(text)) {
        panel.webview.postMessage({ type: "blocks", version, blocks: [] });
        panel.webview.postMessage({ type: "generated", stale: 0, blocking: [], conflicts: [] });
        return;
      }
      try {
        const root = rootOf(document.uri);
        const r = await ask(root, "blocks", { path: relPath(root, document.uri), text }, false);
        panel.webview.postMessage({ type: "blocks", version, blocks: r.blocks });
        panel.webview.postMessage({ type: "generated", stale: r.stale, blocking: r.blocking, conflicts: r.conflicts });
        if (r.stale || r.blocking.length || r.conflicts.length) log(`[generated] ${relPath(root, document.uri)}: ${r.stale} stale block(s), ${r.conflicts.length} conflict(s), ${r.blocking.length} problem(s)`);
      } catch (err) {
        log(`[blocks] not checked: ${err.message}`);
        panel.webview.postMessage({ type: "blocks", version, blocks: null, error: String(err.message || err) });
      }
    };
    const subs = [
      vscode.workspace.onDidChangeTextDocument((e) => {
        if (e.document.uri.toString() !== key) return;
        clearTimeout(timer); timer = setTimeout(send, 40);          // the buffer, including unsaved changes
        clearTimeout(checkTimer); checkTimer = setTimeout(updateBlocks, 300);
      }),
      vscode.window.tabGroups.onDidChangeTabs(() => panel.webview.postMessage({ type: "others", others: otherCustomEditors(document.uri) })),
    ];
    panel.onDidDispose(() => { subs.forEach((s) => s.dispose()); clearTimeout(timer); clearTimeout(checkTimer); panels.get(key).delete(panel); });
    panel.updateBlocks = () => { clearTimeout(checkTimer); checkTimer = setTimeout(updateBlocks, 300); };
    panel.onDidChangeViewState(() => panel.webview.postMessage({ type: "others", others: otherCustomEditors(document.uri) }));
    panel.webview.onDidReceiveMessage((msg) => this.handle(document, panel, msg).catch((err) => {
      if (!(err instanceof StaleEditError) && !err.refused) log(`[error] ${err.stack || err}`);
      panel.webview.postMessage({ type: "error", message: String(err.message || err) });
      send();
    }));
  }

  async handle(document, panel, msg) {
    if (!msg || typeof msg.type !== "string") return;
    const root = rootOf(document.uri);
    const rel = relPath(root, document.uri);
    switch (msg.type) {
      case "ready":
        panel.webview.postMessage({ type: "doc", text: document.getText(), version: document.version, rel,
                                    others: otherCustomEditors(document.uri) });
        panel.updateBlocks();
        for (const r of listRecovery().filter((x) => x.root === root && x.document === rel && x.state === "partial"))
          panel.webview.postMessage({ type: "partial", recovery: r.id, id: r.diagram, source: r.source, reason: r.reason });
        return;
      case "library":
        try { panel.webview.postMessage({ type: "library", data: await ask(root, "library", {}) }); }
        catch (err) {                              // the dialog shows the error with Retry / Change Interpreter
          log(`[library] ${err.message}`);
          panel.webview.postMessage({ type: "libraryError", message: String(err.message || err), interpreter: !!err.interpreter });
        }
        return;
      case "selectPython":
        await vscode.commands.executeCommand("featureDesigner.selectPython");
        panel.webview.postMessage({ type: "pythonChanged" });
        return;
      case "undo": case "redo":
        await vscode.commands.executeCommand(msg.type);
        return;
      case "showLog":
        output.show(true);
        return;
      case "refreshNow": {                            // guarded manual refresh (B3): one undoable edit, not saved
        if (!Number.isInteger(msg.version)) return;
        if (msg.version !== document.version) throw new StaleEditError("the document changed; nothing was refreshed (try again)");
        if (busy.has(document.uri.toString())) throw refused("this document is being reconciled; try again in a moment");
        if (!(await confirmOtherEditors(document, "Refresh"))) return;
        const r = await ask(root, "refresh", { path: rel, text: document.getText() });
        if (document.version !== msg.version) throw new StaleEditError("the document changed; nothing was refreshed (try again)");
        const ids = sync.idsOfEdits(r.edits);
        if (r.edits.length) await applyResponse(document, r);
        log(`[sync] ${rel}: refreshed ${ids.join(", ") || "nothing"} on request`);
        postAll(document.uri.toString(), { type: "syncNote", note: r.edits.length ? { kind: "refreshed", ids } : null });
        return;
      }
      case "save":
        await document.save();
        return;
      case "showChanges": {                           // C2: the saved file against the refreshed buffer
        const saved = vscode.Uri.from({ scheme: "featuredesigner-saved", path: document.uri.path });
        await vscode.commands.executeCommand("vscode.diff", saved, document.uri, `${path.basename(document.uri.fsPath)}: saved ↔ now (not saved)`,
                                             { viewColumn: vscode.ViewColumn.Beside, preview: true });
        return;
      }
      case "checkSources":
        panel.updateBlocks();
        await syncOpenDocuments(root, { manual: true });
        return;
      case "reviewConflict": {                        // both plans, read only; the dialog confirms one of them
        if (!Number.isInteger(msg.line) || !Number.isInteger(msg.version)) return;
        if (msg.version !== document.version) throw new StaleEditError("the document changed; review the block again");
        const text = document.getText();
        const plan = async (action) => {
          try {
            const p = await ask(root, "reconcile", { path: rel, text, line: msg.line, action });
            return { token: p.token, diff: p.diff, warning: p.warning, replaces: p.replaces_source_changes, state: p.state,
                     source: p.source ? p.source.path : "" };
          } catch (err) { if (err.refused) return { error: String(err.message) }; throw err; }
        };
        const discard = await plan("discard"), apply = await plan("apply-to-source");
        if (document.version !== msg.version) throw new StaleEditError("the document changed; review the block again");
        panel.webview.postMessage({ type: "review", line: msg.line, id: msg.id, version: msg.version, discard, apply });
        return;
      }
      case "applyReconcile":
        if (!["discard", "apply-to-source"].includes(msg.action) || !Number.isInteger(msg.line) || !Number.isInteger(msg.version) ||
            typeof msg.token !== "string") return;
        await reconcileBlock(document, root, rel, msg);
        return;
      case "recovery":
        if (typeof msg.recovery !== "string" || !["finish", "restore", "open", "dismiss"].includes(msg.kind)) return;
        await recoveryAction(msg.recovery, msg.kind);
        return;
      case "editDiagram":                            // the pencil: the authoritative source, by stable ID or alias
        if (typeof msg.id !== "string" || !msg.id) return;
        await openSource(root, msg.id);
        return;
      case "previewName": {                           // Make New: the file name `new diagram` would create (read only)
        if (!Number.isInteger(msg.seq)) return;
        let r;
        try { r = await ask(root, "diagram-name", { owner: msg.owner, title: msg.title, category: msg.category }); }
        catch (err) { r = { path: "", problem: String(err.message || err) }; }
        panel.webview.postMessage({ type: "name", seq: msg.seq, path: r.path, problem: r.problem });
        return;
      }
      case "makeNew": {
        if (!Number.isInteger(msg.at) || !Number.isInteger(msg.version)) return;
        if (msg.version !== document.version) throw new StaleEditError("the document changed; nothing was created (try again)");
        if (!(await confirmOtherEditors(document, "Create and Insert"))) return;
        if (document.version !== msg.version) throw new StaleEditError("the document changed while you confirmed; nothing was created (try again)");
        const bridge = await bridgeFor(root);
        const made = await commands.newDiagram({ python: bridge.python, root },
                                               { owner: msg.owner, title: msg.title, category: msg.category });
        log(`[new] ${made.diagram_id} created and registered: ${made.path}`);
        let failure = "";                             // from here the diagram exists: never report "nothing was created"
        try {
          if (testFaults.failNextInsertion) { testFaults.failNextInsertion = false; throw new StaleEditError("the document changed while the diagram was created (simulated)"); }
          if (document.version !== msg.version) throw new StaleEditError("the document changed while the diagram was created");
          const response = await ask(root, "insert", { path: rel, text: document.getText(), at: msg.at, diagram_id: made.diagram_id });
          if (document.version !== msg.version) throw new StaleEditError("the document changed while the diagram was prepared");
          await applyResponse(document, response);
          watchForOverwrite(document, markerOf(made.diagram_id));
        } catch (err) { failure = String(err.message || err); }
        if (failure) {                                // the additional requirement: its ID, and a way to place it later
          log(`[new] ${made.diagram_id} not inserted: ${failure}`);
          panel.webview.postMessage({ type: "placeLater", id: made.diagram_id, path: made.path, reason: failure });
          const add = "Add Existing Diagram…";
          vscode.window.showWarningMessage(`Diagram ${made.diagram_id} was created and registered (${made.path}), but it ` +
            `was not inserted: ${failure}. Use Add Existing Diagram to place it.`, add)
            .then((a) => { if (a === add) panel.webview.postMessage({ type: "placeNow", id: made.diagram_id }); });
          return;
        }
        log(`[insert] ${rel}: ${made.diagram_id} before line ${msg.at + 1}`);
        panel.webview.postMessage({ type: "created", id: made.diagram_id, path: made.path });
        await openSource(root, made.diagram_id).catch((err) => log(`[edit] ${err.message}`));
        return;
      }
      case "removeBlock": {                           // decision B7: a retired diagram's reference, by the user's click
        if (!Number.isInteger(msg.line) || !Number.isInteger(msg.version) || typeof msg.id !== "string") return;
        if (msg.version !== document.version) throw new StaleEditError("the document changed; nothing was removed (try again)");
        if (!(await confirmOtherEditors(document, "Remove"))) return;
        const response = await ask(root, "remove-block", { path: rel, text: document.getText(), line: msg.line });
        if (document.version !== msg.version) throw new StaleEditError("the document changed; nothing was removed (try again)");
        await applyResponse(document, response);
        log(`[remove] ${rel}: the block for retired ${msg.id} at line ${msg.line + 1}`);
        return;
      }
      case "insertDiagram": {
        if (!Number.isInteger(msg.at) || typeof msg.id !== "string" || !Number.isInteger(msg.version)) return;
        if (msg.version !== document.version) throw new StaleEditError("the document changed; nothing was inserted (try again)");
        if (!(await confirmOtherEditors(document, "Insert"))) return;
        if (document.version !== msg.version) throw new StaleEditError("the document changed while you confirmed; nothing was inserted (try again)");
        const response = await ask(root, "insert", { path: rel, text: document.getText(), at: msg.at, diagram_id: msg.id });
        if (document.version !== msg.version) throw new StaleEditError("the document changed while the diagram was prepared; nothing was inserted (try again)");
        await applyResponse(document, response);
        watchForOverwrite(document, markerOf(msg.id));     // fingerprinted markers too (PR A changed the marker form)
        log(`[insert] ${rel}: ${msg.id} before line ${msg.at + 1}`);
        return;
      }
      default:
        return;
    }
  }
}

/** Discard manual change, or Apply to source (C3). Both are planned again on the current text and
 *  must match the reviewed token; Apply to source writes the source first (saved) and then the
 *  block, and reports exactly what happened if only the first step succeeded. */
async function reconcileBlock(document, root, rel, msg) {
  const key = document.uri.toString();
  if (msg.version !== document.version) throw refused("The document changed since the review; nothing was changed. Review the block again.");
  if (!(await confirmOtherEditors(document, msg.action === "discard" ? "Discard" : "Apply"))) return;
  busy.add(key);                                  // no automatic refresh of this document meanwhile
  try {
    const plan = await ask(root, "reconcile", { path: rel, text: document.getText(), line: msg.line, action: msg.action });
    if (plan.token !== msg.token || document.version !== msg.version)
      throw refused("The document or the diagram source changed since the review; nothing was changed. Review the block again.");
    if (plan.replaces_source_changes && msg.replaceConfirmed !== true)
      throw refused("Applying would replace changes made in the source; confirm that explicitly in the review. Nothing was changed.");
    if (msg.action === "discard") {
      await applyResponse(document, plan);
      log(`[reconcile] ${rel}: discarded the manual change to ${plan.id}`);
      postAll(key, { type: "reconciled", text: `Discarded the manual change to ${plan.id}: the block matches its source again (one undoable edit; not saved).` });
      return;
    }
    await applySourceThenBlock(document, root, rel, plan, msg);
  } finally { busy.delete(key); }
}

async function applySourceThenBlock(document, root, rel, plan, msg) {
  const key = document.uri.toString(), src = plan.source;
  const srcPath = path.resolve(root, ...src.path.split("/"));
  if (!srcPath.startsWith(root + path.sep) || src.path.startsWith("docs/architecture/") || !src.path.startsWith("designs/"))
    throw refused(`${src.path} is not a feature-owned diagram source; nothing was changed`);   // the design tooling refuses it too
  const srcDoc = await vscode.workspace.openTextDocument(vscode.Uri.file(srcPath));
  if (srcDoc.isDirty) throw refused(`${src.path} has unsaved changes; save or revert it first. Nothing was changed.`);
  const original = fs.readFileSync(srcPath);
  // immediately before applying: both revisions are still the reviewed ones
  if (sha256Bytes(original) !== src.sha256 || sha256(srcDoc.getText()) !== src.sha256)
    throw refused(`${src.path} changed since the review; nothing was changed. Review the block again.`);
  if (document.version !== msg.version || sha256(document.getText()) !== plan.base.sha256)
    throw refused("The document changed since the review; nothing was changed. Review the block again.");
  const record = saveRecovery({ root, source: src.path, document: rel, diagram: plan.id, writtenSha: sha256Bytes(Buffer.from(src.text, "utf8")),
                                originalSha: sha256Bytes(original) }, original);
  try {                                           // 1. the source, through the editor, saved and verified
    await writeSourceThroughEditor(srcDoc, srcPath, src.text);
  } catch (err) {
    let restored = false;
    try {
      if (!fs.readFileSync(srcPath).equals(original) || srcDoc.isDirty) await writeSourceThroughEditor(srcDoc, srcPath, original.toString("utf8"));
      restored = fs.readFileSync(srcPath).equals(original);
    } catch (e2) { log(`[reconcile] could not put ${src.path} back: ${e2.message}`); }
    if (restored) { dropRecovery(record.id); throw refused(`Nothing was applied: ${src.path} could not be written (${err.message}); it is unchanged.`); }
    record.state = "partial"; record.reason = `the source could not be written cleanly (${err.message})`; updateRecovery(record);
    throw refused(`${src.path} may have been changed and could not be put back (${err.message}). Its original is preserved: run "Feature Designer: Resolve Interrupted Apply to Source".`);
  }
  try {                                           // 2. the block, only on the reviewed text
    if (testFaults.failNextReconcileDocument) { testFaults.failNextReconcileDocument = false; throw new Error("the document could not be edited (simulated)"); }
    if (document.version !== msg.version) throw new StaleEditError("the document changed while the source was being saved");
    await applyResponse(document, plan);
  } catch (err) {
    record.state = "partial"; record.reason = String(err.message || err); updateRecovery(record);
    log(`[reconcile] PARTIAL ${rel}: ${src.path} saved, the ${plan.id} block NOT updated (${record.reason}); recovery ${record.id}`);
    postAll(key, { type: "partial", recovery: record.id, id: plan.id, source: src.path, reason: record.reason });
    const finish = "Update the block now", restore = "Restore the original source";
    vscode.window.showWarningMessage(`Partly done: ${src.path} was updated and saved, but the ${plan.id} block in ${rel} was NOT updated ` +
      `(${record.reason}). The original source is preserved.`, finish, restore)
      .then((a) => a && recoveryAction(record.id, a === finish ? "finish" : "restore").catch((e) => vscode.window.showErrorMessage(e.message)));
    return;
  }
  dropRecovery(record.id);
  log(`[reconcile] ${rel}: applied the ${plan.id} block to ${src.path} (saved) and updated the block (not saved)`);
  postAll(key, { type: "reconciled", text: `Applied to source: saved ${src.path} and updated the ${plan.id} block here (not saved). ` +
    `Ctrl+Z in this document reverts only the block; the source change is saved and is undone separately in ${path.basename(src.path)}.` });
}

/** When a feature file open in Feature Designer is saved, bring designs/index/feature-index.md up to date. */
async function syncFeatureIndex(doc) {
  if (!panels.has(doc.uri.toString()) || !panels.get(doc.uri.toString()).size) return;
  const root = rootOf(doc.uri);
  let response;                                       // the indexes on disk describe the saved files only
  try { response = await ask(root, "feature-index", { texts: {} }, false); }
  catch (err) {
    log(`[index] not updated: ${err.message}`);
    vscode.window.showWarningMessage(`Feature Designer could not update ${INDEX} (${err.message}). Run python -m tools.design index.`);
    return;
  }
  await syncGenerated(root, response);
  if (response.diagram_index) await syncGenerated(root, response.diagram_index);   // its "Used by" column follows the blocks
}

/** Replace one generated index through the editor, only if it has no unsaved changes and still has the base text. */
async function syncGenerated(root, generated) {
  const rel = generated.path;
  if (!generated.changed) return;
  const indexPath = path.join(root, ...rel.split("/"));
  if (!fs.existsSync(indexPath)) { vscode.window.showWarningMessage(`${rel} is missing: run python -m tools.design index`); return; }
  const indexDoc = await vscode.workspace.openTextDocument(vscode.Uri.file(indexPath));
  if (indexDoc.isDirty) {
    vscode.window.showWarningMessage(`${rel} has unsaved changes, so Feature Designer did not update it; save or revert it, then run python -m tools.design index.`);
    return;
  }
  if (!generated.base || sha256(indexDoc.getText()) !== generated.base.sha256) {
    log(`[index] ${rel} changed while it was being computed (or has a BOM or mixed line endings); not updated`);
    vscode.window.showWarningMessage(`Feature Designer did not update ${rel}: it changed while being computed. Run python -m tools.design index.`);
    return;
  }
  const eol = eolOf(indexDoc);
  const edit = new vscode.WorkspaceEdit();
  edit.replace(indexDoc.uri, new vscode.Range(indexDoc.positionAt(0), indexDoc.positionAt(indexDoc.getText().length)),
               eol === "\n" ? generated.content : generated.content.replace(/\n/g, eol));
  if (await vscode.workspace.applyEdit(edit)) { await indexDoc.save(); log(`[index] updated ${rel}`); }
}

function restrictedHtml(nowTrusted) {
  return `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>Feature Designer</title></head><body style="font-family: var(--vscode-font-family); padding: 24px; color: var(--vscode-foreground)">
<h2>Feature Designer is disabled in Restricted Mode</h2>
<p>${nowTrusted ? "The workspace is now trusted: close this tab and open the file with Feature Designer again."
                : "Feature Designer runs this repository's design tooling, so it needs a trusted workspace. Open the file with the text editor, or trust the folder first."}</p>
</body></html>`;
}

function html(webview, ext) {
  const nonce = crypto.randomBytes(18).toString("base64");
  const uri = (...p) => webview.asWebviewUri(vscode.Uri.joinPath(ext, ...p));
  const csp = [`default-src 'none'`, `img-src ${webview.cspSource} data:`, `style-src ${webview.cspSource} 'unsafe-inline'`,
               `font-src ${webview.cspSource}`, `script-src 'nonce-${nonce}'`, `base-uri 'none'`, `form-action 'none'`].join("; ");
  const scripts = [uri("node_modules", "markdown-it", "dist", "markdown-it.min.js"), uri("node_modules", "dompurify", "dist", "purify.min.js"),
                   uri("node_modules", "mermaid", "dist", "mermaid.min.js"), uri("media", "core.js")];
  return `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="${uri("media", "designer.css")}"><title>Feature Designer</title></head>
<body><div id="top"><div id="toolbar"></div><div id="banner" hidden></div><div id="stale" hidden></div><div id="notice" hidden></div><div id="strip" hidden role="status" aria-live="polite"></div><div id="status" role="status" aria-live="polite"></div></div><main id="doc" aria-label="Feature document"></main>
${scripts.map((s) => `<script nonce="${nonce}" src="${s}"></script>`).join("\n")}
<script nonce="${nonce}">window.FD_HOST = { api: acquireVsCodeApi() };</script>
<script nonce="${nonce}" src="${uri("media", "designer.js")}"></script>
</body></html>`;
}

function activate(context) {
  output = vscode.window.createOutputChannel("Feature Designer");
  recoveryDir = path.join(context.globalStorageUri.fsPath, "recovery");   // outside the repository; survives restarts
  context.subscriptions.push(
    output,
    vscode.window.registerCustomEditorProvider(VIEW_TYPE, new DesignerEditor(context),
      { webviewOptions: { retainContextWhenHidden: true }, supportsMultipleEditorsPerDocument: true }),
    vscode.commands.registerCommand("featureDesigner.showLog", () => output.show(true)),
    vscode.commands.registerCommand("featureDesigner.checkSources", async () => {   // when a file watcher missed a change
      const roots = new Set();
      for (const [key, set] of panels) { if (!set.size) continue; try { roots.add(rootOf(vscode.Uri.parse(key))); } catch { /* not a repository */ } for (const p of set) p.updateBlocks(); }
      for (const root of roots) await syncOpenDocuments(root, { manual: true });
    }),
    vscode.commands.registerCommand("featureDesigner.recovery", async () => {
      const pending = listRecovery();
      if (!pending.length) { vscode.window.showInformationMessage("No interrupted Apply to source operation."); return; }
      const pick = pending.length === 1 ? pending[0] : (await vscode.window.showQuickPick(pending.map((r) => ({ label: `${r.diagram}: ${r.source}`, description: r.time, r })), { placeHolder: "Interrupted Apply to source" }) || {}).r;
      if (!pick) return;
      const choices = { "Restore the original source": "restore", "Update the block": "finish", "Open the preserved original": "open", "Keep the current source (forget)": "dismiss" };
      const answer = await vscode.window.showWarningMessage(`Apply to source for ${pick.diagram} did not complete (${pick.reason || "interrupted"}): ${pick.source} ` +
        `was changed, the block in ${pick.document} was not. The original source is preserved.`, { modal: true }, ...Object.keys(choices));
      if (answer) await recoveryAction(pick.id, choices[answer]).catch((e) => vscode.window.showErrorMessage(e.message));
    }),
    vscode.workspace.registerTextDocumentContentProvider("featuredesigner-saved",       // Show changes: the file as saved
      { provideTextDocumentContent: (uri) => { try { return fs.readFileSync(vscode.Uri.file(uri.path).fsPath, "utf8"); } catch { return ""; } } }),
    vscode.commands.registerCommand("featureDesigner.selectPython", async () => {
      const picked = await pickInterpreter(vscode);
      if (!picked) return;
      const problem = interpreterProblem(picked, (p) => { try { return fs.statSync(p).isFile(); } catch { return false; } });
      if (problem) { vscode.window.showErrorMessage(`${problem}. Nothing was saved.`); log(`[python] not saved: ${problem}`); return; }
      await vscode.workspace.getConfiguration("featureDesigner").update(SETTING, picked, vscode.ConfigurationTarget.Global);
      for (const b of bridges.values()) b.dispose();
      bridges.clear();
      log(`[python] saved featureDesigner.${SETTING} = ${picked}`);
    }),
    vscode.workspace.onDidSaveTextDocument((doc) => syncFeatureIndex(doc).catch((err) => log(`[index] ${err.stack || err}`))),
    ...sourceWatchers(),
    vscode.workspace.onDidChangeConfiguration((e) => {          // a new interpreter: start a new process next time
      if (!e.affectsConfiguration(`featureDesigner.${SETTING}`)) return;
      for (const b of bridges.values()) b.dispose();
      bridges.clear();
      log(`[python] featureDesigner.${SETTING} changed; the design tooling restarts on the next request`);
    }),
    { dispose: () => { for (const b of bridges.values()) b.dispose(); bridges.clear(); } });
  setTimeout(() => offerRecovery().catch((err) => log(`[recovery] ${err.message}`)), 1500);
  // Hooks for the automated tests (process ID, simulated crash, fault injection); inert unless called.
  return {
    bridgePid: (root) => (bridges.get(root) ? bridges.get(root).pid : null),
    killBridgeProcess: (root) => { const b = bridges.get(root); if (b && b.proc) b.proc.kill(); return !!(b && b.proc); },
    failNextInsertion: () => { testFaults.failNextInsertion = true; return true; },   // Make New: the insertion after creation fails once
    failNextReconcileDocument: () => { testFaults.failNextReconcileDocument = true; return true; },   // Apply to source: the block edit fails once
    delayNextAutoRefresh: () => { testFaults.autoRefreshDelayMs = 2500; return true; },   // time to type before an automatic refresh applies
    pendingRecovery: () => listRecovery().map((r) => ({ id: r.id, state: r.state, source: r.source })),
  };
}

/** Re-render open views when a diagram source, an architecture document or the registry changes on
 *  disk (saved in VS Code or changed outside it). Rendering only: no document is changed here. */
function sourceWatchers() {
  let timer = null;
  const again = (uri) => {
    clearTimeout(timer); timer = setTimeout(() => { for (const set of panels.values()) for (const p of set) if (p.updateBlocks) p.updateBlocks(); }, 250);
    if (uri) onSourceEvent(uri);                    // PR B2a: refresh open documents (C1) or offer it
  };
  return ["**/designs/**/*.md", "**/designs/diagrams/registry.yml", "**/docs/architecture/**/*.md"].flatMap((glob) => {
    const w = vscode.workspace.createFileSystemWatcher(glob);
    return [w, w.onDidChange(again), w.onDidCreate(again), w.onDidDelete(again)];
  });
}

function deactivate() { for (const b of bridges.values()) b.dispose(); bridges.clear(); }

module.exports = { activate, deactivate };
