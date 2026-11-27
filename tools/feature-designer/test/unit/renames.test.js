// T-97 PR B2b-2b: the rename integration's pure logic (batches, verification on disk, the one prompt and its
// choices, the E6 strip row, wording) and the command builders for adopt-moves --sha256 and move-back.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const R = require("../../src/renames");
const commands = require("../../src/commands");

const ROOT = path.join(os.tmpdir(), "fd-renames-root");
const uri = (rel, scheme = "file") => ({ scheme, fsPath: path.join(ROOT, ...rel.split("/")) });
const SHA = "a".repeat(64), SHA2 = "b".repeat(64), TOKEN = "0123456789abcdef";
const SRC = "designs/features/diagrams/a_process_flow.md", NEW = "designs/features/moved/diagrams/a_process_flow.md";
const sha = (s) => crypto.createHash("sha256").update(s).digest("hex");

test("a rename event becomes repository pairs; other schemes, other folders and outside paths are ignored", () => {
  const pairs = R.batchOf(ROOT, [
    { oldUri: uri(SRC), newUri: uri(NEW) },
    { oldUri: uri("designs/features"), newUri: uri("designs/specs") },                  // a folder
    { oldUri: uri("docs/architecture/diagrams/x.md"), newUri: uri("docs/architecture/x.md") },
    { oldUri: uri("web/src/a.ts"), newUri: uri("web/src/b.ts") },                     // not a design path
    { oldUri: uri(SRC, "untitled"), newUri: uri(NEW, "untitled") },
    { oldUri: { scheme: "file", fsPath: path.join(os.tmpdir(), "elsewhere.md") }, newUri: uri(NEW) },
  ]);
  assert.deepEqual(pairs, [{ from: SRC, to: NEW }, { from: "designs/features", to: "designs/specs" },
                           { from: "docs/architecture/diagrams/x.md", to: "docs/architecture/x.md" }]);
});

test("one key per batch whatever the order; paths in or under a batch path count as the batch (C5)", () => {
  const a = [{ from: "designs/features/x", to: "designs/features/y" }, { from: SRC, to: NEW }];
  assert.equal(R.batchKey(ROOT, a), R.batchKey(ROOT, [...a].reverse()));
  assert.notEqual(R.batchKey(ROOT, a), R.batchKey(ROOT, a.slice(1)));
  assert.ok(R.inBatch(a, "designs/features/x/diagrams/one.md"));
  assert.ok(R.inBatch(a, "designs/features/y/diagrams/one.md"));
  assert.ok(R.inBatch(a, NEW));
  assert.ok(!R.inBatch(a, "designs/features/xy/diagrams/one.md"));
  assert.ok(!R.inBatch(a, "designs/diagrams/registry.yml"));
});

function repo(files) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "fd-renames-"));
  for (const [rel, body] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(root, rel)), { recursive: true });
    fs.writeFileSync(path.join(root, rel), body);
  }
  return root;
}

test("the SHA-256 at exactly a path: letter case as listed, a folder is not a file, nothing is null", () => {
  const root = repo({ "designs/features/diagrams/A.md": "x" });
  assert.equal(R.exactSha(root, "designs/features/diagrams/A.md"), sha("x"));
  assert.equal(R.exactSha(root, "designs/features/diagrams/a.md"), null);           // other letter case: not this name
  assert.equal(R.exactSha(root, "designs/features/diagrams"), "");
  assert.equal(R.exactSha(root, "designs/features/none/b.md"), null);
});

test("the letter case on disk: a case-only rename reported with the old case is read back from the folder", () => {
  const root = repo({ "designs/features/Diag/X-Flow.md": "x" });
  assert.equal(R.diskCase(root, "designs/features/diag/x-flow.md"), "designs/features/Diag/X-Flow.md");
  assert.equal(R.diskCase(root, "designs/features/Diag/X-Flow.md"), "designs/features/Diag/X-Flow.md");
  assert.equal(R.diskCase(root, "designs/features/none/y.md"), "designs/features/none/y.md");
});

test("verification after the rename: only a file at its new path with its bytes from before, and gone from the old path, is ok", () => {
  const root = repo({ [NEW]: "body", "designs/features/b/diagrams/b.md": "edited", "designs/features/diagrams/c.md": "c",
                      "designs/features/c2/diagrams/c.md": "c", "designs/features/diagrams/D.md": "d" });
  const out = R.verify(root, [
    { diagram_id: "FD-0001-D1", from: SRC, to: NEW, sha256: sha("body") },
    { diagram_id: "FD-0001-D2", from: "designs/features/diagrams/b.md", to: "designs/features/b/diagrams/b.md", sha256: sha("before") },
    { diagram_id: "FD-0001-D3", from: "designs/features/diagrams/c.md", to: "designs/features/c2/diagrams/c.md", sha256: sha("c") },
    { diagram_id: "FD-0001-D4", from: "designs/features/diagrams/e.md", to: "designs/features/e/diagrams/e.md", sha256: sha("e") },
    { diagram_id: "FD-0001-D5", from: "designs/features/diagrams/d.md", to: "designs/features/diagrams/D.md", sha256: sha("d") },   // case only
    { diagram_id: "FD-0001-D6", from: "designs/features/diagrams/x.md", to: NEW, sha256: null },
  ]);
  assert.deepEqual(out.map((s) => s.state), ["ok", "changed", "changed", "missing", "ok", "ok"]);
  assert.match(out[1].why, /does not have the content it had before the rename/);
  assert.match(out[2].why, /still exists \(a copy is not a move\)/);
  assert.ok(out[5].unknownBefore && !out[0].unknownBefore);
});

test("referencing documents: open in this window or closed", () => {
  const refs = { "FD-0001-D1": ["designs/features/one.md line 12: diagram block FD-0001-D1", "designs/diagrams/registry.yml: FD-0001-D2 was created from it"],
                 "FD-0001-D2": ["designs/features/two.md line 3: diagram block FD-0001-D2", "designs/features/one.md line 40: diagram block FD-0001-D2"] };
  const d = R.referencingDocuments(refs, ["FD-0001-D1", "FD-0001-D2"], new Set([process.platform === "win32" ? "designs/features/two.md" : "designs/features/two.md"]));
  assert.deepEqual(d, { open: ["designs/features/two.md"], closed: ["designs/features/one.md"] });
});

const src = (over = {}) => ({ diagram_id: "FD-0001-D1", title: "Flow", from: SRC, to: NEW, sha256: SHA, state: "ok", why: "", ...over });
const adoptOk = { possible: true, moves: [{ from: SRC, to: NEW, sha256: SHA }], problems: [], excluded: [] };
const restoreOk = { possible: true, moves: [{ from: NEW, to: SRC, sha256: SHA }] };

test("the prompt: one per batch, Not now first (VS Code focuses it), the four choices, the IDs old → new and the documents", () => {
  const m = R.promptModel({ sources: [src()], adopt: adoptOk, restore: restoreOk, docs: { open: ["designs/features/o.md"], closed: ["designs/features/c1.md", "designs/features/c2.md"] } });
  assert.deepEqual(m.choices, ["Not now", "Update the registry", "Update the registry and 2 closed documents", "Move the files back"]);
  assert.equal(m.message, "1 diagram source was renamed: the registry still names the old path");
  assert.match(m.detail, /FD-0001-D1 "Flow": designs\/features\/diagrams\/a_process_flow\.md → designs\/features\/moved\/diagrams\/a_process_flow\.md/);
  assert.match(m.detail, /1 open document \(designs\/features\/o\.md\); 2 closed documents \(designs\/features\/c1\.md, designs\/features\/c2\.md\)/);
  assert.match(m.detail, /the ID, owner, title and category stay the same/);
  assert.match(m.detail, /nothing is written to them before you confirm/);
  assert.match(m.detail, /recorded, recoverable move; the registry is not changed/);
  assert.doesNotMatch(m.detail, /atomic/i);
});

test("the prompt without closed documents, without an adoption, or with a changed file", () => {
  const none = R.promptModel({ sources: [src()], adopt: adoptOk, restore: restoreOk, docs: { open: [], closed: [] } });
  assert.deepEqual(none.choices, ["Not now", "Update the registry", "Move the files back"]);
  const changed = R.promptModel({ sources: [src({ state: "changed", why: "x.md does not have the content it had before the rename" })],
                                  adopt: { possible: false, moves: [], problems: [], excluded: [] },
                                  restore: { possible: false, moves: [], reason: "a file is not as it was renamed" }, docs: { open: [], closed: [] } });
  assert.deepEqual(changed.choices, ["Not now"]);
  assert.match(changed.detail, /FD-0001-D1: changed — x\.md does not have the content it had before the rename; it is not adopted/);
  assert.match(changed.detail, /\[not adopted\]/);
  assert.match(changed.detail, /Move the files back: not possible \(a file is not as it was renamed\)/);
  const refused = R.promptModel({ sources: [src()], adopt: { possible: false, moves: [], problems: ["a Git operation is in progress (MERGE_HEAD in the Git folder): finish or abort it first (D4)"], excluded: [] },
                                  restore: restoreOk, docs: { open: [], closed: ["designs/features/c.md"] },
                                  warnings: ["designs/features/diagrams/a.md is open with unsaved changes in a VS Code window"],
                                  held: [{ path: "designs/features/f.md", record: "tx-20261127T000000Z-0123abcd" }] });
  assert.deepEqual(refused.choices, ["Not now", "Move the files back"]);
  assert.match(refused.detail, /Git operation is in progress/);
  assert.match(refused.detail, /Update the registry: not possible now/);
  assert.match(refused.detail, /held by the unresolved record tx-20261127T000000Z-0123abcd: VS Code cannot prevent the rename/);
  assert.match(refused.detail, /open with unsaved changes/);
});

test("a partly adoptable batch lists the rest with their problems; an external move says what cannot be proven", () => {
  const two = [src(), src({ diagram_id: "FD-0001-D2", from: "designs/features/diagrams/b.md", to: "designs/features/x/b.md" })];
  const m = R.promptModel({ sources: two, adopt: { ...adoptOk, excluded: [{ move: { from: two[1].from }, problems: ["FD-0001-D2 (…): designs/features/x/b.md is not a feature-owned diagram source"] }] },
                            restore: { possible: false, moves: [], reason: "" }, docs: { open: [], closed: [] } });
  assert.equal(m.message, "2 diagram sources were renamed: the registry still names the old paths");
  assert.match(m.detail, /FD-0001-D2 .*\[not adopted\]/);
  assert.match(m.detail, /is not a feature-owned diagram source/);
  assert.match(m.detail, /only the path of 1 registry entry changes/);
  const ext = R.promptModel({ sources: [src({ sha256: null, unknownBefore: true })], adopt: adoptOk, restore: restoreOk, docs: { open: [], closed: [] }, external: true });
  assert.equal(ext.message, "1 diagram source is not at the registered path: the registry still names the old path");
  assert.match(ext.detail, /content these files had before they were moved is not known here/);
});

test("choices: a label maps to one action; Escape, Cancel and anything else is Not now (nothing written)", () => {
  assert.equal(R.choiceOf("Update the registry"), "registry");
  assert.equal(R.choiceOf("Update the registry and 1 closed document"), "registry-and-closed");
  assert.equal(R.choiceOf("Update the registry and 12 closed documents"), "registry-and-closed");
  assert.equal(R.choiceOf("Move the files back"), "back");
  for (const x of [undefined, "Not now", "Cancel", "", "update the registry"]) assert.equal(R.choiceOf(x), "not-now");
});

test("the E6 strip row: moved and ambiguous sources counted, missing ones reported, architecture never offered (G5)", () => {
  assert.equal(R.movedNote({ matches: [], ambiguous: [], missing: [], architecture: [{ diagram_id: "AD-0001" }] }), null);
  assert.equal(R.movedNote(null), null);
  const n = R.movedNote({ matches: [{ diagram_id: "FD-0001-D1", problem: "" }, { diagram_id: "FD-0001-D2", problem: "x" }],
                          ambiguous: [{ diagram_id: "FD-0001-D3" }], missing: [{ diagram_id: "FD-0001-D4" }], architecture: [{}] });
  assert.equal(n.text, "3 moved sources: registry not updated; 1 found at several paths (never guessed); 1 source is missing with no file holding its ID (E7).");
  assert.deepEqual([n.count, n.adoptable, n.ambiguous, n.missing], [3, 1, 1, 1]);
  assert.equal(R.movedNote({ matches: [{ diagram_id: "FD-0001-D1", problem: "" }] }).text, "1 moved source: registry not updated.");
});

test("external moves: a checksum remembered from this session's rename is used; ambiguous and missing ones are never guessed", () => {
  const remembered = new Map([[(process.platform === "win32" ? `FD-0001-D1|${SRC}|${NEW}`.toLowerCase() : `FD-0001-D1|${SRC}|${NEW}`), SHA2]]);
  const r = R.externalSources({ matches: [{ diagram_id: "FD-0001-D1", from: SRC, to: NEW, problem: "" }],
                                ambiguous: [{ diagram_id: "FD-0001-D2", from: "designs/features/diagrams/b.md", candidates: ["designs/features/x/diagrams/b.md", "designs/features/y/diagrams/b.md"] }],
                                missing: [{ diagram_id: "FD-0001-D3", from: "designs/features/diagrams/c.md", candidates: [] }] }, remembered);
  assert.equal(r.sources[0].sha256, SHA2);
  assert.match(r.skipped[0], /at 2 unregistered paths \(designs\/features\/x\/diagrams\/b\.md, designs\/features\/y\/diagrams\/b\.md\): nothing is guessed/);
  assert.match(r.skipped[1], /no file holds its ID \(E7\): never relinked automatically/);
});

test("the outcome message never claims an index regeneration that did not happen", () => {
  const ok = { renames: [{ diagram_id: "FD-0001-D1", from: SRC, to: NEW }], index: { regenerated: true, problem: "" } };
  assert.match(R.adoptedMessage(ok), /^Registry updated: FD-0001-D1 .* Only the path changed\. designs\/index\/diagram-index\.md was regenerated\./);
  const failed = { ...ok, index: { regenerated: false, problem: "PermissionError: locked" } };
  assert.match(R.adoptedMessage(failed), /was NOT regenerated \(PermissionError: locked\); run python -m tools\.design index/);
  assert.doesNotMatch(R.adoptedMessage(failed), /was regenerated\./);
  assert.match(R.adoptedMessage({ ...ok, renames: [{ diagram_id: "FD-0001-D1", from: NEW, to: SRC }] }, true), /^Moved back 1 diagram source to its registered path: .*The registry was not changed\./);
  assert.equal(R.ARCH_NOTICE, "Architecture diagram sources change only through technical-lead's documentation workflow (M1); the registry was not changed.");
});

test("adopt-moves and move-back arguments: validated paths, a SHA-256 for every source or for none, the token", () => {
  assert.deepEqual(commands.moveArgs({ mode: "adopt", moves: [{ from: SRC, to: NEW, sha256: SHA }], token: TOKEN }),
                   ["registry", "adopt-moves", `--from=${SRC}`, `--to=${NEW}`, `--sha256=${SHA}`, `--confirm=${TOKEN}`, "--json"]);
  assert.deepEqual(commands.moveArgs({ mode: "adopt", moves: [{ from: SRC, to: NEW, sha256: null }], token: TOKEN }),
                   ["registry", "adopt-moves", `--from=${SRC}`, `--to=${NEW}`, `--confirm=${TOKEN}`, "--json"]);
  assert.deepEqual(commands.moveArgs({ mode: "restore", moves: [{ from: NEW, to: "FD-0001-D1", sha256: SHA }], token: TOKEN }),
                   ["registry", "move-back", `--from=${NEW}`, "--to=FD-0001-D1", `--sha256=${SHA}`, `--confirm=${TOKEN}`, "--json"]);
  const bad = [
    { mode: "move", moves: [{ from: SRC, to: NEW }], token: TOKEN },
    { mode: "adopt", moves: [], token: TOKEN },
    { mode: "adopt", moves: [{ from: SRC, to: NEW, sha256: SHA }, { from: SRC, to: NEW }], token: TOKEN },   // a mixture
    { mode: "adopt", moves: [{ from: SRC, to: "docs/architecture/diagrams/x.md" }], token: TOKEN },
    { mode: "adopt", moves: [{ from: SRC, to: "designs/features/../x.md" }], token: TOKEN },
    { mode: "adopt", moves: [{ from: SRC, to: "designs\\features\\x.md" }], token: TOKEN },
    { mode: "adopt", moves: [{ from: "-rf", to: NEW }], token: TOKEN },
    { mode: "adopt", moves: [{ from: SRC, to: NEW, sha256: "A".repeat(64) }], token: TOKEN },
    { mode: "adopt", moves: [{ from: SRC, to: NEW }], token: "nope" },
    { mode: "restore", moves: [{ from: "FD-0001-D1", to: SRC }], token: TOKEN },                            // move-back takes a path now
  ];
  for (const b of bad) assert.throws(() => commands.moveArgs(b), undefined, JSON.stringify(b));
});

test("a move runs once as a command with an argument array and returns its JSON result; a refusal is reported as such", async () => {
  let seen = null;
  const fake = (result, code = 0, stderr = "") => (python, argv, options, cb) => {
    seen = { python, argv, options };
    const err = code ? Object.assign(new Error("exit"), { code }) : null;
    cb(err, JSON.stringify(result), stderr);
  };
  const done = { ok: true, id: "tx-20261127T000000Z-0123abcd", renames: [{ diagram_id: "FD-0001-D1", from: SRC, to: NEW }],
                 index: { regenerated: true, problem: "" }, warnings: [] };
  const r = await commands.moveSources({ python: "py.exe", root: ROOT, execFileImpl: fake(done) }, { mode: "adopt", moves: [{ from: SRC, to: NEW, sha256: SHA }], token: TOKEN });
  assert.deepEqual(r, done);
  assert.equal(seen.options.shell, false);
  assert.deepEqual(seen.argv.slice(0, 5), ["-B", "-E", "-m", "tools.design", "registry"]);
  await assert.rejects(commands.moveSources({ python: "py.exe", root: ROOT, execFileImpl: fake({ ok: true }) }, { mode: "adopt", moves: [{ from: SRC, to: NEW }], token: TOKEN }),
                       /unexpected result/);
  await assert.rejects(commands.moveSources({ python: "py.exe", root: ROOT, execFileImpl: fake({}, 2, "design: error: the adoption was refused; nothing was changed:\n  - x\n") },
                                            { mode: "adopt", moves: [{ from: SRC, to: NEW }], token: TOKEN }), (e) => e.refused && /x/.test(e.message));
});
