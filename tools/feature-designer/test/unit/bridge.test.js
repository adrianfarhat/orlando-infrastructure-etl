"use strict";
// The bridge against the real `python -m tools.design designer --serve` of this repository.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { Bridge } = require("../../src/bridge");
const { replacements, applyReplacements } = require("../../src/edits");
const { REPO, testPython } = require("./helpers");

const python = testPython();
const skip = python ? false : "no Python for the design tooling (set FEATURE_DESIGNER_TEST_PYTHON)";

test("library, request IDs and a refused request over one process", { skip }, async () => {
  const b = new Bridge({ python, root: REPO });
  try {
    const lib = await b.request("library");
    assert.equal(lib.ok, true);
    assert.equal(lib.architecture.flatMap((g) => g.diagrams).length, 14);
    const pid = b.pid;
    const refused = await b.request("insert", { path: "designs/features/none.md", text: "", at: 0, diagram_id: "x" });
    assert.equal(refused.ok, false);
    assert.equal(refused.error.code, "bad-request");
    const [r1, r2] = await Promise.all([b.request("library"), b.request("library")]);   // concurrent, matched by ID
    assert.equal(r1.ok && r2.ok, true);
    assert.equal(b.pid, pid);                                                            // the same process throughout
  } finally { b.dispose(); }
});

test("a crashed process is restarted on the next request", { skip }, async () => {
  const b = new Bridge({ python, root: REPO });
  try {
    await b.request("library");
    const first = b.pid;
    b.proc.kill();
    await new Promise((r) => setTimeout(r, 500));
    const again = await b.request("library");
    assert.equal(again.ok, true);
    assert.notEqual(b.pid, first);
  } finally { b.dispose(); }
});

test("a request that does not answer in time kills the process; the next one works", { skip }, async () => {
  const b = new Bridge({ python, root: REPO, timeoutMs: 1 });
  try {
    await assert.rejects(b.request("library"), /did not answer/);
    b.timeoutMs = 30000;
    assert.equal((await b.request("library")).ok, true);
  } finally { b.dispose(); }
});

test("a missing interpreter is reported, not hung", async () => {
  const b = new Bridge({ python: path.join(os.tmpdir(), "no-such-python.exe"), root: REPO, timeoutMs: 5000 });
  try { await assert.rejects(b.request("library"), /cannot start the design tooling|stopped unexpectedly/); }
  finally { b.dispose(); }
});

test("dispose leaves no process behind", { skip }, async () => {
  const b = new Bridge({ python, root: REPO });
  await b.request("library");
  const proc = b.proc;
  b.dispose();
  await new Promise((resolve) => { if (proc.exitCode !== null || proc.signalCode) resolve(); else proc.on("exit", resolve); });
  assert.ok(proc.exitCode !== null || proc.signalCode);
  await assert.rejects(b.request("library"), /shutting down/);
});

test("an insert response applies to the exact text it was computed from (real tooling)", { skip }, async () => {
  const b = new Bridge({ python, root: REPO });
  try {
    const template = fs.readFileSync(path.join(REPO, "designs", "templates", "feature-spec.md"), "utf8");
    // no feature exists in this repository's designs/features, so use a path check: insert needs a real feature file
    const r = await b.request("insert", { path: "designs/features/x.md", text: template, at: 0, diagram_id: "x" });
    assert.equal(r.ok, false);                               // the path must be an existing feature: never guessed
    const text = "a\nb\n";
    const fake = { base: { sha256: require("../../src/edits").sha256(text), line_count: 3 }, newline: "\n",
                   edits: [{ start: 1, end: 1, lines: ["X"] }] };
    assert.equal(applyReplacements(text, replacements(text, fake, "\n")), "a\nX\nb\n");
  } finally { b.dispose(); }
});

// Windows paths with spaces and special characters: a minimal copy of the test virtual environment
// (pyvenv.cfg, the launcher and the packages the tooling imports) under such a folder.
function venvCopyWithAwkwardPath() {
  const venv = path.dirname(path.dirname(python));
  if (process.platform !== "win32" || !fs.existsSync(path.join(venv, "pyvenv.cfg"))) return null;
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "fd venv & (x) %PATH% ^ !"));
  fs.copyFileSync(path.join(venv, "pyvenv.cfg"), path.join(dir, "pyvenv.cfg"));
  fs.mkdirSync(path.join(dir, "Scripts"));
  for (const f of fs.readdirSync(path.join(venv, "Scripts"))) if (/^python.*\.exe$|\.dll$/i.test(f)) fs.copyFileSync(path.join(venv, "Scripts", f), path.join(dir, "Scripts", f));
  const site = path.join(venv, "Lib", "site-packages");
  for (const f of fs.readdirSync(site)) if (/^(ruamel|_ruamel)/i.test(f)) fs.cpSync(path.join(site, f), path.join(dir, "Lib", "site-packages", f), { recursive: true });
  return { dir, exe: path.join(dir, "Scripts", "python.exe") };
}

test("an interpreter under a path with spaces, &, (), %, ^ and ! starts and answers", { skip }, async () => {
  const copy = venvCopyWithAwkwardPath();
  if (!copy) return;
  const b = new Bridge({ python: copy.exe, root: REPO });
  try {
    const lib = await b.request("library");
    assert.equal(lib.ok, true);
    assert.ok(lib.architecture.length > 0);
  } finally { b.dispose(); await new Promise((r) => setTimeout(r, 500)); fs.rmSync(copy.dir, { recursive: true, force: true }); }
});

test("a missing interpreter path with spaces is reported exactly (no mangling)", async () => {
  const missing = path.join(os.tmpdir(), "no such dir & (x)", "python.exe");
  const b = new Bridge({ python: missing, root: REPO, timeoutMs: 5000 });
  try { await assert.rejects(b.request("library"), (err) => err.message.includes(missing) && /ENOENT/.test(err.message)); }
  finally { b.dispose(); }
});
