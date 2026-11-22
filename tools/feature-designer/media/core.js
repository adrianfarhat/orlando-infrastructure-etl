/* Feature Designer: how a document is split into rendered regions (shared by the webview and
 * the unit tests). These rules only decide where the "+" is *shown*; whether a block may be
 * inserted at a position is decided by the design tooling (tools/design/designer_api.py). */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.FDCore = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const FENCE = /^ {0,3}(`{3,}|~{3,})(.*)$/;
  const GENERATED = [
    { start: /^<!-- summary:start/, end: /^<!-- summary:end -->\s*$/, kind: "summary" },
    { start: /^<!-- related-features:start/, end: /^<!-- related-features:end -->\s*$/, kind: "related" },
    { start: /^<!--\s*diagram:start\s+(\S+)\s*-->\s*$/, end: /^<!--\s*diagram:end\s*-->\s*$/, kind: "diagram" },
  ];

  function splitLines(text) {
    return text.split("\n").map((l) => (l.endsWith("\r") ? l.slice(0, -1) : l));
  }

  /* CommonMark fences: closed by the same character, at least as long, with nothing after it. */
  function fenceStep(line, fence) {
    const m = FENCE.exec(line);
    if (fence === null) {
      if (!m) return { fence: null, isFence: false };
      if (m[1][0] === "`" && m[2].includes("`")) return { fence: null, isFence: false };
      return { fence: { ch: m[1][0], len: m[1].length }, isFence: true };
    }
    if (m && m[1][0] === fence.ch && m[1].length >= fence.len && m[2].trim() === "") return { fence: null, isFence: true };
    return { fence, isFence: false };
  }

  /* Top-level regions by line: front matter, generated blocks (read-only), <details> groups and
   * ordinary Markdown. Markers inside code fences are examples, not regions. */
  function segments(text) {
    const lines = splitLines(text);
    const out = [];
    let i = 0;
    if (lines[0] === "---") {
      const end = lines.indexOf("---", 1);
      if (end > 0) { out.push({ kind: "frontmatter", start: 0, end: end + 1 }); i = end + 1; }
    }
    let md = i, fence = null;
    const flush = (upto) => {
      if (upto > md && lines.slice(md, upto).some((l) => l.trim() !== "")) out.push({ kind: "markdown", start: md, end: upto });
    };
    while (i < lines.length) {
      const line = lines[i];
      if (fence === null) {
        let matched = null;
        for (const g of GENERATED) { const m = g.start.exec(line); if (m) { matched = { g, m }; break; } }
        if (matched) {
          let j = i + 1;
          while (j < lines.length && !matched.g.end.test(lines[j])) j++;
          if (j < lines.length) {
            flush(i);
            out.push({ kind: matched.g.kind, start: i, end: j + 1, id: matched.g.kind === "diagram" ? matched.m[1] : undefined });
            i = j + 1; md = i; continue;
          }
        }
        if (/^<details[\s>]/i.test(line.trim())) {
          let depth = 0, j = i, f = null;
          for (; j < lines.length; j++) {
            const st = fenceStep(lines[j], f); const inCode = f !== null || st.isFence; f = st.fence;
            if (inCode) continue;
            depth += (lines[j].match(/<details[\s>]/gi) || []).length;
            depth -= (lines[j].match(/<\/details>/gi) || []).length;
            if (depth <= 0) break;
          }
          if (j < lines.length) { flush(i); out.push({ kind: "details", start: i, end: j + 1 }); i = j + 1; md = i; continue; }
        }
      }
      fence = fenceStep(line, fence).fence;
      i++;
    }
    flush(lines.length);
    return out;
  }

  /* Where the "+" is offered: after a block that ends inside "## 1. Objective" … end of section 6. */
  function insertionZone(text) {
    const lines = splitLines(text);
    let start = -1, end = lines.length, fence = null, seenSix = false;
    for (let i = 0; i < lines.length; i++) {
      const st = fenceStep(lines[i], fence); const inCode = fence !== null || st.isFence; fence = st.fence;
      if (inCode) continue;
      const l = lines[i];
      if (start < 0) { if (/^## 1\. Objective\s*$/.test(l)) start = i; continue; }
      if (/^## 6\./.test(l)) { seenSix = true; continue; }
      if (seenSix && (/^ {0,3}((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$/.test(l) || /^#{1,2}\s/.test(l) || /^\s*<details[\s>]/i.test(l))) { end = i; break; }
    }
    return start < 0 ? null : { start, end };
  }

  return { splitLines, fenceStep, segments, insertionZone };
});
