"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const C = require("../../media/core");
const { REPO } = require("./helpers");

const template = fs.readFileSync(path.join(REPO, "designs", "templates", "feature-spec.md"), "utf8")
  .replace(/\{\{\w+\}\}/g, "x");

test("segments: front matter, generated blocks and details groups are separate regions", () => {
  const kinds = C.segments(template).map((s) => s.kind);
  assert.equal(kinds[0], "frontmatter");
  for (const k of ["summary", "related", "details"]) assert.ok(kinds.includes(k), k);
});

test("markers inside code fences are examples, not regions", () => {
  const doc = "## 1. Objective\n\n```markdown\n<!-- diagram:start a/b -->\n<!-- diagram:end -->\n```\n";
  assert.deepEqual(C.segments(doc).map((s) => s.kind), ["markdown"]);
  const real = "## 1. Objective\n\n<!-- diagram:start a/b -->\ncap\n<!-- diagram:end -->\n";
  assert.deepEqual(C.segments(real).map((s) => [s.kind, s.id]), [["markdown", undefined], ["diagram", "a/b"]]);
});

test("a start marker with a fingerprint (U13) is the same diagram region, and the ID excludes it", () => {
  const fp = "## 1. Objective\n\n<!-- diagram:start AD-0013 sha256:0123456789abcdef -->\ncap\n<!-- diagram:end -->\n";
  assert.deepEqual(C.segments(fp).map((s) => [s.kind, s.id]), [["markdown", undefined], ["diagram", "AD-0013"]]);
});

test("the + is offered from section 1 to the end of section 6", () => {
  const lines = C.splitLines(template);
  const z = C.insertionZone(template);
  assert.equal(lines[z.start], "## 1. Objective");
  assert.equal(lines[z.end], "---");
  assert.equal(C.insertionZone("# no sections\n"), null);
});

test("CRLF text is split into the same lines", () => {
  assert.deepEqual(C.splitLines("a\r\nb\r\n"), ["a", "b", ""]);
});
