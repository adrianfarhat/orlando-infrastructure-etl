// Which feature documents this VS Code window has open (T-97 PR B2b-1, decision D6).
//
// The registry lock says nothing about another window's unsaved documents, so every Feature
// Designer window publishes the feature documents it has open in a tab, and whether each has
// unsaved changes, in designs/diagrams/.transactions/windows/<window>.json, rewritten every 5 s
// (a heartbeat) and whenever a tab or a document's unsaved state changes. `refresh-blocks` never
// writes a document listed by any window record (tools/design/transactions.py): a record is never
// ignored because its heartbeat is old (the window may be suspended or hung with unsaved changes).
// The records of windows on this computer whose process has ended are removed here (sweep); others
// stay until their window removes them or `transaction forget-window` removes one explicitly.
//
// Not detectable (documented): a VS Code window that does not run Feature Designer (another
// installation, the extension not loaded, Restricted Mode), and other editors.
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const crypto = require("crypto");

const DIR = ["designs", "diagrams", ".transactions", "windows"];
const HEARTBEAT_MS = 5000;
const NAME = /^[0-9a-f]{16}\.json$/;
const FORMAT = "feature-designer-window";

function isLink(p, fsImpl = fs) {
  try { return fsImpl.lstatSync(p).isSymbolicLink(); } catch { return false; }   // Node reports junctions as links
}

/** The windows folder of `root`, never through a symbolic link or junction (created when asked). */
function windowsDir(root, create, fsImpl = fs) {
  let p = root;
  for (const part of DIR) {
    p = path.join(p, part);
    if (isLink(p, fsImpl)) throw new Error(`${DIR.join("/")} goes through a symbolic link or junction; not written`);
    if (create && !fsImpl.existsSync(p)) fsImpl.mkdirSync(p);
  }
  return p;
}

function alive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try { process.kill(pid, 0); return true; } catch (e) { return e.code === "EPERM"; }   // signal 0: a check only
}

/** Write this window's record atomically (a temporary file renamed over it). */
function publish(root, id, documents, { fsImpl = fs, now = Date.now(), pid = process.pid, host = os.hostname(), platform = process.platform } = {}) {
  const dir = windowsDir(root, true, fsImpl);
  const record = { format: FORMAT, version: 1, window: id, pid, host, platform, heartbeat: now / 1000,
                   documents: documents.map((d) => ({ path: d.path, dirty: !!d.dirty })) };
  const file = path.join(dir, `${id}.json`), tmp = path.join(dir, `.${id}.${crypto.randomBytes(4).toString("hex")}.tmp`);
  fsImpl.writeFileSync(tmp, JSON.stringify(record));
  try { fsImpl.renameSync(tmp, file); } catch (err) { try { fsImpl.unlinkSync(tmp); } catch { /* gone */ } throw err; }
  return record;
}

function remove(root, id, fsImpl = fs) {
  try { fsImpl.unlinkSync(path.join(windowsDir(root, false, fsImpl), `${id}.json`)); } catch { /* not there */ }
}

/** Remove the records of windows on this computer whose process has ended (never this window's). */
function sweep(root, id, { fsImpl = fs, host = os.hostname(), platform = process.platform, isAlive = alive } = {}) {
  let dir;
  try { dir = windowsDir(root, false, fsImpl); if (!fsImpl.existsSync(dir)) return []; } catch { return []; }
  const removed = [];
  for (const name of fsImpl.readdirSync(dir)) {
    if (!NAME.test(name) || name === `${id}.json`) continue;
    const p = path.join(dir, name);
    try {
      if (isLink(p, fsImpl)) continue;
      const r = JSON.parse(fsImpl.readFileSync(p, "utf8"));
      // the same computer AND the same platform: a WSL window shares the computer name but not its process IDs (QA)
      if (r && r.format === FORMAT && typeof r.host === "string" && r.host.toLowerCase() === host.toLowerCase() &&
          r.platform === platform && !isAlive(r.pid)) {
        fsImpl.unlinkSync(p);
        removed.push(name);
      }
    } catch { /* unreadable or being replaced: left for its owner */ }
  }
  return removed;
}

/** Feature documents under `root` open in a tab of this window, or with unsaved changes. */
function openDocuments(vscode, root) {
  const out = new Map();
  const add = (uri, dirty) => {
    if (!uri || uri.scheme !== "file") return;
    const rel = path.relative(root, uri.fsPath).split(path.sep).join("/");
    if (!rel.startsWith("designs/features/") || !rel.toLowerCase().endsWith(".md") || rel.includes("..")) return;
    out.set(rel, (out.get(rel) || false) || !!dirty);
  };
  for (const group of vscode.window.tabGroups.all)
    for (const tab of group.tabs) {
      const i = tab.input;
      if (!i) continue;
      if (i.uri) add(i.uri, tab.isDirty);
      if (i.original) add(i.original, false);
      if (i.modified) add(i.modified, tab.isDirty);
    }
  for (const d of vscode.workspace.textDocuments) if (d.isDirty) add(d.uri, true);
  return [...out].map(([p, dirty]) => ({ path: p, dirty }));
}

module.exports = { publish, remove, sweep, openDocuments, windowsDir, alive, HEARTBEAT_MS, FORMAT };
