"use strict";
// One-shot write commands (T-97 PR B, decision B1): validated arguments, no shell, a timeout, JSON results.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");
const { newDiagram, newDiagramArgs, run } = require("../../src/commands");
const { REPO, testPython } = require("./helpers");

const ok = { owner: "FD-0001", title: "Pipe flow", category: "process" };

test("new diagram arguments: validated, and every value is attached to its option", () => {
  assert.deepEqual(newDiagramArgs(ok), ["new", "diagram", "--feature=FD-0001", "--title=Pipe flow", "--category=process", "--json"]);
  assert.deepEqual(newDiagramArgs({ ...ok, title: "--root C:\\elsewhere" })[3], "--title=--root C:\\elsewhere");   // never an option
  for (const [fields, why] of [[{ ...ok, owner: "FD-1" }, /feature ID/], [{ ...ok, owner: "FD-0001 --root x" }, /feature ID/],
                               [{ ...ok, owner: undefined }, /feature ID/], [{ ...ok, title: "  " }, /needs a name/],
                               [{ ...ok, title: "a\nb" }, /control character/], [{ ...ok, title: "a\u0085b" }, /control character/],
                               [{ ...ok, title: "x".repeat(201) }, /longer than/], [{ ...ok, category: "drawing" }, /category/],
                               [{ ...ok, title: 7 }, /needs a name/]])
    assert.throws(() => newDiagramArgs(fields), why);
});

function fake(result) {
  const calls = [];
  return { calls, impl: (file, args, options, cb) => { calls.push({ file, args, options }); setImmediate(() => cb(...result)); } };
}

test("runs the interpreter directly with an argument array, no shell, a timeout and the repository as working folder", async () => {
  const f = fake([null, '{"path":"designs/features/diagrams/a_process_pipe-flow.md","diagram_id":"FD-0001-D1","owner":"FD-0001","category":"process"}', ""]);
  const made = await newDiagram({ python: "C:\\py\\python.exe", root: "C:\\repo", execFileImpl: f.impl }, ok);
  assert.equal(made.diagram_id, "FD-0001-D1");
  const { file, args, options } = f.calls[0];
  assert.equal(file, "C:\\py\\python.exe");
  assert.deepEqual(args, ["-B", "-E", "-m", "tools.design", "new", "diagram", "--feature=FD-0001", "--title=Pipe flow",
                          "--category=process", "--json", "--root", "C:\\repo"]);
  assert.equal(options.shell, false);
  assert.equal(options.cwd, "C:\\repo");
  assert.ok(options.timeout > 0 && options.timeout <= 120000);
});

test("a refusal reports the tooling's own message; a timeout says nothing is known to have been created", async () => {
  const refused = fake([Object.assign(new Error("exit 1"), { code: 1 }), "", "design: error: no feature has the ID FD-0009\n"]);
  await assert.rejects(newDiagram({ python: "p", root: "r", execFileImpl: refused.impl }, ok),
                       (e) => e.message === "no feature has the ID FD-0009" && e.refused === true);
  const slow = fake([Object.assign(new Error("timeout"), { killed: true, signal: "SIGTERM" }), "", ""]);
  await assert.rejects(run({ python: "p", root: "r", args: [], timeoutMs: 5000, execFileImpl: slow.impl }),
                       /did not finish within 5 s; nothing is known to have been created/);
});

test("an unexpected or non-JSON answer is rejected", async () => {
  for (const out of ["created it", '{"path":"../outside.md","diagram_id":"FD-0001-D1","owner":"FD-0001"}',
                     '{"path":"designs/features/diagrams/x.md","diagram_id":"AD-0001","owner":"FD-0001"}',
                     '{"path":"designs/features/diagrams/x.md","diagram_id":"FD-0002-D1","owner":"FD-0002"}']) {
    const f = fake([null, out, ""]);
    await assert.rejects(newDiagram({ python: "p", root: "r", execFileImpl: f.impl }, ok), /JSON|unexpected/);
  }
  await assert.rejects(run({ python: "", root: "r", args: [] }), /no Python/);
});

test("with the real design tooling: creates and registers one diagram in a fixture repository", { skip: !testPython() && "no Python" }, async () => {
  const py = testPython();
  const ws = fs.mkdtempSync(path.join(os.tmpdir(), "fd-cmd-"));
  try {
    for (const rel of ["tools/design", "docs/architecture", "designs/templates", "designs/diagrams/registry.yml",
                       "designs/index/architecture-index.md", "designs/index/diagram-index.md"])
      fs.cpSync(path.join(REPO, rel), path.join(ws, rel), { recursive: true, filter: (s) => !/__pycache__/.test(s) });
    const git = (...a) => execFileSync("git", ["-c", "user.name=t", "-c", "user.email=t@example.invalid", ...a], { cwd: ws });
    git("init", "-q"); git("add", "-A"); git("commit", "-qm", "base");
    execFileSync(py, ["-B", "-m", "tools.design", "new", "feature", "--name", "Road pipes", "--root", ws], { cwd: ws });
    const made = await newDiagram({ python: py, root: ws }, { owner: "FD-0001", title: "Pipe flow", category: "process" });
    assert.deepEqual(made, { path: "designs/features/diagrams/road-pipes_process_pipe-flow.md", diagram_id: "FD-0001-D1",
                             owner: "FD-0001", category: "process" });
    assert.ok(fs.readFileSync(path.join(ws, "designs/diagrams/registry.yml"), "utf8").includes("FD-0001-D1"));
    await assert.rejects(newDiagram({ python: py, root: ws }, { owner: "FD-0001", title: "Pipe flow", category: "process" }),
                         /already exists; nothing was overwritten/);
  } finally { fs.rmSync(ws, { recursive: true, force: true }); }
});
