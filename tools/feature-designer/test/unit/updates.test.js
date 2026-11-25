// T-97 PR B2b-1: window presence (D6) and the closed-document command builders.
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const presence = require("../../src/presence");
const commands = require("../../src/commands");

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "fd-presence-"));
const ID = "0123456789abcdef", OTHER = "fedcba9876543210";
const SHA = "a".repeat(64), TOKEN = "0123456789abcdef";

test("a window record lists its open documents, is replaced atomically and removed on close", () => {
  const root = tmp();
  const r = presence.publish(root, ID, [{ path: "designs/features/a.md", dirty: true }], { now: 5000, pid: 42, host: "h" });
  assert.deepStrictEqual(r, { format: presence.FORMAT, version: 1, window: ID, pid: 42, host: "h", heartbeat: 5,
                              documents: [{ path: "designs/features/a.md", dirty: true }] });
  const file = path.join(root, "designs", "diagrams", ".transactions", "windows", `${ID}.json`);
  assert.deepStrictEqual(JSON.parse(fs.readFileSync(file, "utf8")), r);
  presence.publish(root, ID, [], { now: 10000, pid: 42, host: "h" });
  assert.deepStrictEqual(JSON.parse(fs.readFileSync(file, "utf8")).documents, []);
  assert.deepStrictEqual(fs.readdirSync(path.dirname(file)), [`${ID}.json`]);      // no temporary file left
  presence.remove(root, ID);
  assert.ok(!fs.existsSync(file));
});

test("records of ended windows on this computer are swept; live, foreign and own records are kept", () => {
  const root = tmp();
  presence.publish(root, ID, [], { pid: 1, host: "me" });
  presence.publish(root, OTHER, [], { pid: 2, host: "me" });
  presence.publish(root, "1111111111111111", [], { pid: 3, host: "elsewhere" });
  presence.publish(root, "2222222222222222", [], { pid: 4, host: "ME" });
  const removed = presence.sweep(root, ID, { host: "me", isAlive: (pid) => pid === 4 });
  assert.deepStrictEqual(removed, [`${OTHER}.json`]);
  const left = fs.readdirSync(path.join(root, "designs", "diagrams", ".transactions", "windows")).sort();
  assert.deepStrictEqual(left, [`${ID}.json`, "1111111111111111.json", "2222222222222222.json"]);
});

test("the windows folder is never written through a symbolic link or junction", { skip: false }, () => {
  const root = tmp(), outside = tmp();
  fs.mkdirSync(path.join(root, "designs", "diagrams"), { recursive: true });
  fs.symlinkSync(outside, path.join(root, "designs", "diagrams", ".transactions"), "junction");
  assert.throws(() => presence.publish(root, ID, []), /symbolic link or junction/);
  assert.deepStrictEqual(fs.readdirSync(outside), []);
});

test("this process is alive; an impossible process ID is not", () => {
  assert.strictEqual(presence.alive(process.pid), true);
  assert.strictEqual(presence.alive(0), false);
  assert.strictEqual(presence.alive(-5), false);
});

test("open documents: tabs and unsaved documents under designs/features only", () => {
  const root = path.resolve("/repo");
  const uri = (rel) => ({ scheme: "file", fsPath: path.join(root, ...rel.split("/")) });
  const vscode = {
    window: { tabGroups: { all: [{ tabs: [
      { input: { uri: uri("designs/features/a.md") }, isDirty: false },
      { input: { uri: uri("designs/features/b.md") }, isDirty: true },
      { input: { original: uri("designs/features/c.md"), modified: uri("designs/features/a.md") }, isDirty: false },
      { input: { uri: uri("docs/architecture/x.md") }, isDirty: true },
      { input: { uri: { scheme: "untitled", fsPath: "x" } }, isDirty: true },
      { input: undefined } ] }] } },
    workspace: { textDocuments: [{ isDirty: true, uri: uri("designs/features/d.md") }, { isDirty: false, uri: uri("designs/features/e.md") }] },
  };
  const got = presence.openDocuments(vscode, root).sort((x, y) => x.path.localeCompare(y.path));
  assert.deepStrictEqual(got, [{ path: "designs/features/a.md", dirty: false }, { path: "designs/features/b.md", dirty: true },
                               { path: "designs/features/c.md", dirty: false }, { path: "designs/features/d.md", dirty: true }]);
});

test("refresh-blocks arguments: validated feature paths, hashes, token and window", () => {
  assert.deepStrictEqual(commands.refreshBlocksArgs({ files: [{ path: "designs/features/g/a b.md", sha256: SHA }], token: TOKEN, window: ID }),
    ["refresh-blocks", "--file=designs/features/g/a b.md", `--expect=${SHA}`, `--sources-token=${TOKEN}`, `--window=${ID}`, "--json"]);
  const bad = [
    { files: [] }, { files: [{ path: "designs/features/../x.md", sha256: SHA }] }, { files: [{ path: "docs/architecture/x.md", sha256: SHA }] },
    { files: [{ path: "designs/features/a\\b.md", sha256: SHA }] }, { files: [{ path: "designs/features/c:x.md", sha256: SHA }] },
    { files: [{ path: "designs/features/a.md", sha256: "x" }] }, { files: [{ path: "designs/features/a.md", sha256: SHA }], token: "--root=x" },
    { files: [{ path: "designs/features/a.md", sha256: SHA }], token: TOKEN, window: "../../x" },
  ];
  for (const b of bad) assert.throws(() => commands.refreshBlocksArgs({ token: TOKEN, window: ID, ...b }), undefined, JSON.stringify(b));
});

test("transaction arguments: an explicit action, a record ID and the decision token", () => {
  assert.deepStrictEqual(commands.transactionArgs({ action: "undo", id: "tx-20261125T010203Z-0123abcd", token: TOKEN }),
    ["transaction", "undo", "tx-20261125T010203Z-0123abcd", `--confirm=${TOKEN}`, "--json"]);
  for (const b of [{ action: "status" }, { action: "complete", id: "../x" }, { action: "complete", id: "tx-20261125T010203Z-0123abcd", token: "" }])
    assert.throws(() => commands.transactionArgs({ id: "tx-20261125T010203Z-0123abcd", token: TOKEN, ...b }));
});

test("a partly possible recovery (exit code 1 with a JSON answer) is a result, not a failure", async () => {
  const fake = (out, code) => (file, argv, options, cb) => { const e = code ? Object.assign(new Error("x"), { code }) : null; cb(e, out, ""); };
  const r = await commands.resolveTransaction({ python: "py", root: "/r", execFileImpl: fake(JSON.stringify({ ok: false, message: "partly done", files: [] }), 1) },
                                              { action: "complete", id: "tx-20261125T010203Z-0123abcd", token: TOKEN });
  assert.deepStrictEqual([r.ok, r.message], [false, "partly done"]);
  await assert.rejects(commands.refreshBlocks({ python: "py", root: "/r", execFileImpl: (f, a, o, cb) => cb(Object.assign(new Error("x"), { code: 2 }), "", "design: error: changed since it was listed") },
                                              { files: [{ path: "designs/features/a.md", sha256: SHA }], token: TOKEN, window: ID }),
                       /changed since it was listed/);
});
