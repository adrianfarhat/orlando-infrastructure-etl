// Source-change synchronization rules (T-97 PR B2a, decisions B3, C1, C5). Pure functions, so
// the rules can be tested without VS Code; src/extension.js applies them.
"use strict";

const STORM_COUNT = 5;          // C5: more than 5 sources ...
const STORM_WINDOW_MS = 2000;   // ... changed within 2 seconds: no automatic refresh

/** Whether a repository-relative path is something diagram blocks are generated from: the
 *  registry, an architecture document, or a standalone source in a designs/**\/diagrams/ folder.
 *  Feature documents themselves are not sources: saving one never triggers a refresh. */
function isSourcePath(rel) {
  if (typeof rel !== "string" || !rel || rel.startsWith("../") || rel.includes("/../")) return false;
  if (rel === "designs/diagrams/registry.yml") return true;
  if (!rel.toLowerCase().endsWith(".md")) return false;
  if (rel.startsWith("docs/architecture/")) return true;
  const parts = rel.split("/");
  return parts[0] === "designs" && parts.length >= 3 && parts[parts.length - 2] === "diagrams";
}

/** Counts distinct source paths changed within a sliding window (C5). */
class StormGuard {
  constructor(count = STORM_COUNT, windowMs = STORM_WINDOW_MS) { this.count = count; this.windowMs = windowMs; this.seen = new Map(); }
  record(rel, now) { this.seen.set(rel, now); }
  /** True when more than `count` distinct sources changed in the window ending at `now`. */
  isStorm(now) {
    for (const [rel, t] of this.seen) if (now - t > this.windowMs) this.seen.delete(rel);
    return this.seen.size > this.count;
  }
  size(now) { this.isStorm(now); return this.seen.size; }
}

/** What to do with one open feature document that has refreshable blocks (C1):
 *  "auto"   refresh it now (one undoable edit, never saved);
 *  "manual" leave it and offer "Refresh now", with the reason;
 *  "skip"   it is being reconciled; do nothing now. */
function decide({ busy = false, storm = false, dirty = false, otherEditors = [], textEditor = false, designerViews = 0 }) {
  if (busy) return { action: "skip" };
  if (!designerViews) return { action: "manual", reason: "not-in-designer" };
  if (storm) return { action: "manual", reason: "storm" };
  if (dirty) return { action: "manual", reason: "unsaved" };
  if (otherEditors.length) return { action: "manual", reason: "other-editor", editors: otherEditors };
  if (textEditor) return { action: "manual", reason: "text-editor" };
  return { action: "auto" };
}

/** The diagram IDs named by the start markers in a set of edits (for the notice). */
function idsOfEdits(edits) {
  const ids = [];
  for (const e of edits || []) {
    const m = /^<!--\s*diagram:start\s+(\S+)/.exec((e.lines || [])[0] || "");
    if (m && !ids.includes(m[1])) ids.push(m[1]);
  }
  return ids;
}

module.exports = { isSourcePath, StormGuard, decide, idsOfEdits, STORM_COUNT, STORM_WINDOW_MS };
