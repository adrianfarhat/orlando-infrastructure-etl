// Test-only helper (never part of the Feature Designer extension): the GUI test writes
// cmd-<n>.json into FD_TEST_CMD_DIR, this answers with res-<n>.json. Active only when that
// environment variable is set by the test launcher.
"use strict";
const vscode = require("vscode");
const fs = require("fs");
const path = require("path");

function activate(context) {
  const dir = process.env.FD_TEST_CMD_DIR;
  if (!dir) return;
  const root = () => vscode.workspace.workspaceFolders[0].uri.fsPath;
  const uriOf = (rel) => vscode.Uri.file(path.join(root(), ...rel.split("/")));
  const docOf = (rel) => vscode.workspace.textDocuments.find((d) => d.uri.fsPath.toLowerCase() === uriOf(rel).fsPath.toLowerCase());
  const ops = {
    async openWith({ path: rel, viewType, column }) {
      await vscode.commands.executeCommand("vscode.openWith", uriOf(rel), viewType, { viewColumn: column || 1, preview: false });
      return true;
    },
    async openText({ path: rel, column }) {
      const doc = await vscode.workspace.openTextDocument(uriOf(rel));
      await vscode.window.showTextDocument(doc, { viewColumn: column || 1, preview: false });
      return true;
    },
    async doc({ path: rel }) {
      const d = docOf(rel);
      return d ? { text: d.getText(), isDirty: d.isDirty, version: d.version } : null;
    },
    async replace({ path: rel, find, replace, after }) {              // one WorkspaceEdit, like typing (not saved)
      const d = docOf(rel) || await vscode.workspace.openTextDocument(uriOf(rel));
      const t = d.getText(), from = after ? t.indexOf(after) : 0, i = from < 0 ? -1 : t.indexOf(find, from);
      if (i < 0) return false;
      const e = new vscode.WorkspaceEdit();
      e.replace(d.uri, new vscode.Range(d.positionAt(i), d.positionAt(i + find.length)), replace);
      return vscode.workspace.applyEdit(e);
    },
    async save({ path: rel }) { const d = docOf(rel); return d ? d.save() : false; },
    async command({ id, args }) { await vscode.commands.executeCommand(id, ...(args || [])); return true; },
    async closeAll() { await vscode.commands.executeCommand("workbench.action.closeAllEditors"); return true; },
    async tabs() {
      return vscode.window.tabGroups.all.flatMap((g) => g.tabs.map((t) => ({
        label: t.label, group: g.viewColumn, dirty: t.isDirty, active: t.isActive,
        kind: t.input instanceof vscode.TabInputCustom ? `custom:${t.input.viewType}` : t.input instanceof vscode.TabInputText ? "text" : "other" })));
    },
    async setGlobal({ section, key, value }) {
      await vscode.workspace.getConfiguration(section).update(key, value, vscode.ConfigurationTarget.Global);
      return true;
    },
    async getGlobal({ section, key }) { return vscode.workspace.getConfiguration(section).inspect(key); },
    async designer({ fn }) {
      const ext = vscode.extensions.getExtension("orlando-infrastructure.feature-designer");
      if (!ext) return { error: "not installed" };
      if (!ext.isActive) return { active: false };
      return { active: true, value: ext.exports[fn](root()) };
    },
    async trusted() { return vscode.workspace.isTrusted; },
  };
  const seen = new Set();
  const timer = setInterval(async () => {
    let names = [];
    try { names = fs.readdirSync(dir).filter((n) => /^cmd-\d+\.json$/.test(n) && !seen.has(n)); } catch { return; }
    for (const name of names) {
      seen.add(name);
      const n = name.slice(4, -5);
      let result;
      try {
        const cmd = JSON.parse(fs.readFileSync(path.join(dir, name), "utf8"));
        result = { ok: true, value: await ops[cmd.op](cmd) };
      } catch (err) { result = { ok: false, error: String(err && err.stack || err) }; }
      fs.writeFileSync(path.join(dir, `res-${n}.tmp`), JSON.stringify(result));
      fs.renameSync(path.join(dir, `res-${n}.tmp`), path.join(dir, `res-${n}.json`));
    }
  }, 100);
  context.subscriptions.push({ dispose: () => clearInterval(timer) });
}

module.exports = { activate, deactivate() {} };
