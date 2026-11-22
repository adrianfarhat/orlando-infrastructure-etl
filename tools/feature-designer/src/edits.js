// Turning `python -m tools.design designer` responses into text edits (no VS Code API here,
// so it is unit-tested directly). The Python side counts lines by "\n" (a "\r" before it
// belongs to the line) and proposes {start, end, lines}: replace lines start..end-1 with
// `lines`. Every response carries `base` (SHA-256 and line count of the text it was computed
// from); an edit is applied only to exactly that text, otherwise it is rejected as stale.
"use strict";
const crypto = require("crypto");

function sha256(text) {
  return crypto.createHash("sha256").update(text, "utf8").digest("hex");
}

/** Offsets [start, end) in `text` for whole lines start..end-1, and whether `end` is past the last line. */
function lineOffsets(text) {
  const starts = [0];
  for (let i = text.indexOf("\n"); i !== -1; i = text.indexOf("\n", i + 1)) starts.push(i + 1);
  return starts;                                  // starts.length === text.split("\n").length
}

class StaleEditError extends Error {}

/**
 * Text replacements {start, end, text} (character offsets into `text`) for a response, after
 * checking that `text` is exactly the text the response was computed from.
 */
function replacements(text, response, newline) {
  const base = response && response.base;
  if (!base || base.sha256 !== sha256(text) || base.line_count !== text.split("\n").length)
    throw new StaleEditError("the document changed after the edit was computed; nothing was changed");
  const nl = newline || response.newline || "\n";
  const starts = lineOffsets(text);
  const n = starts.length;
  const out = [];
  let previousEnd = -1;
  for (const e of response.edits || []) {
    if (!Number.isInteger(e.start) || !Number.isInteger(e.end) || e.start < 0 || e.end < e.start || e.end > n ||
        !Array.isArray(e.lines) || e.lines.some((l) => typeof l !== "string" || /[\r\n]/.test(l)))
      throw new Error("malformed edit from the design tooling");
    if (e.start < previousEnd) throw new Error("overlapping edits from the design tooling");
    previousEnd = e.end;
    let from, to, newText;
    if (e.end < n) {                                // ends before an existing line: whole lines with their endings
      from = starts[e.start]; to = starts[e.end];
      newText = e.lines.map((l) => l + nl).join("");
    } else if (e.start < n) {                       // runs to the end of the text (last line has no ending)
      from = starts[e.start]; to = text.length;
      newText = e.lines.join(nl);
    } else {                                        // e.start === e.end === n: after the last line
      from = to = text.length;
      newText = e.lines.length ? nl + e.lines.join(nl) : "";
    }
    out.push({ start: from, end: to, text: newText });
  }
  return out;
}

/** Apply replacements to a string (bottom-up), for tests and previews. */
function applyReplacements(text, reps) {
  let out = text;
  for (const r of [...reps].sort((a, b) => b.start - a.start)) out = out.slice(0, r.start) + r.text + out.slice(r.end);
  return out;
}

module.exports = { sha256, lineOffsets, replacements, applyReplacements, StaleEditError };
