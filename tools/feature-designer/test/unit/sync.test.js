"use strict";
// Source-change synchronization rules (T-97 PR B2a: B3, C1, C5).
const test = require("node:test");
const assert = require("node:assert/strict");
const { isSourcePath, StormGuard, decide, idsOfEdits } = require("../../src/sync");

test("only the registry, architecture documents and standalone sources are sources; feature documents are not", () => {
  for (const p of ["designs/diagrams/registry.yml", "docs/architecture/system-architecture.md",
                   "docs/architecture/diagrams/x.md", "designs/features/diagrams/a_process_b.md",
                   "designs/features/parent/diagrams/c_other_d.md"]) assert.equal(isSourcePath(p), true, p);
  for (const p of ["designs/features/a.md", "designs/features/parent/README.md", "designs/index/feature-index.md",
                   "designs/diagrams/x.md.bak", "designs/features/diagrams/a.txt", "../designs/features/diagrams/a.md",
                   "docs/architecture/notes.txt", "", null, "web/src/diagrams/x.md"]) assert.equal(isSourcePath(p), false, String(p));
});

test("event storms: more than 5 distinct sources within 2 seconds", () => {
  const g = new StormGuard();
  for (let i = 0; i < 5; i++) g.record(`s${i}`, 1000 + i * 100);
  assert.equal(g.isStorm(1500), false);                               // exactly 5: not a storm
  g.record("s0", 1600);                                               // the same file again does not count twice
  assert.equal(g.isStorm(1600), false);
  g.record("s5", 1700);
  assert.equal(g.isStorm(1700), true);
  assert.equal(g.isStorm(5000), false);                               // the window has passed
  const slow = new StormGuard();                                      // QA M1: a steady stream seen as it happens
  const seen = [0, 350, 700, 1050, 1400, 1750].map((t, i) => slow.record(`p${i}`, t));
  assert.deepEqual(seen, [false, false, false, false, false, true]);
  assert.equal(g.size(5000), 0);
});

test("C1: automatic only for a clean document open exclusively in Feature Designer", () => {
  assert.deepEqual(decide({ designerViews: 1 }), { action: "auto" });
  assert.deepEqual(decide({ designerViews: 2 }), { action: "auto" });          // two views of one document: one refresh
  assert.equal(decide({ designerViews: 1, dirty: true }).reason, "unsaved");
  assert.equal(decide({ designerViews: 1, otherEditors: ["Mark Sharp"] }).reason, "other-editor");
  assert.equal(decide({ designerViews: 1, textEditor: true }).reason, "text-editor");
  assert.equal(decide({ designerViews: 1, storm: true }).reason, "storm");
  assert.equal(decide({ designerViews: 0 }).reason, "not-in-designer");
  assert.equal(decide({ designerViews: 1, busy: true, dirty: true }).action, "skip"); // being reconciled: untouched
});

test("diagram IDs of refresh edits", () => {
  assert.deepEqual(idsOfEdits([{ lines: ["<!-- diagram:start FD-0001-D1 sha256:0123456789abcdef -->", "x"] },
                               { lines: ["<!-- diagram:start AD-0006 sha256:0123456789abcdef -->"] },
                               { lines: ["<!-- diagram:start FD-0001-D1 sha256:fedcba9876543210 -->"] }, { lines: [] }]),
                   ["FD-0001-D1", "AD-0006"]);
});
