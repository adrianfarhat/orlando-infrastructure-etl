"use strict";
// Interpreter selection (Q9, P2-A): machine-level only, suggestion saved only after confirmation.
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");
const { configured, candidate, ensurePython } = require("../../src/python");

test("only the machine-level (user settings) value counts; workspace values are reported as ignored", () => {
  assert.deepEqual(configured({ globalValue: " C:\\py\\python.exe ", workspaceValue: "evil.exe", workspaceFolderValue: "x.exe" }),
                   { path: "C:\\py\\python.exe", ignored: ["workspaceValue", "workspaceFolderValue"] });
  assert.deepEqual(configured({ workspaceValue: "evil.exe" }), { path: "", ignored: ["workspaceValue"] });
  assert.deepEqual(configured(undefined), { path: "", ignored: [] });
});

test("the .venv interpreter is found when it exists", () => {
  const root = path.resolve("/repo");
  const want = process.platform === "win32" ? path.join(root, ".venv", "Scripts", "python.exe") : path.join(root, ".venv", "bin", "python3");
  assert.equal(candidate(root, (p) => p === want), want);
  assert.equal(candidate(root, () => false), "");
});

function fakeVscode({ answer, globalValue, workspaceValue, picked }) {
  const calls = { updates: [], messages: [], warnings: [] };
  return {
    calls,
    ConfigurationTarget: { Global: "Global" },
    workspace: { getConfiguration: () => ({
      inspect: () => ({ globalValue, workspaceValue }),
      update: async (k, v, target) => calls.updates.push([k, v, target]) }) },
    window: {
      showInformationMessage: async (msg, opts, ...buttons) => { calls.messages.push({ msg, opts, buttons }); return answer; },
      showWarningMessage: (msg) => calls.warnings.push(msg),
      showOpenDialog: async () => (picked ? [{ fsPath: picked }] : undefined),
    },
  };
}

test("a suggestion is saved to machine-level settings only after confirmation", async () => {
  const root = path.resolve("/repo");
  const exists = () => true;
  const yes = fakeVscode({ answer: "Use and Save" });
  const got = await ensurePython(yes, root, () => {}, exists);
  assert.match(got, /\.venv/);
  assert.equal(yes.calls.messages[0].opts.modal, true);
  assert.deepEqual(yes.calls.updates, [["pythonPath", got, "Global"]]);
  const no = fakeVscode({ answer: undefined });                    // dismissed: nothing saved, clear error
  await assert.rejects(ensurePython(no, root, () => {}, exists), /no Python interpreter configured/);
  assert.deepEqual(no.calls.updates, []);
});

test("background work never prompts (QA D3): no interpreter configured → quiet failure, nothing saved", async () => {
  const v = fakeVscode({ answer: "Use and Save" });
  await assert.rejects(ensurePython(v, path.resolve("/repo"), () => {}, () => true, false), /no Python interpreter configured yet/);
  assert.equal(v.calls.messages.length, 0);
  assert.deepEqual(v.calls.updates, []);
});

test("a workspace override is ignored and announced; no prompt when the machine value exists", async () => {
  const v = fakeVscode({ globalValue: "C:\\trusted\\python.exe", workspaceValue: "C:\\repo\\evil.exe" });
  ensurePython.warned = false;
  assert.equal(await ensurePython(v, path.resolve("/repo"), () => {}, () => true), "C:\\trusted\\python.exe");
  assert.equal(v.calls.messages.length, 0);
  assert.equal(v.calls.warnings.length, 1);
});

const { interpreterProblem } = require("../../src/python");

test("interpreter paths are validated: a JSON-mangled Windows path is reported, not spawned (hands-on review bug)", () => {
  const good = path.resolve("/venv/Scripts/python.exe");
  const isFile = (p) => p === good;
  // C:\Users\example\Documents\project\.venv\Scripts\python.exe written into settings.json with single
  // backslashes: VS Code's tolerant JSON parser drops each invalid escape (the backslash and the character after it):
  assert.match(interpreterProblem("C:sersxampleocumentsrojectvenvcriptsython.exe", isFile), /not an absolute path/);
  assert.match(interpreterProblem("python.exe", isFile), /not an absolute path/);
  assert.match(interpreterProblem(path.resolve("/missing/python.exe"), isFile), /does not point to an existing file/);
  assert.equal(interpreterProblem(good, isFile), "");
});

test("a configured but unusable interpreter fails with an interpreter error, without prompting or saving", async () => {
  const v = fakeVscode({ globalValue: "C:sersxampleocumentspython.exe", answer: "Use and Save" });
  await assert.rejects(ensurePython(v, path.resolve("/repo"), () => {}, () => true, true, () => false),
                       (err) => err.interpreter === true && /not an absolute path/.test(err.message));
  assert.equal(v.calls.messages.length, 0);
  assert.deepEqual(v.calls.updates, []);
});

test("only a file named like a Python interpreter is accepted; other programs are refused before they run (QA L3)", () => {
  const isFile = () => true;
  for (const name of ["python.exe", "python", "python3", "python3.12", "pythonw.exe", "Python.EXE", "python3.12.exe"])
    assert.equal(interpreterProblem(path.resolve("/venv/Scripts", name), isFile), "", name);
  for (const name of ["notepad.exe", "cmd.exe", "py.exe", "python-evil.exe", "pythonx.exe", "python.exe.bat", "node.exe"])
    assert.match(interpreterProblem(path.resolve("/tools", name), isFile), /is not a Python interpreter/, name);
});

test("an interpreter chosen in the dialog is checked before it is saved (QA L3)", async () => {
  const v = fakeVscode({ answer: "Choose Another…", picked: path.resolve("/Windows/notepad.exe") });
  await assert.rejects(ensurePython(v, path.resolve("/repo"), () => {}, () => false, true, () => true),
                       (err) => err.interpreter === true && /is not a Python interpreter/.test(err.message) && /Nothing was saved/.test(err.message));
  assert.deepEqual(v.calls.updates, []);
  const ok = fakeVscode({ answer: "Choose Another…", picked: path.resolve("/py/python.exe") });
  assert.equal(await ensurePython(ok, path.resolve("/repo"), () => {}, () => false, true, () => true), path.resolve("/py/python.exe"));
  assert.equal(ok.calls.updates.length, 1);
});
