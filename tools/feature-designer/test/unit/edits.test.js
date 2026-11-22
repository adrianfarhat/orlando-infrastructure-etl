"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { replacements, applyReplacements, sha256, StaleEditError } = require("../../src/edits");

const base = (text) => ({ sha256: sha256(text), line_count: text.split("\n").length });

/** The Python side's own semantics (tools/design/tests/test_designer_api.apply). */
function pythonApply(text, response) {
  const lines = text.split("\n").map((l) => (l.endsWith("\r") ? l.slice(0, -1) : l));
  for (const e of [...response.edits].reverse()) lines.splice(e.start, e.end - e.start, ...e.lines);
  return lines.join(response.newline);
}

function check(text, edits, newline) {
  const response = { base: base(text), newline, edits };
  const got = applyReplacements(text, replacements(text, response, newline));
  assert.equal(got, pythonApply(text, response));
  return got;
}

test("inserts before a line, in the middle, keeps every other byte", () => {
  const text = "a\nb\n\nc\n";
  assert.equal(check(text, [{ start: 2, end: 2, lines: ["X", "Y"] }], "\n"), "a\nb\nX\nY\n\nc\n");
});

test("CRLF documents keep CRLF everywhere", () => {
  const text = "a\r\nb\r\n\r\nc\r\n";
  const got = check(text, [{ start: 2, end: 2, lines: ["", "X", "Y"] }], "\r\n");
  assert.equal(got, "a\r\nb\r\n\r\nX\r\nY\r\n\r\nc\r\n");
  assert.equal(got.replace(/\r\n/g, "").includes("\n"), false);
});

test("replacing lines, several non-overlapping edits, top to bottom", () => {
  const text = "s\nold1\nold2\ne\nmid\ns\nold3\ne\n";
  check(text, [{ start: 1, end: 3, lines: ["new"] }, { start: 6, end: 7, lines: ["n2", "n3"] }], "\n");
});

test("edits at the end of the text, with and without a final newline", () => {
  check("a\nb", [{ start: 2, end: 2, lines: ["X"] }], "\n");             // after the last line
  check("a\nb\n", [{ start: 2, end: 3, lines: ["X"] }], "\n");           // through the (empty) last line
  check("a\nb\n", [{ start: 3, end: 3, lines: ["X"] }], "\n");
  check("a", [{ start: 0, end: 1, lines: [] }], "\n");
});

test("an edit is applied only to the exact text it was computed from", () => {
  const text = "a\nb\n";
  const response = { base: base(text), newline: "\n", edits: [{ start: 1, end: 1, lines: ["X"] }] };
  assert.throws(() => replacements("a\nb changed\n", response, "\n"), StaleEditError);
  assert.throws(() => replacements(text, { ...response, base: undefined }, "\n"), StaleEditError);
  assert.throws(() => replacements(text, { ...response, base: { ...response.base, line_count: 9 } }, "\n"), StaleEditError);
});

test("malformed or overlapping edits are refused", () => {
  const text = "a\nb\nc\n";
  const r = (edits) => () => replacements(text, { base: base(text), newline: "\n", edits }, "\n");
  assert.throws(r([{ start: 2, end: 1, lines: [] }]), /malformed/);
  assert.throws(r([{ start: 0, end: 99, lines: [] }]), /malformed/);
  assert.throws(r([{ start: 0, end: 0, lines: ["line\nbreak"] }]), /malformed/);
  assert.throws(r([{ start: 0, end: 2, lines: [] }, { start: 1, end: 2, lines: [] }]), /overlapping/);
});
