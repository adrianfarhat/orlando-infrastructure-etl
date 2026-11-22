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

const VIEW_TYPE = "featureDesigner.editor";
const INDEX = "designs/index/feature-index.md";
const FEATURES = "designs/features/";
let output;
const bridges = new Map();                       // repository root -> Bridge
const panels = new Map();                        // document uri -> Set<WebviewPanel>
const acknowledged = new Set();                  // document uris whose "also open elsewhere" warning was accepted
const testFaults = { failNextInsertion: false };  // fault injection for the automated tests only (see activate)

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
<body><div id="toolbar"></div><div id="banner" hidden></div><div id="stale" hidden></div><div id="notice" hidden></div><main id="doc" aria-label="Feature document"></main>
${scripts.map((s) => `<script nonce="${nonce}" src="${s}"></script>`).join("\n")}
<script nonce="${nonce}">window.FD_HOST = { api: acquireVsCodeApi() };</script>
<script nonce="${nonce}" src="${uri("media", "designer.js")}"></script>
</body></html>`;
}

function activate(context) {
  output = vscode.window.createOutputChannel("Feature Designer");
  context.subscriptions.push(
    output,
    vscode.window.registerCustomEditorProvider(VIEW_TYPE, new DesignerEditor(context),
      { webviewOptions: { retainContextWhenHidden: true }, supportsMultipleEditorsPerDocument: true }),
    vscode.commands.registerCommand("featureDesigner.showLog", () => output.show(true)),
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
  // Read-only hooks for the automated tests (process ID, simulated crash); no document access.
  return {
    bridgePid: (root) => (bridges.get(root) ? bridges.get(root).pid : null),
    killBridgeProcess: (root) => { const b = bridges.get(root); if (b && b.proc) b.proc.kill(); return !!(b && b.proc); },
    failNextInsertion: () => { testFaults.failNextInsertion = true; return true; },   // Make New: the insertion after creation fails once
  };
}

/** Re-render open views when a diagram source, an architecture document or the registry changes on
 *  disk (saved in VS Code or changed outside it). Rendering only: no document is changed here. */
function sourceWatchers() {
  let timer = null;
  const again = () => { clearTimeout(timer); timer = setTimeout(() => { for (const set of panels.values()) for (const p of set) if (p.updateBlocks) p.updateBlocks(); }, 250); };
  return ["**/designs/**/*.md", "**/designs/diagrams/registry.yml", "**/docs/architecture/**/*.md"].flatMap((glob) => {
    const w = vscode.workspace.createFileSystemWatcher(glob);
    return [w, w.onDidChange(again), w.onDidCreate(again), w.onDidDelete(again)];
  });
}

function deactivate() { for (const b of bridges.values()) b.dispose(); bridges.clear(); }

module.exports = { activate, deactivate };
