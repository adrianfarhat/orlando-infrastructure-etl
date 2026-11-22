// GUI test harness: a fixture repository, an isolated VS Code profile, the pinned VS Code test
// build with Feature Designer and the test helper loaded in development mode, and Playwright
// connected over the Chrome DevTools Protocol. Nothing outside test/gui/.run is touched.
"use strict";
const { spawn, execFileSync } = require("child_process");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
const { chromium } = require("playwright-core");
const { EXT, REPO, testPython } = require("../unit/helpers");

const RUN = path.join(__dirname, ".run");
const WS = path.join(RUN, "ws");
const CMD = path.join(RUN, "cmd");
const HELPER = path.join(__dirname, "helper");
const CODE = path.join(EXT, ".vscode-test", "vscode-win32-x64-archive-1.146.0", "Code.exe");
const PY = testPython();
const PORT = 9341;
const MARK_SHARP = path.join(os.homedir(), ".vscode", "extensions", "jonathan-yeung.mark-sharp-1.13.0");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function git(...args) {
  return execFileSync("git", ["-c", "user.name=fd-test", "-c", "user.email=fd-test@example.invalid", "-c", "core.autocrlf=false",
                              "-c", "init.defaultBranch=main", "-C", WS, ...args], { encoding: "utf8" });
}
function design(...args) { return execFileSync(PY, ["-B", "-m", "tools.design", ...args, "--root", WS], { cwd: WS, encoding: "utf8" }); }

/** A fresh fixture repository with the current working copy's tooling and docs, two features and one owned diagram. */
function fixture() {
  if (!PY) throw new Error("no Python for the design tooling: set FEATURE_DESIGNER_TEST_PYTHON");
  fs.rmSync(WS, { recursive: true, force: true });
  const copy = (rel) => fs.cpSync(path.join(REPO, rel), path.join(WS, rel), { recursive: true,
    filter: (src) => !/__pycache__|\.pyc$/.test(src) && !src.includes(`${path.sep}features${path.sep}`) });
  for (const rel of ["tools/design", "docs/architecture", "designs/templates", "designs/index/architecture-index.md",
                     "designs/README.md", "designs/DECISIONS.md", "designs/IMPLEMENTATION_BRIEF.md"]) copy(rel);
  git("init", "-q"); git("add", "-A"); git("commit", "-qm", "fixture baseline");
  design("new", "feature", "--name", "Road pipe intersections");
  design("new", "feature", "--name", "Condition analysis");
  design("new", "diagram", "--feature", "FD-0002", "--title", "Condition Analysis Workflow");
  design("index");
  git("add", "-A"); git("commit", "-qm", "fixture features");
  fs.mkdirSync(path.join(WS, ".venv", "Scripts"), { recursive: true });            // a suggestion target (not a real Python)
  fs.writeFileSync(path.join(WS, ".venv", "Scripts", "python.exe"), "");
  fs.mkdirSync(path.join(WS, ".vscode"), { recursive: true });                    // a workspace override that must be ignored
  fs.writeFileSync(path.join(WS, ".vscode", "settings.json"), JSON.stringify({ "featureDesigner.pythonPath": "C:\\untrusted\\python.exe" }));
  return WS;
}

function profile({ trust, markSharp }) {
  const user = path.join(RUN, "user"), exts = path.join(RUN, "exts");
  fs.rmSync(user, { recursive: true, force: true }); fs.rmSync(exts, { recursive: true, force: true });
  fs.mkdirSync(path.join(user, "User"), { recursive: true }); fs.mkdirSync(exts, { recursive: true });
  fs.writeFileSync(path.join(user, "User", "settings.json"), JSON.stringify({
    "workbench.startupEditor": "none", "workbench.tips.enabled": false, "telemetry.telemetryLevel": "off",
    "update.mode": "none", "extensions.autoUpdate": false, "extensions.autoCheckUpdates": false,
    "security.workspace.trust.enabled": !!trust, "security.workspace.trust.startupPrompt": "never",
    "window.restoreWindows": "none", "files.hotExit": "off", "window.dialogStyle": "custom", "chat.disableAIFeatures": true,
    "workbench.secondarySideBar.defaultVisibility": "hidden", "git.enabled": false,
  }, null, 2));
  let markSharpCopied = false;
  if (markSharp && fs.existsSync(MARK_SHARP)) {                                   // a read-only copy for the test profile
    fs.cpSync(MARK_SHARP, path.join(exts, path.basename(MARK_SHARP)), { recursive: true });
    markSharpCopied = true;
  }
  return { user, exts, markSharpCopied };
}

function getJson(url) {
  return new Promise((res, rej) => http.get(url, (r) => { let b = ""; r.on("data", (d) => (b += d)); r.on("end", () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } }); }).on("error", rej));
}

async function launch({ trust = false, markSharp = true } = {}) {
  const prof = profile({ trust, markSharp });
  fs.rmSync(CMD, { recursive: true, force: true }); fs.mkdirSync(CMD, { recursive: true });
  const args = [WS, `--extensionDevelopmentPath=${EXT}`, `--extensionDevelopmentPath=${HELPER}`,
    `--user-data-dir=${prof.user}`, `--extensions-dir=${prof.exts}`, "--skip-release-notes", "--skip-welcome",
    "--disable-updates", "--new-window", `--remote-debugging-port=${PORT}`, ...(trust ? [] : ["--disable-workspace-trust"])];
  const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !/^(VSCODE_|ELECTRON_|CHROME_)/i.test(k)));
  env.FD_TEST_CMD_DIR = CMD;
  const proc = spawn(CODE, args, { env, stdio: "ignore" });
  let ver;
  for (let i = 0; i < 90 && !ver; i++) { await sleep(500); ver = await getJson(`http://127.0.0.1:${PORT}/json/version`).catch(() => null); }
  if (!ver) throw new Error("VS Code did not open a debugging port");
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`);
  let page;
  for (let i = 0; i < 90 && !page; i++) {
    for (const c of browser.contexts()) for (const p of c.pages()) if (p.url().includes("workbench")) page = p;
    if (!page) await sleep(500);
  }
  if (!page) throw new Error("no workbench window");
  await page.waitForSelector(".monaco-workbench", { timeout: 60000 });
  const app = { proc, browser, page, markSharp: prof.markSharpCopied, seq: 0 };
  app.host = (op, fields = {}, timeout = 30000) => host(app, op, fields, timeout);
  for (let i = 0; i < 60; i++) { try { await app.host("trusted", {}, 2000); break; } catch { await sleep(500); } }
  return app;
}

async function host(app, op, fields, timeout = 30000) {
  const n = ++app.seq;
  fs.writeFileSync(path.join(CMD, `cmd-${n}.json`), JSON.stringify({ op, ...fields }));
  const res = path.join(CMD, `res-${n}.json`);
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    if (fs.existsSync(res)) { const r = JSON.parse(fs.readFileSync(res, "utf8")); if (!r.ok) throw new Error(`${op}: ${r.error}`); return r.value; }
    await sleep(100);
  }
  throw new Error(`helper did not answer ${op}`);
}

/** The Feature Designer webview's inner frame (it defines FD_DEBUG). */
async function designerFrame(page, timeout = 30000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    for (const f of page.frames()) if (await f.evaluate(() => !!window.FD_DEBUG && !!document.querySelector("#doc")).catch(() => false)) return f;
    await sleep(300);
  }
  return null;
}

/** Mark Sharp's webview frame (a Lexical editor with a contenteditable root). */
async function markSharpFrame(page, timeout = 30000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    for (const f of page.frames())
      if (await f.evaluate(() => !window.FD_DEBUG && !!document.querySelector('[contenteditable="true"]') && !!document.querySelector("[data-lexical-editor]")).catch(() => false)) return f;
    await sleep(300);
  }
  return null;
}

async function close(app) {
  if (!app) return;
  try { await app.browser.close(); } catch { /* */ }
  try { execFileSync("taskkill", ["/F", "/T", "/PID", String(app.proc.pid)], { stdio: "ignore" }); } catch { /* gone */ }
  for (let i = 0; i < 40; i++) {
    const out = execFileSync("powershell", ["-NoProfile", "-Command",
      "(Get-CimInstance Win32_Process -Filter \"name='Code.exe'\" | Where-Object { $_.CommandLine -like '*feature-designer*gui*.run*user*' }).Count"], { encoding: "utf8" }).trim();
    if (out === "0" || out === "") break;
    await sleep(500);
  }
}

module.exports = { RUN, WS, PY, fixture, launch, close, designerFrame, markSharpFrame, design, git, sleep };
