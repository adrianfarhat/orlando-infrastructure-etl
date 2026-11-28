// Feature Designer (T-97 Phase 2, PR B1, B2a, B2b-1, B2b-2b) end-to-end test in the pinned VS Code 1.146 test build, with
// real pointer and keyboard input (Playwright over CDP). Writes evidence to test/gui/.run/.
"use strict";
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { execFileSync } = require("child_process");
const { RUN, WS, PY, fixture, launch, close, designerFrame, markSharpFrame, design, sleep } = require("./vscode");

const FEATURE = "designs/features/road-pipe-intersections.md";
const OWNED = "FD-0002-D1";
const CRED = "AD-0011";                                   // stable ID (diagram registry, M0) of the credential boundary
const CRED_ALIAS = "system-architecture/credential-boundary";   // its former catalog ID, still valid as an alias
// a start marker for an ID, with or without its fingerprint (diagram library U13)
const markerAt = (lines, id) => lines.findIndex((l) => l === `<!-- diagram:start ${id} -->` || l.startsWith(`<!-- diagram:start ${id} sha256:`));
const EV = path.join(RUN, "evidence");
const results = [];
let app, f, shot = 0;

function rec(name, ok, detail) {
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail === undefined ? "" : ` — ${typeof detail === "string" ? detail : JSON.stringify(detail)}`}`);
}
async function snap(name) { await app.page.screenshot({ path: path.join(EV, `${String(++shot).padStart(2, "0")}-${name}.png`) }).catch(() => {}); }
async function step(name, fn) {
  try { await fn(); } catch (e) {
    rec(name, false, String(e.message || e).split("\n")[0]);
    if (app && app.events && app.events.length) console.log(`  window events: ${app.events.join("; ")}`);   // a lost window (run 14)
    await snap(`FAILED-${name.replace(/[^a-z0-9]+/gi, "-")}`); await app.page.keyboard.press("Escape").catch(() => {});
  }
}
const text = () => f.evaluate(() => window.FD_DEBUG.state.text);
const version = () => f.evaluate(() => window.FD_DEBUG.state.version);
async function waitFor(fn, ms = 15000, every = 150) { const t0 = Date.now(); while (Date.now() - t0 < ms) { const v = await fn(); if (v) return v; await sleep(every); } return null; }
async function waitVersion(v) { if (!(await waitFor(async () => (await version()) > v))) throw new Error("the document did not change"); await sleep(200); }
const doc = (p = FEATURE) => app.host("doc", { path: p });
const center = (b) => ({ x: b.x + b.width / 2, y: b.y + b.height / 2 });
async function box(sel) { const l = f.locator(sel).first(); await l.scrollIntoViewIfNeeded(); await sleep(100); return l.boundingBox(); }
async function blockAfter(heading) {
  return f.evaluate((hd) => {
    const bs = [...document.querySelectorAll("#doc > .block")];
    const i = bs.findIndex((b) => { const x = b.querySelector("h2,h3"); return x && x.textContent.trim().startsWith(hd); });
    return i < 0 ? null : { idx: i + 1, end: +bs[i + 1].dataset.end };
  }, heading);
}
const blockSel = (i) => `#doc > .block >> nth=${i}`;
async function dialogButton(label) {                       // VS Code's custom (HTML) modal dialog
  const btn = app.page.locator(".monaco-dialog-box .dialog-buttons a.monaco-button, .monaco-dialog-box .dialog-buttons .monaco-button").filter({ hasText: label }).first();
  await btn.waitFor({ timeout: 15000 }); await btn.click();
}
/** "+" below a block, then Place Diagram ▸ <which> (PR B). */
async function placeMenu(idx, which) {
  await app.page.mouse.move(...Object.values(center(await box(blockSel(idx)))), { steps: 3 });
  await f.locator(`${blockSel(idx)} >> .plus`).click();
  await f.locator('.menu [role="menuitem"].has-sub').click();
  await f.locator('.menu.sub [role="menuitem"]', { hasText: which }).click();
}
async function insertVia(heading, query) {
  const b = await blockAfter(heading);
  await placeMenu(b.idx, "Add Existing Diagram");
  await f.waitForSelector(".tree li.item", { state: "attached", timeout: 20000 });
  await f.locator('.dlg input[type="search"]').fill(query); await sleep(200);
  const v = await version();
  await app.page.keyboard.press("Enter");
  return { block: b, v };
}
function py(args) { try { return execFileSync(PY, ["-B", ...args], { cwd: WS, encoding: "utf8" }); } catch (e) { return `${e.stdout || ""}${e.stderr || ""}`; } }

(async () => {
  fs.rmSync(EV, { recursive: true, force: true }); fs.mkdirSync(EV, { recursive: true });
  fixture();
  app = await launch({ trust: false, markSharp: true });
  if (process.env.FD_GUI_ONLY === "b2b1") {               // a shorter run of the PR B2b-1 steps alone (diagnosis)
    await app.host("setGlobal", { section: "featureDesigner", key: "pythonPath", value: PY });
    py(["-m", "tools.design", "new", "diagram", "--feature", "FD-0001", "--title", "Pipe flow", "--category", "process"]);
    await prB2b1Steps();
    await saveLog();
    await close(app);
    const failed = results.filter((r) => !r.ok);
    console.log(`\n${results.length - failed.length} of ${results.length} checks passed`);
    process.exit(failed.length ? 1 : 0);
  }
  if (process.env.FD_GUI_ONLY === "b2b2b") {              // a shorter run of the PR B2b-2b steps alone (diagnosis)
    await app.host("setGlobal", { section: "featureDesigner", key: "pythonPath", value: PY });
    await prB2b2bSteps();
    await saveLog();
    await close(app);
    fs.writeFileSync(path.join(EV, "e2e-results.json"), JSON.stringify(results, null, 2));
    const failed = results.filter((r) => !r.ok);
    console.log(`\n${results.length - failed.length} of ${results.length} checks passed`);
    process.exit(failed.length ? 1 : 0);
  }

  // P2-A: no interpreter configured → the .venv interpreter is suggested; saved only after confirmation
  await step("P2-A interpreter suggestion and confirmation", async () => {
    await app.host("openWith", { path: FEATURE, viewType: "featureDesigner.editor" });
    f = await designerFrame(app.page);                    // rendering needs no Python; the library does
    // the frame exists before the document is rendered: wait for the section (a slow first render under load
    // failed here, and as this step also saves the test interpreter, every later step failed with it)
    const b0 = await waitFor(() => blockAfter("3. Logic"), 30000);
    await placeMenu(b0.idx, "Add Existing Diagram");
    const dlg = app.page.locator(".monaco-dialog-box");
    await dlg.waitFor({ timeout: 30000 });
    const message = await dlg.innerText();
    await snap("interpreter-prompt");
    const before = await app.host("getGlobal", { section: "featureDesigner", key: "pythonPath" });
    await dialogButton("Use and Save");
    const after = await waitFor(async () => (await app.host("getGlobal", { section: "featureDesigner", key: "pythonPath" })).globalValue);
    rec("P2-A suggested .venv interpreter, saved to user/machine settings only after confirming",
        message.includes(path.join(".venv", "Scripts", "python.exe")) && !before.globalValue && after && after.endsWith(path.join(".venv", "Scripts", "python.exe")),
        { suggested: message.split("\n").find((l) => l.includes(".venv")), saved: after });
    rec("Q9 workspace override is not used", after !== "C:\\untrusted\\python.exe");
    await app.host("setGlobal", { section: "featureDesigner", key: "pythonPath", value: PY });   // the real interpreter for the rest
    await app.page.keyboard.press("Escape");
    await app.host("closeAll");
  });

  await step("1 open formatted", async () => {
    await app.host("openWith", { path: FEATURE, viewType: "featureDesigner.editor" });
    f = await designerFrame(app.page);
    if (!f) throw new Error("Feature Designer did not open");
    await waitFor(() => f.evaluate(() => document.querySelectorAll(".mermaid-out svg").length > 0));
    const info = await f.evaluate(() => {
      const bs = [...document.querySelectorAll("#doc > .block")];
      const i = bs.findIndex((b) => { const x = b.querySelector("h2"); return x && x.textContent.trim() === "1. Objective"; });
      return { h1: document.querySelector("h1").textContent, svgs: document.querySelectorAll(".mermaid-out svg").length,
               plusAbove: bs.slice(0, i).filter((b) => b.querySelector(".plus")).length, genEditable: document.querySelectorAll(".gen [contenteditable]").length };
    });
    rec("1 formatted document: diagrams drawn, no + above section 1, generated blocks read-only",
        info.h1.includes("Road pipe intersections") && info.svgs >= 1 && info.plusAbove === 0 && info.genEditable === 0, info);
    rec("1b the buffer shown equals VS Code's document", (await text()) === (await doc()).text);
    await snap("formatted");
  });

  await step("2 hover and menu", async () => {
    const b = await blockAfter("3. Logic");
    const plus = `${blockSel(b.idx)} >> .plus`;
    await app.page.mouse.move(1000, 14);
    const before = await f.locator(plus).evaluate((el) => getComputedStyle(el).opacity);
    const c = center(await box(blockSel(b.idx)));
    await app.page.mouse.move(c.x, c.y, { steps: 6 });
    const after = await waitFor(async () => { await app.page.mouse.move(c.x + 2, c.y, { steps: 1 });   // hover is re-evaluated on movement
                                               const o = await f.locator(plus).evaluate((el) => getComputedStyle(el).opacity); return o === "1" ? o : null; }, 3000, 200) || "0";
    await app.page.mouse.move(...Object.values(center(await box(plus))), { steps: 4 }); await sleep(200);
    const onIt = await waitFor(async () => { const o = await f.locator(plus).evaluate((el) => getComputedStyle(el).opacity); return o === "1" ? o : null; }, 3000, 200) || "0";
    await f.locator(plus).click();
    const items = await f.locator('.menu:not(.sub) [role="menuitem"]').allTextContents();
    await f.locator('.menu [role="menuitem"].has-sub').hover();
    const sub = await waitFor(() => f.locator('.menu.sub [role="menuitem"]').allTextContents().then((x) => x.length ? x : null), 3000);
    await snap("menu");
    rec("2 / B1 hover reveals + (stays while moving onto it); the menu shows Place Diagram ▸ Add Existing Diagram… / Make New Diagram…",
        before === "0" && after === "1" && onIt === "1" && JSON.stringify(items) === '["Place Diagram▸"]' &&
        JSON.stringify(sub) === '["Add Existing Diagram…","Make New Diagram…"]', { before, after, onIt, items, sub });
    await app.page.keyboard.press("Escape");
    await f.locator(plus).click();                                    // keyboard: Right opens the submenu, Left closes it
    await app.page.keyboard.press("ArrowRight");
    const focused = await f.evaluate(() => document.activeElement && document.activeElement.textContent);
    await app.page.keyboard.press("ArrowLeft");
    const closed = await f.evaluate(() => !document.querySelector(".menu.sub") && document.activeElement.classList.contains("has-sub"));
    rec("B1b keyboard: ArrowRight opens the submenu on its first item; ArrowLeft returns to Place Diagram", focused === "Add Existing Diagram…" && closed, { focused, closed });
    await app.page.keyboard.press("Escape");
    // a menu closed in the same tick it opened must not leave its outside-click listener behind
    await f.evaluate((i) => { document.querySelector(`#doc > .block:nth-child(${i + 1}) > .plus`).click();
                              document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); }, b.idx);
    await sleep(300);
    await f.locator(plus).click();
    await f.locator('.menu [role="menuitem"].has-sub').click();
    const still = await waitFor(() => f.evaluate(() => !!document.querySelector(".menu.sub") && !!document.querySelector(".menu:not(.sub)")), 3000);
    rec("B1c a menu closed as soon as it opened leaves nothing behind: the next menu stays open when clicked", !!still);
    await app.page.keyboard.press("Escape"); await app.page.keyboard.press("Escape");
  });

  await step("3 library", async () => {
    const b = await blockAfter("3. Logic");
    await placeMenu(b.idx, "Add Existing Diagram");
    await f.waitForSelector(".tree li.item", { state: "attached", timeout: 20000 });
    const lib = await f.evaluate(() => ({
      cats: [...document.querySelectorAll(".tree > li.cat > .row .label")].map((x) => x.textContent),
      arch: document.querySelectorAll(".tree > li.cat:nth-child(1) li.item").length,
      feats: [...document.querySelectorAll(".tree > li.cat:nth-child(2) li.grp > .row .label")].map((x) => x.textContent),
      owned: [...document.querySelectorAll(".tree > li.cat:nth-child(2) li.item")].map((x) => x.dataset.id) }));
    const search = f.locator('.dlg input[type="search"]');
    const visible = async (q) => { await search.fill(q); await sleep(150); return f.evaluate(() => [...document.querySelectorAll(".tree li.item")].filter((li) => li.offsetParent).map((li) => li.dataset.id)); };
    const byName = await visible("credential"), byOwner = await visible("FD-0002"), byDoc = await visible("etl-workflow.md");
    const byAlias = await visible(CRED_ALIAS), byCategory = await visible("other condition");
    const title = await f.locator(".dlg header").innerText();
    await snap("library");
    rec("B2 Add Existing Diagram: titled so; a former catalog ID (alias) and a category also find a diagram",
        title === "Add Existing Diagram" && JSON.stringify(byAlias) === `["${CRED}"]` && JSON.stringify(byCategory) === `["${OWNED}"]`,
        { title, byAlias, byCategory });
    rec("3 library: two categories, 14 architecture diagrams, feature groups; search by name, owner and source document",
        JSON.stringify(lib.cats) === '["Main Branch — Architecture","Feature Documents"]' && lib.arch === 14 &&
        lib.feats.length === 2 && JSON.stringify(lib.owned) === `["${OWNED}"]` && JSON.stringify(byName) === `["${CRED}"]` &&
        JSON.stringify(byOwner) === `["${OWNED}"]` && byDoc.length === 5, { ...lib, byName, byOwner, byDoc: byDoc.length });
    await app.page.keyboard.press("Escape");
  });

  await step("3b unusable interpreter: error with Retry / Change Interpreter, then Retry loads", async () => {
    // C:\Users\example\Documents\python.exe as VS Code reads it from a settings.json with single backslashes
    await app.host("setGlobal", { section: "featureDesigner", key: "pythonPath", value: "C:sersxampleocumentspython.exe" });
    await sleep(500);
    const b = await blockAfter("3. Logic");
    await placeMenu(b.idx, "Add Existing Diagram");
    const error = await waitFor(() => f.evaluate(() => { const e = document.querySelector(".tree .lib-error"); return e ? e.innerText : ""; }), 15000);
    const buttons = await f.evaluate(() => [...document.querySelectorAll(".tree .lib-actions button")].map((x) => x.textContent));
    const stuck = await f.evaluate(() => /Loading the diagram library/.test(document.querySelector(".tree").innerText));
    await snap("library-error");
    await app.host("setGlobal", { section: "featureDesigner", key: "pythonPath", value: PY });
    await sleep(500);
    await f.locator(".tree .lib-actions .retry").click();
    const loaded = await waitFor(() => f.evaluate(() => document.querySelectorAll(".tree li.item").length), 20000);
    rec("3b an unusable interpreter shows the error with Retry and Change Interpreter (not stuck on Loading); Retry then loads",
        /not an absolute path/.test(error || "") && !stuck && JSON.stringify(buttons) === '["Retry","Change Interpreter…"]' && loaded >= 14,
        { error: (error || "").slice(0, 120), buttons, stuck, loaded });
    await f.locator(".dlg button", { hasText: "Cancel" }).click();
  });

  await step("3c a program that is not Python: refused before it runs, with Change Interpreter (QA L3)", async () => {
    const notPython = path.join(process.env.SystemRoot || "C:\\Windows", "System32", "notepad.exe");
    const running = () => { try { return /notepad\.exe/i.test(execFileSync("tasklist", ["/FI", "IMAGENAME eq notepad.exe"], { encoding: "utf8" })); } catch { return false; } };
    const before = running();
    await app.host("setGlobal", { section: "featureDesigner", key: "pythonPath", value: notPython });
    await sleep(500);
    const b = await blockAfter("3. Logic");
    await app.page.mouse.move(...Object.values(center(await box(blockSel(b.idx)))), { steps: 3 });
    await f.locator(`${blockSel(b.idx)} >> .plus`).click();
    await f.locator('.menu [role="menuitem"].has-sub').click();
    const t0 = Date.now();
    await f.locator('.menu.sub [role="menuitem"]', { hasText: "Add Existing Diagram" }).click();
    const error = await waitFor(() => f.evaluate(() => { const e = document.querySelector(".tree .lib-error"); return e ? e.innerText : ""; }), 15000);
    const seconds = (Date.now() - t0) / 1000;
    const buttons = await f.evaluate(() => [...document.querySelectorAll(".tree .lib-actions button")].map((x) => x.textContent));
    const started = !before && running();
    await snap("library-not-python");
    await app.host("setGlobal", { section: "featureDesigner", key: "pythonPath", value: PY });
    await sleep(500);
    await f.locator(".tree .lib-actions .retry").click();
    const loaded = await waitFor(() => f.evaluate(() => document.querySelectorAll(".tree li.item").length), 20000);
    rec("3c notepad.exe as the interpreter: a clear 'not a Python interpreter' error within seconds, Retry and Change Interpreter offered, nothing started",
        /is not a Python interpreter/.test(error || "") && seconds < 10 && !started &&
        JSON.stringify(buttons) === '["Retry","Change Interpreter…"]' && loaded >= 14,
        { error: (error || "").slice(0, 120), seconds, buttons, started, loaded });
    await f.locator(".dlg button", { hasText: "Cancel" }).click();
  });

  let insertedText, markSharpSaved = null;
  await step("4 insert two diagrams at the + positions", async () => {
    const before = (await doc()).text;
    const a = await insertVia("3. Logic", "condition analysis workflow");          // owned by another feature
    await waitVersion(a.v);
    const b = await insertVia("2. Data contract", "credential");
    await waitVersion(b.v);
    const after = (await doc()).text, L = after.split(/\r?\n/);
    const iOwned = markerAt(L, OWNED), iCred = markerAt(L, CRED);
    const untouched = before.split(/\r?\n/).every((l) => L.includes(l));                 // every original line still there
    insertedText = after;
    await waitFor(() => f.evaluate((id) => !!document.querySelector(`.gen[data-diagram="${id}"] .mermaid-out svg`), OWNED));
    await snap("inserted");
    rec("4 an architecture and another feature's diagram land below the hovered blocks; unrelated content kept",
        iOwned > 0 && iCred > 0 && iCred < iOwned && untouched && L[iOwned + 1].startsWith("**🔷 Proposed:") && L[iCred + 1].startsWith("**✅ Current architecture:"),
        { iCred, iOwned, untouched });
    rec("4b the document is dirty, not saved behind VS Code's back", (await doc()).isDirty === true && !fs.readFileSync(path.join(WS, FEATURE), "utf8").includes(OWNED));
    const drawn = await waitFor(() => f.evaluate(([a, b]) => ["current"].includes((document.querySelector(`.gen[data-diagram="${a}"]`) || {}).dataset?.state) &&
                                                             (document.querySelector(`.gen[data-diagram="${b}"]`) || {}).dataset?.state === "current", [OWNED, CRED]), 15000);
    const sources = fs.readdirSync(path.join(WS, "designs/features/diagrams"));
    rec("B2b the references use the stable IDs with fingerprints, render from their sources (state current), and no source file was copied",
        /^<!-- diagram:start AD-0011 sha256:[0-9a-f]{16} -->$/.test(L[iCred]) && !!drawn && sources.length === 1, { marker: L[iCred], drawn: !!drawn, sources });
  });

  await step("5 stale insert refused", async () => {
    const v = await version(), t = await text();
    await f.evaluate(([ver, id]) => window.FD_HOST.api.postMessage({ type: "insertDiagram", at: 30, id, version: ver - 1 }), [v, CRED_ALIAS]);
    const msg = await waitFor(() => f.evaluate(() => { const s = document.querySelector("#status"); return s && s.style.display !== "none" ? s.textContent : ""; }));
    rec("5 an insert computed for an older version is refused; nothing changes", /changed/.test(msg || "") && (await text()) === t, msg);
  });

  await step("6 undo and redo", async () => {
    const t = await text();
    await f.locator("h1").click();
    await app.page.keyboard.press("Control+Z"); await sleep(1000);
    const undone = await text();
    await app.page.keyboard.press("Control+Y"); await sleep(1000);
    rec("6 one Ctrl+Z removes exactly the last insertion; Ctrl+Y restores it",
        !undone.includes(`diagram:start ${CRED}`) && undone.includes(`diagram:start ${OWNED}`) && (await text()) === t);
  });

  await step("7 save updates the feature index through the editor", async () => {
    const indexPath = path.join(WS, "designs", "index", "feature-index.md");
    const beforeIndex = fs.readFileSync(indexPath, "utf8");
    await app.host("save", { path: FEATURE });
    const changed = await waitFor(() => fs.readFileSync(indexPath, "utf8") !== beforeIndex, 15000);
    const idx = fs.readFileSync(indexPath, "utf8");
    const check = py(["-m", "tools.design", "check"]), idxCheck = py(["-m", "tools.design", "index", "--check"]);
    rec("7 saving updates designs/index/feature-index.md (Diagrams column); check and index --check clean with no manual index",
        changed && idx.includes(`\`${CRED}\``) && /0 problem\(s\)/.test(check) && !/out of date/.test(idxCheck),
        { check: check.trim().split("\n").pop(), index: idxCheck.trim().split("\n").join(" | ") });
    const otherFeature = fs.readFileSync(path.join(WS, "designs/features/condition-analysis.md"), "utf8");
    rec("7b no other feature file was rewritten", !otherFeature.includes("diagram:start"));
  });

  await step("8 edit source", async () => {
    await app.host("command", { id: "notifications.clearAll" });
    await f.locator(`.edit-diagram[data-id="${CRED}"]`).scrollIntoViewIfNeeded();
    await f.locator(`.edit-diagram[data-id="${CRED}"]`).click();
    const tab = await waitFor(async () => (await app.host("tabs")).find((t) => t.label === "system-architecture.md" && t.kind === "text"));
    const line = await waitFor(() => app.page.locator(".line-numbers.active-line-number").allTextContents().then((x) => { const n = x.map((s) => s.trim()).filter(Boolean); return n.length ? n : null; }), 10000) || [];
    const src = fs.readFileSync(path.join(WS, "docs/architecture/system-architecture.md"), "utf8").split(/\r?\n/);
    const toast = await waitFor(() => app.page.locator(".notifications-toasts").innerText().catch(() => ""), 8000);
    rec("8 / B6 the pencil on an architecture diagram opens the authoritative Mermaid line, with the technical-lead workflow notice",
        !!tab && line && line.some((n) => src[+n - 1] && src[+n - 1].startsWith("```mermaid")) && /technical-lead's documentation workflow/.test(toast || ""),
        { line, toast: (toast || "").slice(0, 140) });
    await snap("edit-source");
  });

  await step("9 Python crash recovery", async () => {
    await app.host("command", { id: "notifications.clearAll" });
    const pid = (await app.host("designer", { fn: "bridgePid" })).value;
    const killed = (await app.host("designer", { fn: "killBridgeProcess" })).value;
    await sleep(800);
    const t = await text();
    const a = await insertVia("5. Downstream impact", "credential");
    await waitVersion(a.v);
    const newPid = (await app.host("designer", { fn: "bridgePid" })).value;
    rec("9 after the Python process is killed, the next insert restarts it; no edits lost",
        killed && pid && newPid && newPid !== pid && (await text()).startsWith(t.slice(0, 200)) &&
        (await text()).split(`diagram:start ${CRED}`).length === t.split(`diagram:start ${CRED}`).length + 1,
        { pid, newPid });
    await f.locator("h1").click(); await app.page.keyboard.press("Control+Z"); await sleep(2500);
    const toasts = await app.page.locator(".notifications-toasts").innerText().catch(() => "");
    rec("9b undoing an insertion does not raise the 'removed by another change' warning", !/removed by another change/.test(toasts), toasts.slice(0, 120));
  });

  await step("10 text editor ↔ Feature Designer with unsaved changes", async () => {
    await app.host("save", { path: FEATURE }); await sleep(800);
    await app.host("closeAll"); await dialogDismissIfAny();
    await app.host("openText", { path: FEATURE, column: 1 });
    await sleep(800);
    await app.page.locator(".monaco-editor .view-lines").first().click();
    await app.page.keyboard.press("Control+End");
    await app.page.keyboard.type("Typed in the text editor.");
    await sleep(500);
    const typed = await doc();
    await app.host("openWith", { path: FEATURE, viewType: "featureDesigner.editor", column: 2 });
    f = await designerFrame(app.page);
    const seen = await waitFor(async () => (await text()).includes("Typed in the text editor."));
    const a = await insertVia("1. Objective", "credential");
    await waitVersion(a.v);
    const both = (await doc()).text;
    await app.host("openWith", { path: FEATURE, viewType: "default", column: 2 });   // switch that group to the text editor
    await sleep(800);
    const dialogs = await app.page.locator(".monaco-dialog-box").count();
    const stillDirty = (await doc()).isDirty;
    await app.host("openWith", { path: FEATURE, viewType: "featureDesigner.editor", column: 2 });   // and back
    f = await designerFrame(app.page);
    const reopened = await text();
    rec("10 unsaved typing in the text editor is shown, kept and combined with the insertion; switching editors loses nothing",
        typed.isDirty && !!seen && both.includes("Typed in the text editor.") && both.includes(`diagram:start ${CRED}`) &&
        reopened === both && stillDirty && dialogs === 0, { typedDirty: typed.isDirty, seen: !!seen, stillDirty, dialogs });
  });

  await step("11 Mark Sharp interoperability", async () => {
    if (!app.markSharp) { rec("11 Mark Sharp interoperability", false, "Mark Sharp 1.13.0 not found in the user's extensions; not tested"); return; }
    await app.host("save", { path: FEATURE }); await sleep(800);
    await app.host("closeAll"); await dialogDismissIfAny();
    await app.host("openWith", { path: FEATURE, viewType: "featureDesigner.editor", column: 1 });
    await app.host("openWith", { path: FEATURE, viewType: "msharp.customEditor", column: 2 });
    const ms = await markSharpFrame(app.page);
    f = await designerFrame(app.page);
    if (!ms || !f) throw new Error(`Mark Sharp ${!!ms}, Designer ${!!f}`);
    const banner = await waitFor(() => f.evaluate(() => { const b = document.querySelector("#banner"); return b && !b.hidden ? b.textContent : ""; }));
    // type into a paragraph in Mark Sharp
    const para = ms.locator("[data-lexical-editor] p").filter({ hasText: "Describe the real problem" }).first();
    await para.click(); await app.page.keyboard.press("End");
    await app.page.keyboard.type(" MarkSharpTyped");
    const synced = await waitFor(async () => (await doc()).text.includes("MarkSharpTyped"), 10000);
    await snap("mark-sharp-side-by-side");
    // insert from the Designer: the modal warning names Mark Sharp
    const b = await blockAfter("4. Dependencies");
    await placeMenu(b.idx, "Add Existing Diagram");
    await f.waitForSelector(".tree li.item", { state: "attached" });
    await f.locator('.dlg input[type="search"]').fill(OWNED); await sleep(150);
    const v = await version();
    await app.page.keyboard.press("Enter");
    const warning = await app.page.locator(".monaco-dialog-box").innerText({ timeout: 15000 }).catch(() => "");
    await dialogButton("Insert");
    await waitVersion(v);
    await sleep(3000);                                            // give Mark Sharp time to react to the change
    const after = (await doc()).text;
    const removedWarning = await app.page.locator(".notifications-toasts").innerText().catch(() => "");
    const msShows = await ms.evaluate(() => document.body.innerText.includes("Condition Analysis Workflow")).catch(() => false);
    rec("11a Mark Sharp typing reaches VS Code's shared document and the Designer shows it", !!synced && !!banner, { banner: !!banner });
    rec("11b insertion warns that the file is also open in Mark Sharp", /Mark Sharp/.test(warning), warning.slice(0, 120));
    rec("11c after the insertion Mark Sharp keeps both the typed text and the inserted block (no overwrite)",
        after.includes("MarkSharpTyped") && after.split(`diagram:start ${OWNED}`).length === 3 && !/was removed by another change/.test(removedWarning),
        { markSharpRendersCaption: msShows });
    // race: type in Mark Sharp and insert immediately, without waiting for Mark Sharp to sync
    await app.host("command", { id: "notifications.clearAll" });
    await para.click(); await app.page.keyboard.press("End"); await app.page.keyboard.type(" RaceTyped");
    const a2 = await insertVia("5. Downstream impact", CRED);
    await waitFor(async () => (await version()) > a2.v, 8000);
    await sleep(4000);
    const raced = (await doc()).text;
    const toast = await app.page.locator(".notifications-toasts").innerText().catch(() => "");
    const kept = raced.includes("RaceTyped"), insertedKept = raced.split(`diagram:start ${CRED}`).length - 1;
    rec("11d race (insert while Mark Sharp has just-typed text): both kept, or the loss is detected and warned",
        (kept && insertedKept >= 2) || /was removed by another change/.test(toast), { typedKept: kept, credBlocks: insertedKept, warned: /removed/.test(toast) });
    await f.locator("h1").click(); await app.page.keyboard.press("Control+Z"); await sleep(1200);
    const afterUndo = (await doc()).text;
    rec("11e undo in the Designer removes the last insertion and keeps Mark Sharp's typing",
        afterUndo.includes("MarkSharpTyped") && afterUndo.split(`diagram:start ${CRED}`).length - 1 === insertedKept - 1, null);
    await app.host("save", { path: FEATURE }); await sleep(1500);
    const saved = fs.readFileSync(path.join(WS, FEATURE), "utf8");
    markSharpSaved = saved;
    fs.writeFileSync(path.join(EV, "11-after-mark-sharp-save.md"), saved);        // evidence: what Mark Sharp wrote
    const check1 = py(["-m", "tools.design", "check"]);
    const stale = await waitFor(() => f.evaluate(() => { const s = document.querySelector("#stale"); return s && !s.hidden ? s.textContent : ""; }), 8000);
    await snap("stale-banner");
    py(["-m", "tools.design", "index"]);                  // summary and Related features rows are restored ...
    const afterIndex = fs.readFileSync(path.join(WS, FEATURE), "utf8");
    // ... but a reformatted diagram block is a conflict (U13, exact comparison): never overwritten by index
    const conflicts = [...py(["-m", "tools.design", "check"]).matchAll(/line (\d+): the diagram block for \S+ was edited by hand/g)]
      .map((m) => +m[1]).sort((a, b) => b - a);
    const untouched = conflicts.every((n) => afterIndex.split(/\r?\n/)[n] === saved.split(/\r?\n/)[n]);
    for (const n of conflicts) {                             // explicit reconciliation, bottom up: preview, then confirm
      const preview = py(["-m", "tools.design", "reconcile", "--file", FEATURE, "--line", String(n), "--discard"]);
      py(["-m", "tools.design", "reconcile", "--file", FEATURE, "--line", String(n), "--discard", "--confirm", preview.trim().split(/\s+/).pop()]);
    }
    const restored = fs.readFileSync(path.join(WS, FEATURE), "utf8");
    const check2 = py(["-m", "tools.design", "check"]);
    const authored = (s) => s.replace(/<!-- (diagram|summary|related-features):start[\s\S]*?<!-- (diagram|summary|related-features):end -->/g, "").replace(/\r/g, "");
    rec("11f Mark Sharp's reformatting of generated blocks is detected (check + Designer banner) as conflicts that index never overwrites; reconcile --discard restores them; authored text identical",
        (/0 problem\(s\)/.test(check1) || !!stale) && conflicts.length > 0 && untouched && /0 problem\(s\)/.test(check2) &&
        authored(saved) === authored(restored) && restored.includes("MarkSharpTyped") && restored.includes("RaceTyped"),
        { checkAfterMarkSharp: check1.trim().split("\n").pop(), banner: (stale || "").slice(0, 80), conflicts: conflicts.length,
          untouched, checkAfterReconcile: check2.trim().split("\n").pop() });
  });

  // T-98: the blank-line placeholder of a generated copy survives Mark Sharp's save and a reopen.
  // AD-0011 (credential boundary, a flowchart) has one blank line, written as "%% (blank line)".
  await step("11g T-98 blank-line placeholder through Mark Sharp", async () => {
    if (!app.markSharp) { rec("11g T-98 blank-line placeholder through Mark Sharp", false, "Mark Sharp 1.13.0 not found; not tested"); return; }
    const PH = "%% (blank line)";
    /** The Mermaid lines (between the opening and closing fence) of every block of `id` in `s`; the fences are
     *  found, not counted, so a change Mark Sharp makes around them (11f) does not shift the comparison. */
    const bodies = (s, id) => {
      const L = s.split(/\r?\n/), out = [];
      L.forEach((l, i) => {
        if (!l.startsWith(`<!-- diagram:start ${id} `) && l !== `<!-- diagram:start ${id} -->`) return;
        const end = L.indexOf("<!-- diagram:end -->", i);
        const open = L.findIndex((x, j) => j > i && j < end && /^`{3,}mermaid/.test(x));
        if (open < 0) { out.push(null); return; }
        const fence = L[open].match(/^`+/)[0];
        const close = L.findIndex((x, j) => j > open && x.trim() === fence);
        out.push(close > open && close < end ? L.slice(open + 1, close) : null);
      });
      return out;
    };
    const same = (b) => !!b && JSON.stringify(b) === JSON.stringify(generated);
    // Mark Sharp reformats a generated block it reads as part of the list before it (indentation dropped,
    // blank lines added; the known behaviour of 11f, the same 4 conflicts before T-98). In such a copy the
    // placeholder must still be there exactly, in the same place among the other lines.
    const content = (b) => b.map((l) => l.trim()).filter((l) => l);
    const placeholderKept = (b) => !!b && b.filter((l) => l === PH).length === generated.filter((l) => l === PH).length &&
      !b.includes("%%") && JSON.stringify(content(b)) === JSON.stringify(content(generated));
    const firstDiff = (b) => { if (!b) return "no closed Mermaid fence"; const k = b.findIndex((l, j) => l !== generated[j]);
                               return k < 0 && b.length === generated.length ? null : { line: k < 0 ? b.length : k, got: b[k], want: generated[k] }; };
    const generated = bodies(insertedText, CRED)[0];
    if (!generated || generated.filter((l) => l === PH).length !== 1) throw new Error(`the generated ${CRED} copy has no placeholder line`);
    const afterSave = markSharpSaved ? bodies(markSharpSaved, CRED) : [];
    rec("11g after Mark Sharp's save the placeholder line survives in every AD-0011 copy, in place and never as a bare %%; a copy Mark Sharp does not reformat (11f) is kept exactly",
        afterSave.length >= 1 && afterSave.some(same) && afterSave.every(placeholderKept),
        { blocks: afterSave.length, exact: afterSave.map(same), placeholderKept: afterSave.map(placeholderKept),
          placeholders: afterSave.map((b) => b && b.filter((l) => l === PH).length), diff: afterSave.map(firstDiff) });
    // reopen in Mark Sharp, change a paragraph so that Mark Sharp writes the whole document again, save, read back
    await app.host("closeAll"); await dialogDismissIfAny(); await sleep(2000);   // no stale Mark Sharp frame
    const before = fs.readFileSync(path.join(WS, FEATURE), "utf8");
    await app.host("openWith", { path: FEATURE, viewType: "msharp.customEditor", column: 1 });
    await sleep(2000);
    const ms = await markSharpFrame(app.page);
    if (!ms) throw new Error("Mark Sharp did not open");
    await sleep(4000);
    const view = await ms.evaluate(() => {
      const svgs = [...document.querySelectorAll("svg")].filter((s) => s.closest("[data-lexical-editor]") || s.querySelector("g"));
      return { svgs: svgs.length, percentNode: svgs.some((s) => [...s.querySelectorAll("text, span, p, div")].some((n) => n.textContent.trim() === "%%")),
               syntaxError: /Syntax error|Parse error/i.test(document.body.innerText) };
    }).catch((e) => ({ error: String(e) }));
    await snap("t98-mark-sharp-reopen");
    const para = ms.locator("[data-lexical-editor] p").filter({ hasText: "Who needs the result" }).first();   // untouched by 11d's race
    await para.scrollIntoViewIfNeeded(); await para.click(); await app.page.keyboard.press("End"); await app.page.keyboard.type(" T98Typed");
    await waitFor(async () => (await doc()).text.includes("T98Typed"), 10000);
    await app.host("save", { path: FEATURE }); await sleep(1500);
    const resaved = fs.readFileSync(path.join(WS, FEATURE), "utf8");
    const again = bodies(resaved, CRED);
    rec("11h reopened and saved again in Mark Sharp: the placeholder line still survives in every AD-0011 copy; Mark Sharp shows no %% node and no syntax error",
        resaved.includes("T98Typed") && again.length >= 1 && again.some(same) && again.every(placeholderKept) &&
        !view.error && !view.percentNode && !view.syntaxError,
        { blocks: again.length, exact: again.map(same), placeholderKept: again.map(placeholderKept),
          placeholders: again.map((b) => b && b.filter((l) => l === PH).length), diff: again.map(firstDiff), view });
    fs.writeFileSync(path.join(EV, "t98-after-mark-sharp-reopen-save.md"), resaved);
    await snap("t98-mark-sharp-resaved");
    // put the fixture back as it was before this step (test data only), for the steps that follow
    await app.host("closeAll"); await dialogDismissIfAny();
    fs.writeFileSync(path.join(WS, FEATURE), before);
  });

  await prB1Steps();
  await prB2aSteps();
  await prB2b1Steps();
  await prB2b2bSteps();

  await close(app); app = null;

  // workspace trust: the editor is not available in an untrusted workspace
  await step("12 untrusted workspace", async () => {
    app = await launch({ trust: true, markSharp: false });
    const trusted = await app.host("trusted");
    let opened = true;
    try { await app.host("openWith", { path: FEATURE, viewType: "featureDesigner.editor" }); } catch { opened = false; }
    const frame = await designerFrame(app.page, 8000);
    const pid = (await app.host("designer", { fn: "bridgePid" })).value || null;
    const notice = await waitFor(async () => { for (const fr of app.page.frames()) { const t = await fr.evaluate(() => document.body && document.body.innerText).catch(() => ""); if (/disabled in Restricted Mode/.test(t || "")) return true; } return false; }, 10000);
    await snap("untrusted");
    rec("12 in an untrusted workspace Feature Designer shows a Restricted Mode notice only (no scripts, no Python)",
        trusted === false && !frame && !pid && !!notice, { trusted, openWithSucceeded: opened, designerFrame: !!frame, pythonPid: pid, notice: !!notice });
  });
  await close(app); app = null;

  fs.writeFileSync(path.join(EV, "e2e-results.json"), JSON.stringify(results, null, 2));
  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length} of ${results.length} checks passed`);
  process.exit(failed.length ? 1 : 0);
})().catch(async (e) => { console.error(e); await close(app); process.exit(2); });

// ---------------------------------------------------------------------------------------- PR B1
const OWN_SRC = "designs/features/diagrams/road-pipe-intersections_process_pipe-flow.md";
const SHARED_SRC = "designs/features/diagrams/condition-analysis_system-architecture_shared-condition-view.md";
const registryText = () => fs.readFileSync(path.join(WS, "designs/diagrams/registry.yml"), "utf8");
const stateOf = (id) => f.evaluate((x) => { const g = document.querySelector(`.gen[data-diagram="${x}"]`); return g ? g.dataset.state : ""; }, id);
const statusText = () => f.evaluate(() => { const s = document.querySelector("#status"); return s && s.style.display !== "none" ? s.textContent : ""; });
function archHash() {
  const h = crypto.createHash("sha256");
  const walk = (dir) => { for (const n of fs.readdirSync(dir).sort()) { const p = path.join(dir, n); if (fs.statSync(p).isDirectory()) walk(p); else h.update(n).update(fs.readFileSync(p)); } };
  walk(path.join(WS, "docs/architecture"));
  return h.digest("hex");
}
/** Undo/redo in Feature Designer: Edit Diagram leaves the keyboard focus in the source opened beside it. */
async function designerKey(key) {
  await app.host("command", { id: "workbench.action.focusFirstEditorGroup" });
  await f.locator("h1").click(); await app.page.keyboard.press(key);
}
async function makeNew(heading, name, ownerId) {
  const b = await blockAfter(heading);
  await placeMenu(b.idx, "Make New Diagram");
  await f.waitForSelector(".make-new", { timeout: 15000 });
  const category = await f.locator(".dg-category").inputValue();
  const ownerBefore = await waitFor(() => f.locator(".owner-text").innerText().then((t) => (/—/.test(t) ? t : "")), 15000) || await f.locator(".owner-text").innerText();
  await f.locator(".dg-name").fill(name);
  let confirmText = "";
  if (ownerId) {
    await f.locator(".change-owner").click();
    await f.locator(".owner-select").selectOption(ownerId);
    await f.locator(".use-owner").click();
    confirmText = await f.locator(".confirm-text").innerText();
    await f.locator(".confirm-owner").click();
  }
  const file = await waitFor(() => f.evaluate(() => { const e = document.querySelector(".dg-file"); return e && /^File: /.test(e.textContent) ? e.textContent : ""; }), 15000);
  const ownerAfter = await f.locator(".owner-text").innerText();
  const v = await version();
  await f.locator(".dlg button.primary").click();
  return { category, ownerBefore, ownerAfter, confirmText, file, v };
}

async function prB1Steps() {
  const archBefore = archHash();
  await step("B3 Make New Diagram", async () => {
    // a clean start even if an earlier step failed: Mark Sharp closed, the fixture file saved (test data only)
    await app.host("save", { path: FEATURE }); await sleep(500);
    await app.host("closeAll"); await dialogDismissIfAny();
    if ((await app.host("tabs")).length) { await app.host("revert", { path: FEATURE }); await app.host("closeAll"); await dialogDismissIfAny(); }
    if ((await app.host("tabs")).length) throw new Error(`could not start from a clean state: ${JSON.stringify(await app.host("tabs"))}`);
    await app.host("openWith", { path: FEATURE, viewType: "featureDesigner.editor", column: 1 });
    f = await designerFrame(app.page);
    const before = (await doc()).text;
    const m = await makeNew("3. Logic", "Pipe flow");
    await waitVersion(m.v);
    const after = (await doc()).text, L = after.split(/\r?\n/), i = markerAt(L, "FD-0001-D1");
    const logic = L.indexOf("## 3. Logic"), deps = L.indexOf("## 4. Dependencies");
    const tab = await waitFor(async () => (await app.host("tabs")).find((t) => t.label === path.basename(OWN_SRC) && t.kind === "text"));
    const line = await waitFor(() => app.page.locator(".line-numbers.active-line-number").allTextContents().then((x) => { const n = x.map((s) => s.trim()).filter(Boolean); return n.length ? n : null; }), 10000) || [];
    const src = fs.readFileSync(path.join(WS, OWN_SRC), "utf8").split(/\r?\n/);
    const reg = registryText();
    await snap("make-new-created");
    rec("B3 Make New: category preselected from section 3 (process), owner = this feature, one source file and one registry entry, the reference inserted at + with a fingerprint, its source opened at the Mermaid line",
        m.category === "process" && /FD-0001 — Road pipe intersections \(the feature you are editing\)/.test(m.ownerBefore) && m.file === `File: ${OWN_SRC}` &&
        fs.existsSync(path.join(WS, OWN_SRC)) && reg.split("diagram_id: FD-0001-D1").length === 2 && logic < i && i < deps &&
        /^<!-- diagram:start FD-0001-D1 sha256:[0-9a-f]{16} -->$/.test(L[i]) && before.split(/\r?\n/).every((l) => L.includes(l)) &&
        !!tab && line && line.some((n) => (src[+n - 1] || "").startsWith("```mermaid")),
        { category: m.category, owner: m.ownerBefore, file: m.file, i, logic, deps, line });
    rec("B3b the source content is not copied: the document holds only the generated reference block",
        !after.includes("Question this diagram answers") && after.includes("road-pipe-intersections_process_pipe-flow.md"));
    await designerKey("Control+Z"); await sleep(1000);
    const undone = await text();
    await designerKey("Control+Y"); await sleep(1000);
    rec("B3c one Ctrl+Z removes exactly the inserted reference (the created source stays registered); Ctrl+Y restores it",
        undone === before && (await text()) === after && fs.existsSync(path.join(WS, OWN_SRC)));
    const b = await blockAfter("3. Logic");
    await placeMenu(b.idx, "Add Existing Diagram");
    await f.waitForSelector(".tree li.item", { state: "attached", timeout: 20000 });
    await f.locator('.dlg input[type="search"]').fill("pipe flow"); await sleep(200);
    const listed = await f.evaluate(() => [...document.querySelectorAll(".tree li.item")].filter((li) => li.offsetParent).map((li) => li.dataset.id));
    rec("B3d the new diagram is listed in the library under its owner", JSON.stringify(listed) === '["FD-0001-D1"]', listed);
    await app.page.keyboard.press("Escape");
  });

  await step("B4 Change owner", async () => {
    const m = await makeNew("4. Dependencies", "Shared condition view", "FD-0002");
    await waitVersion(m.v);
    const L = (await text()).split(/\r?\n/), i = markerAt(L, "FD-0002-D2");
    const resolved = JSON.parse(py(["-m", "tools.design", "resolve", "FD-0002-D2"]));
    rec("B4 Change owner… is explicit and confirmed (names both features); the diagram is created and owned by FD-0002 and referenced here",
        m.category === "system-architecture" && /FD-0002 — Condition analysis/.test(m.confirmText) && /not by FD-0001 — Road pipe intersections/.test(m.confirmText) &&
        /does not change its owner/.test(m.confirmText) && /not the feature you are editing/.test(m.ownerAfter) && m.file === `File: ${SHARED_SRC}` &&
        i > 0 && resolved.owner && resolved.owner.ref === "FD-0002" && resolved.path === SHARED_SRC,
        { category: m.category, confirm: m.confirmText.slice(0, 160), owner: m.ownerAfter, file: m.file, i, owner2: resolved.owner });
    const reg = registryText(), t = await text(), v = await version();
    for (const owner of ["FD-0099", "FD-0001 --root x"]) {
      await f.evaluate(([ver, o]) => window.FD_HOST.api.postMessage({ type: "makeNew", at: 30, version: ver, owner: o, title: "Not allowed", category: "other" }), [v, owner]);
      await sleep(1500);
    }
    const msg = await waitFor(statusText, 5000);
    rec("B4b an invalid owner is refused and nothing is created", registryText() === reg && (await text()) === t &&
        !fs.readdirSync(path.join(WS, "designs/features/diagrams")).some((n) => /not-allowed/.test(n)) && /feature ID|no feature/.test(msg || ""), msg);
  });

  await step("B5 created but not inserted", async () => {
    await app.host("command", { id: "notifications.clearAll" });
    await app.host("designer", { fn: "failNextInsertion" });
    const t = await text();
    const m = await makeNew("1. Objective", "Later flow");
    const note = await waitFor(() => f.evaluate(() => { const n = document.querySelector("#notice"); return n && !n.hidden ? n.innerText : ""; }), 20000);
    const toast = await waitFor(() => app.page.locator(".notifications-toasts").innerText().catch(() => ""), 8000);
    await snap("created-not-inserted");
    rec("B5 when the insertion fails after creation, the stable ID is shown with an Add Existing Diagram action; the document is unchanged; the diagram stays registered",
        /FD-0001-D2 was created and registered/.test(note || "") && /not inserted/.test(note || "") && /Add Existing Diagram/.test(note || "") &&
        /FD-0001-D2/.test(toast || "") && (await text()) === t && registryText().includes("diagram_id: FD-0001-D2"),
        { note: (note || "").slice(0, 160), toast: (toast || "").slice(0, 120) });
    await f.locator("#notice .add-existing").click();
    const prompt = await f.locator("#notice").innerText();
    const b = await blockAfter("1. Objective");
    await app.page.mouse.move(...Object.values(center(await box(blockSel(b.idx)))), { steps: 3 });
    await f.locator(`${blockSel(b.idx)} >> .plus`).click();
    await f.waitForSelector(".tree li.item", { state: "attached", timeout: 20000 });
    const dlg = await f.locator(".dlg header").innerText();
    const sel = await waitFor(() => f.evaluate(() => { const r = document.querySelector('.tree .row[aria-selected="true"]'); return r ? r.parentElement.dataset.id : ""; }), 5000);
    const v = await version();
    await app.page.keyboard.press("Enter");
    await waitVersion(v);
    const L = (await text()).split(/\r?\n/), i = markerAt(L, "FD-0001-D2"), obj = L.indexOf("## 1. Objective"), data = L.indexOf("## 2. Data contract");
    const cleared = await waitFor(() => f.evaluate(() => document.querySelector("#notice").hidden), 5000);
    rec("B5b Add Existing Diagram places it later: click + where it should go, the library opens with it selected, Enter inserts it, the notice clears",
        /Click \+ where diagram FD-0001-D2 should go/.test(prompt) && dlg === "Add Existing Diagram — place FD-0001-D2" && sel === "FD-0001-D2" &&
        obj < i && i < data && !!cleared, { prompt: prompt.slice(0, 80), dlg, sel, i, cleared: !!cleared });
  });

  await step("B6 Edit Diagram pencil", async () => {
    const open = async (id) => {
      await f.locator(`.edit-diagram[data-id="${id}"]`).first().scrollIntoViewIfNeeded();
      await f.locator(`.edit-diagram[data-id="${id}"]`).first().click();
    };
    const otherSrc = JSON.parse(py(["-m", "tools.design", "resolve", OWNED])).path;
    const activeIs = async (want) => (await waitFor(async () => { const t = (await app.host("tabs")).find((x) => x.active && x.kind === "text" && x.group === 2);
                                                                  return t && t.label === want ? t.label : ""; }, 10000)) ||
                                     ((await app.host("tabs")).find((x) => x.active && x.kind === "text" && x.group === 2) || {}).label;
    await open("FD-0001-D1"); const own = await activeIs(path.basename(OWN_SRC));
    await designerKey("Home"); await sleep(500);                       // focus back in the view, as a person would click
    await open(OWNED); const other = await activeIs(path.basename(otherSrc));
    await designerKey("Home");                                        // as a click on the pencil would: the view has the focus
    await f.evaluate((id) => window.FD_HOST.api.postMessage({ type: "editDiagram", id }), CRED_ALIAS); const byAlias = await activeIs("system-architecture.md");
    rec("B6 the pencil opens the authoritative source: this feature's, another feature's (no copy), and an architecture diagram by its former catalog ID",
        own === path.basename(OWN_SRC) && other === path.basename(otherSrc) && byAlias === "system-architecture.md", { own, other, byAlias });
  });

  await step("B2c conflicts and changed sources are never hidden", async () => {
    await app.host("replace", { path: FEATURE, find: 'B["New step (planned)"]', replace: 'B["Hand edited"]', after: "diagram:start FD-0001-D1 " });
    const st = await waitFor(async () => ((await stateOf("FD-0001-D1")) === "conflict" ? "conflict" : ""), 15000);
    const shown = await f.evaluate(() => {
      const g = document.querySelector('.gen[data-diagram="FD-0001-D1"]');
      return { warn: g.querySelector(".dg-notice.warn").innerText, labels: [...g.querySelectorAll(".dg-vlabel")].map((x) => x.innerText),
               svgs: g.querySelectorAll(".dg-version .mermaid-out svg").length, diff: [...g.querySelectorAll("pre.diff .del")].map((x) => x.textContent).join("") };
    });
    const banner = await waitFor(() => f.evaluate(() => { const s = document.querySelector("#stale"); return s && !s.hidden ? s.textContent : ""; }), 8000);
    await snap("conflict-both-versions");
    rec("B2c a hand-edited copy is marked as a conflict, shows the authoritative source and the document copy side by side, and the differences can be inspected",
        st === "conflict" && /edited by hand/.test(shown.warn) && /\(E15\)/.test(shown.warn) && shown.labels.length === 2 &&
        shown.labels[0].startsWith(`Authoritative source · ${OWN_SRC}`) && /Copy in this document · differs/.test(shown.labels[1]) &&
        shown.svgs === 2 && /Hand edited/.test(shown.diff) && /changed outside/.test(banner || ""), { st, ...shown, diff: shown.diff.slice(0, 80) });
    await designerKey("Control+Z");
    const back = await waitFor(async () => ((await stateOf("FD-0001-D1")) === "current" ? "current" : ""), 10000);
    const t = await text();
    await app.host("replace", { path: OWN_SRC, find: 'B["New step (planned)"]', replace: 'B["Source step"]' });
    await app.host("save", { path: OWN_SRC });
    const outdated = await waitFor(async () => ((await stateOf("FD-0001-D1")) === "outdated" ? "outdated" : ""), 15000);
    const o = await f.evaluate(() => {
      const g = document.querySelector('.gen[data-diagram="FD-0001-D1"]');
      const info = window.FD_DEBUG.state.blocks.list.find((b) => b.id === "FD-0001-D1");
      return { note: g.querySelector(".dg-notice").innerText, fromSource: info.generated.some((l) => l.includes("Source step")),
               copyOld: info.embedded.some((l) => l.includes("New step (planned)")), copyShown: !!g.querySelector("details.dg-copy") };
    });
    rec("B2d after its source is saved, the block is drawn from the source and marked out of date; a document with unsaved changes is not changed automatically",
        !!back && outdated === "outdated" && /Out of date in this document/.test(o.note) && o.fromSource && o.copyOld && o.copyShown && (await text()) === t, o);
    await app.host("replace", { path: OWN_SRC, find: 'B["Source step"]', replace: 'B["New step (planned)"]' });
    await app.host("save", { path: OWN_SRC });
    await waitFor(async () => ((await stateOf("FD-0001-D1")) === "current" ? "current" : ""), 15000);
  });

  await step("B10 retired and missing sources", async () => {
    py(["-m", "tools.design", "registry", "retire", "FD-0001-D2", "--confirm"]);
    const st = await waitFor(async () => ((await stateOf("FD-0001-D2")) === "retired" ? "retired" : ""), 15000);
    const note = await f.evaluate(() => document.querySelector('.gen[data-diagram="FD-0001-D2"] .dg-notice').innerText);
    await f.locator('.edit-diagram[data-id="FD-0001-D2"]').click();
    const pencil = await waitFor(statusText, 8000);
    const b = await blockAfter("3. Logic");
    await placeMenu(b.idx, "Add Existing Diagram");
    await f.waitForSelector(".tree li.item", { state: "attached", timeout: 20000 });
    await f.locator('.dlg input[type="search"]').fill("FD-0001-D2"); await sleep(200);
    const listed = await f.evaluate(() => [...document.querySelectorAll(".tree li.item")].filter((li) => li.offsetParent).length);
    await app.page.keyboard.press("Escape");
    const t = await text(), v = await version();
    await f.locator('.gen[data-diagram="FD-0001-D2"] .remove-ref').click();
    await waitVersion(v);
    const removed = await text();
    await designerKey("Control+Z"); await sleep(1000);
    const restored = await text();
    rec("B10 a retired diagram shows a placeholder (E11) with Remove reference; the pencil explains instead of opening; the library hides it; removal is one undoable edit",
        st === "retired" && /retired on/.test(note) && /\(E11\)/.test(note) && /retired/.test(pencil || "") && listed === 0 &&
        markerAt(removed.split(/\r?\n/), "FD-0001-D2") < 0 && restored === t, { st, note: note.slice(0, 100), pencil: (pencil || "").slice(0, 100), listed });
    const src = path.join(WS, SHARED_SRC);
    fs.renameSync(src, `${src}.moved`);
    const missing = await waitFor(async () => ((await stateOf("FD-0002-D2")) === "missing" ? "missing" : ""), 15000);
    const mnote = await f.evaluate(() => document.querySelector('.gen[data-diagram="FD-0002-D2"] .dg-notice').innerText);
    await f.locator('.edit-diagram[data-id="FD-0002-D2"]').click();
    const mpencil = await waitFor(async () => { const s = await statusText(); return /FD-0002-D2/.test(s || "") ? s : ""; }, 8000);
    await snap("missing-source");
    fs.renameSync(`${src}.moved`, src);
    const again = await waitFor(async () => ((await stateOf("FD-0002-D2")) === "current" ? "current" : ""), 15000);
    rec("B10b a missing source shows a placeholder with E7 and the fix; the pencil explains; it renders again when the source is back",
        missing === "missing" && /\(E7\)/.test(mnote) && /cannot be opened/.test(mpencil || "") && !!again, { mnote: mnote.slice(0, 120), mpencil: (mpencil || "").slice(0, 100) });
  });

  await step("B12 safety", async () => {
    rec("B12 docs/architecture/ unchanged byte for byte through every PR B1 step", archHash() === archBefore);
  });
}

// ---------------------------------------------------------------------------------------- PR B2a
const CA = "designs/features/condition-analysis.md";
const caText = async () => (await doc(CA)).text;
const write = (rel, from, to) => { const f2 = path.join(WS, rel); const s = fs.readFileSync(f2, "utf8"); if (!s.includes(from)) throw new Error(`${from} not in ${rel}`); fs.writeFileSync(f2, s.replace(from, to)); };
const stripRow = (cls) => f.evaluate((c) => { const r = document.querySelector(`#strip .strip-row.${c}`); return r ? r.innerText : ""; }, cls);
async function caKey(key) { await app.host("command", { id: "workbench.action.focusFirstEditorGroup" }); await f.locator("h1").click(); await app.page.keyboard.press(key); }
async function openCa() {                          // the fixture file is saved first: closing never meets a save prompt
  if ((await doc(CA)) && (await doc(CA)).isDirty) { await app.host("save", { path: CA }); await sleep(500); }
  await app.host("closeAll"); await dialogDismissIfAny();
  if ((await app.host("tabs")).length) { await app.host("revert", { path: FEATURE }); await app.host("revert", { path: CA }); await app.host("closeAll"); await dialogDismissIfAny(); }
  await app.host("openWith", { path: CA, viewType: "featureDesigner.editor", column: 1 });
  f = await designerFrame(app.page);
  await waitFor(() => f.evaluate(() => !!document.querySelector("h1")), 15000);
}
async function caInsert(heading, query) { const a = await insertVia(heading, query); await waitFor(async () => (await version()) > a.v, 15000); await sleep(300); }
async function review(id) {
  await f.locator(`.gen[data-diagram="${id}"] .review`).first().scrollIntoViewIfNeeded();
  await f.locator(`.gen[data-diagram="${id}"] .review`).first().click();
  await f.waitForSelector(".dlg .review", { timeout: 15000 });
}
const blockState = (id) => f.evaluate((x) => { const g = document.querySelector(`.gen[data-diagram="${x}"]`); return g ? g.dataset.state : ""; }, id);

async function prB2aSteps() {
  const archBefore = archHash();
  let ownedSrc = "";
  const extra = [];
  await step("B2a setup", async () => {
    for (let i = 1; i <= 5; i++) {                       // sources for the event-storm test (C5)
      const out = py(["-m", "tools.design", "new", "diagram", "--feature", "FD-0002", "--title", `Storm ${i}`, "--json"]);
      extra.push(JSON.parse(out).path);
    }
    ownedSrc = JSON.parse(py(["-m", "tools.design", "resolve", OWNED])).path;
    await app.host("save", { path: FEATURE });
    await openCa();
    await caInsert("1. Objective", "credential");
    await caInsert("2. Data contract", "condition analysis workflow");
    await caInsert("3. Logic", "pipe flow");
    await app.host("save", { path: CA }); await sleep(1200);
    const ok = !(await doc(CA)).isDirty && markerAt((await caText()).split(/\r?\n/), "FD-0001-D1") > 0;
    rec("B2a setup: a saved feature document with an architecture diagram, its own diagram and another feature's diagram", ok, { extra: extra.length, ownedSrc });
  });

  await step("S1 automatic refresh of a clean document", async () => {
    const t0 = await caText();
    write(OWN_SRC, 'B["New step (planned)"]', 'B["Auto one"]');
    const done = await waitFor(async () => { const d = await doc(CA); return d.isDirty && d.text.includes('B["Auto one"]') ? d : null; }, 20000);
    const note = await waitFor(() => stripRow("auto"), 5000);
    const disk = fs.readFileSync(path.join(WS, CA), "utf8");
    const changed = done ? done.text.split(/\r?\n/).filter((l, i) => l !== t0.split(/\r?\n/)[i]).length : -1;
    await snap("b2a-auto-refresh");
    // Show changes compares read-only snapshots: closing it must never ask to save (and so never revert) the document
    await f.locator("#strip .show-changes").click();
    const diffTab = await waitFor(async () => (await app.host("tabs")).find((x) => /saved ↔ now/.test(x.label)), 10000);
    await app.host("command", { id: "workbench.action.closeActiveEditor" }, 8000);
    await sleep(1200);
    const prompt = await app.page.locator(".monaco-dialog-box").count();
    const still = await doc(CA);
    rec("S1d Show changes opens a read-only comparison; closing it asks nothing and the document keeps the unsaved refresh",
        !!diffTab && prompt === 0 && still.isDirty && still.text.includes('B["Auto one"]'), { tab: diffTab && diffTab.label, prompt });
    await app.host("command", { id: "workbench.action.focusFirstEditorGroup" }); await sleep(300);
    await f.locator("#strip .undo-refresh").click(); await sleep(1000);
    const undone = await doc(CA);
    rec("S1 a clean document open only in Feature Designer is refreshed automatically: one edit, not saved (disk unchanged), with an Undo / Show changes / Save notice; Undo restores it exactly",
        !!done && !disk.includes("Auto one") && /Updated 1 diagram from its source \(FD-0001-D1\) — not saved/.test(note || "") &&
        undone.text === t0 && !undone.isDirty && changed > 0 && changed <= 3, { changedLines: changed, note: (note || "").slice(0, 120), undoneClean: !undone.isDirty });
    // Make New in a clean document with an out-of-date block: its own registry write must not trigger a
    // refresh that races with the insertion (found in a GUI run)
    const before = await caText();
    const m = await makeNew("4. Dependencies", "During refresh");
    await waitVersion(m.v);
    const withNew = await caText();
    const ins = markerAt(withNew.split(/\r?\n/), "FD-0002-D8");
    const newNotice = await f.evaluate(() => { const n = document.querySelector("#notice"); return n && !n.hidden ? n.innerText : ""; });
    rec("S1c Make New in a clean document with an out-of-date block is inserted normally; the out-of-date block is not refreshed meanwhile",
        ins > 0 && !newNotice && !withNew.includes('B["Auto one"]') && before.split(/\r?\n/).every((l) => withNew.split(/\r?\n/).includes(l)),
        { ins, notice: newNotice.slice(0, 80) });
    await app.host("command", { id: "workbench.action.focusFirstEditorGroup" });
    const counts = await waitFor(() => stripRow("counts"), 8000);
    await f.locator("#strip .refresh-now").first().click();          // in the counts row, or with the reason it was not automatic
    await waitFor(async () => (await caText()).includes('B["Auto one"]'), 10000);
    rec("S1b afterwards the strip shows the block as out of date with Refresh now, which refreshes it as one edit", /1 out of date/.test(counts || "") && (await caText()).includes('B["Auto one"]'), counts);
    await app.host("save", { path: CA }); await sleep(1000);
  });

  await step("S2 a document with unsaved changes is never refreshed automatically", async () => {
    await app.host("replace", { path: CA, find: "[Who needs the result?]", replace: "[Who needs the result?] typed" });
    await sleep(500);
    const t1 = await caText();
    write(OWN_SRC, 'B["Auto one"]', 'B["Auto two"]');
    await sleep(3500);
    const untouched = (await caText()) === t1;
    const manual = await waitFor(() => stripRow("manual"), 8000);
    await snap("b2a-manual-refresh");
    await f.locator("#strip .manual .refresh-now").click();
    await waitFor(async () => (await caText()).includes('B["Auto two"]'), 10000);
    const refreshed = await caText();
    await caKey("Control+Z"); await sleep(1000);
    rec("S2 unsaved edits: nothing changes automatically; the notice says why and Refresh now applies one edit that keeps the typing; one Ctrl+Z reverts exactly it",
        untouched && /out of date \(FD-0001-D1\); not refreshed automatically because this document has unsaved changes/.test(manual || "") &&
        refreshed.includes("typed") && refreshed.includes('B["Auto two"]') && (await caText()) === t1, (manual || "").slice(0, 140));
    await caKey("Control+Y"); await sleep(800);
    await app.host("save", { path: CA }); await sleep(1000);
  });

  await step("S3 conflicts are never refreshed", async () => {
    await app.host("replace", { path: CA, find: 'B["New step (planned)"]', replace: 'B["Hand edited copy"]', after: `diagram:start ${OWNED} ` });
    await app.host("save", { path: CA }); await sleep(1500);
    write(OWN_SRC, 'B["Auto two"]', 'B["Auto three"]');
    const done = await waitFor(async () => ((await caText()).includes('B["Auto three"]') ? true : null), 20000);
    const t = await caText();
    rec("S3 with a conflict in the same document, only the out-of-date block is refreshed; the conflicting copy is kept",
        !!done && t.includes('B["Hand edited copy"]') && (await blockState(OWNED)) === "conflict", { conflict: await blockState(OWNED) });
    await app.host("save", { path: CA }); await sleep(1000);
  });

  await step("S4 typing while a refresh is prepared", async () => {
    await app.host("designer", { fn: "delayNextAutoRefresh" });
    write(OWN_SRC, 'B["Auto three"]', 'B["Auto four"]');
    await sleep(1200);
    await app.host("replace", { path: CA, find: "[Who needs the result?] typed", replace: "[Who needs the result?] typed again" });
    await sleep(4500);
    const t = await caText();
    const manual = await waitFor(() => stripRow("manual"), 5000);
    rec("S4 if the document changes while an automatic refresh is prepared, nothing is applied and Refresh now is offered",
        t.includes("typed again") && !t.includes('B["Auto four"]') && /not refreshed automatically/.test(manual || ""), (manual || "").slice(0, 120));
    await f.locator("#strip .manual .refresh-now").click();
    await waitFor(async () => (await caText()).includes('B["Auto four"]'), 10000);
    await app.host("save", { path: CA }); await sleep(1000);
  });

  await step("S5 two views of one document", async () => {
    await app.host("openWith", { path: CA, viewType: "featureDesigner.editor", column: 2 });
    await sleep(2000);
    const t0 = await caText();
    write(OWN_SRC, 'B["Auto four"]', 'B["Auto five"]');
    const done = await waitFor(async () => ((await caText()).includes('B["Auto five"]') ? true : null), 20000);
    await sleep(1500);
    await app.host("command", { id: "workbench.action.focusFirstEditorGroup" });
    f = await designerFrame(app.page);
    await caKey("Control+Z"); await sleep(1000);
    rec("S5 with two Feature Designer views of the document it is refreshed once (one Ctrl+Z restores the saved text)", !!done && (await caText()) === t0);
    await caKey("Control+Y"); await sleep(800);
    await app.host("save", { path: CA }); await sleep(800);
    await openCa();
  });

  await step("S8 review: Discard manual change", async () => {
    await review(OWNED);
    const dlg = await f.evaluate(() => ({ title: document.querySelector(".dlg header").textContent,
      labels: [...document.querySelectorAll(".dlg .dg-vlabel")].map((x) => x.textContent),
      buttons: [...document.querySelectorAll(".dlg footer button")].map((x) => `${x.textContent}${x.disabled ? " (disabled)" : ""}`) }));
    await snap("b2a-review");
    await f.locator(".dlg footer .discard").click();
    const confirmText = await f.locator(".dlg .review").innerText();
    const v = await version();
    await f.locator(".dlg footer .confirm").click();
    await waitVersion(v);
    const after = await caText();
    const st = await waitFor(async () => ((await blockState(OWNED)) === "current" ? "current" : ""), 10000);
    await caKey("Control+Z"); await sleep(1000);
    const undone = await caText();
    rec("S8 Review shows both versions and both actions; Discard previews exactly what changes, then restores the generated copy as one undoable edit",
        dlg.title === `Review changed diagram ${OWNED}` && dlg.labels.length === 2 && /Authoritative source/.test(dlg.labels[0]) &&
        JSON.stringify(dlg.buttons) === '["Cancel","Discard manual change…","Apply to source…"]' && /The source is not changed/.test(confirmText) &&
        !after.includes("Hand edited copy") && st === "current" && undone.includes("Hand edited copy"), { ...dlg, st });
  });

  await step("S8b review: Apply to source", async () => {
    const srcBefore = fs.readFileSync(path.join(WS, ownedSrc), "utf8");
    await review(OWNED);
    await f.locator(".dlg footer .apply").click();
    const confirmText = await f.locator(".dlg .review").innerText();
    const v = await version();
    await f.locator(".dlg footer .confirm").click();
    await waitVersion(v);
    const msg = await waitFor(statusText, 8000);
    const src = fs.readFileSync(path.join(WS, ownedSrc), "utf8");
    const st = await waitFor(async () => ((await blockState(OWNED)) === "current" ? "current" : ""), 10000);
    const pending = (await app.host("designer", { fn: "pendingRecovery" })).value;
    rec("S8b Apply to source saves the source, then updates the block (not saved); the message says Ctrl+Z reverts only the block; nothing is left pending",
        /reverts only the block/.test(confirmText) && src.includes('B["Hand edited copy"]') && src !== srcBefore && !(await doc(CA)).text.includes("diagram:start x") &&
        st === "current" && /Applied to source: saved .* Ctrl\+Z in this document reverts only the block/.test(msg || "") && pending.length === 0 && (await doc(CA)).isDirty,
        { msg: (msg || "").slice(0, 160), pending });
    await app.host("save", { path: CA }); await sleep(800);
  });

  await step("S8c a source changed after the review is never overwritten", async () => {
    await app.host("replace", { path: CA, find: 'B["Hand edited copy"]', replace: 'B["Stale review"]', after: `diagram:start ${OWNED} ` });
    await sleep(800);
    await review(OWNED);
    await f.locator(".dlg footer .apply").click();
    write(ownedSrc, 'A["Existing step"]', 'A["Moved on"]');
    await sleep(1500);
    await f.locator(".dlg footer .confirm").click();
    const msg = await waitFor(async () => { const s = await statusText(); return /changed since the review/.test(s || "") ? s : ""; }, 8000);
    const src = fs.readFileSync(path.join(WS, ownedSrc), "utf8");
    rec("S8c if the source changes between the review and the confirmation, nothing is written and the review must be repeated",
        !!msg && src.includes("Moved on") && !src.includes("Stale review") && (await caText()).includes("Stale review"), (msg || "").slice(0, 120));
    await review(OWNED);
    await f.locator(".dlg footer .apply").click();
    const box = await f.evaluate(() => ({ disabled: document.querySelector(".dlg footer .confirm").disabled, label: (document.querySelector(".dlg .replace-confirm") || {}).innerText || "",
                                         warn: (document.querySelector(".dlg .dg-notice.warn") || {}).innerText || "" }));
    await f.locator(".dlg .replace-ok").check();
    const enabled = await f.evaluate(() => !document.querySelector(".dlg footer .confirm").disabled);
    const v = await version();
    await f.locator(".dlg footer .confirm").click();
    await waitVersion(v);
    const src2 = fs.readFileSync(path.join(WS, ownedSrc), "utf8");
    rec("S8d when applying would replace changes made in the source, Confirm stays disabled until that is explicitly ticked",
        box.disabled && /Replace the changes made in/.test(box.label) && /replaces those source changes/.test(box.warn) && enabled && src2.includes("Stale review") && !src2.includes("Moved on"), box);
    await app.host("save", { path: CA }); await sleep(800);
  });

  await step("S8e architecture diagrams: Apply to source is not offered", async () => {
    await app.host("replace", { path: CA, find: 'ROLE --> NEON', replace: 'ROLE --> NEON2["Edited"]\n  ROLE --> NEON', after: `diagram:start ${CRED} ` });
    await waitFor(async () => ((await blockState(CRED)) === "conflict" ? 1 : 0), 10000);
    await review(CRED);
    const apply = await f.evaluate(() => ({ disabled: document.querySelector(".dlg footer .apply").disabled, text: document.querySelector(".dlg .review-actions").innerText }));
    await f.locator(".dlg footer .discard").click();
    const v = await version();
    await f.locator(".dlg footer .confirm").click();
    await waitVersion(v);
    rec("S8e for an architecture diagram Apply to source is disabled with the technical-lead reason; Discard restores the copy; docs/architecture is not written",
        apply.disabled && /technical-lead's documentation workflow/.test(apply.text) && !(await caText()).includes("NEON2") && archHash() === archBefore, apply.text.slice(0, 160));
  });

  await step("S9 a source with unsaved changes is never overwritten", async () => {
    await app.host("replace", { path: CA, find: 'B["Stale review"]', replace: 'B["Dirty source"]', after: `diagram:start ${OWNED} ` });
    await sleep(800);
    await app.host("openText", { path: ownedSrc, column: 2 });
    await app.host("replace", { path: ownedSrc, find: 'A["Existing step"]', replace: 'A["Unsaved in source"]' });
    await app.host("command", { id: "workbench.action.focusFirstEditorGroup" });
    const disk = fs.readFileSync(path.join(WS, ownedSrc), "utf8");
    await review(OWNED);
    await f.locator(".dlg footer .apply").click();
    await f.locator(".dlg footer .confirm").click();
    const msg = await waitFor(async () => { const s = await statusText(); return /unsaved changes/.test(s || "") ? s : ""; }, 8000);
    rec("S9 Apply to source is refused while the source has unsaved changes; nothing is written",
        !!msg && fs.readFileSync(path.join(WS, ownedSrc), "utf8") === disk && (await caText()).includes("Dirty source"), (msg || "").slice(0, 120));
    await app.host("revert", { path: ownedSrc });
    await openCa();
  });

  await step("C3 partial completion and recovery", async () => {
    const original = fs.readFileSync(path.join(WS, ownedSrc));
    await app.host("designer", { fn: "failNextReconcileDocument" });
    await review(OWNED);
    await f.locator(".dlg footer .apply").click();
    if (await f.locator(".dlg .replace-ok").count()) await f.locator(".dlg .replace-ok").check();
    await f.locator(".dlg footer .confirm").click();
    const row = await waitFor(() => stripRow("partial"), 15000);
    const pending = (await app.host("designer", { fn: "pendingRecovery" })).value;
    const written = fs.readFileSync(path.join(WS, ownedSrc), "utf8");
    const atPartial = await caText();
    await sleep(3000);                                    // the source change must not trigger a refresh of this document
    const heldOff = (await caText()) === atPartial;
    await snap("b2a-partial");
    rec("C3a when the source is saved but the block update fails, this is reported as partial (never as success), with a durable recovery record",
        /Partly done: .* was updated and saved, but the FD-0002-D1 block here was NOT updated/.test(row || "") && written.includes("Dirty source") &&
        (await caText()).includes("Dirty source") && pending.length === 1 && pending[0].state === "partial" && heldOff,
        { row: (row || "").slice(0, 160), pending, heldOff });
    await f.locator("#strip .partial .restore").click();
    await waitFor(async () => fs.readFileSync(path.join(WS, ownedSrc)).equals(original), 10000);
    const gone = await waitFor(async () => ((await app.host("designer", { fn: "pendingRecovery" })).value.length === 0 ? 1 : 0), 8000);
    await sleep(3000);                                    // time for any automatic refresh after the source change
    const kept = (await caText()).includes("Dirty source"), st = await blockState(OWNED);
    rec("C3b Restore the original source puts back the exact original bytes and clears the record; the copy the user wanted to apply stays in the document (as a conflict), never refreshed away",
        fs.readFileSync(path.join(WS, ownedSrc)).equals(original) && !!gone && kept && st === "conflict", { kept, st });
    await app.host("designer", { fn: "failNextReconcileDocument" });
    await waitFor(async () => ((await blockState(OWNED)) === "conflict" ? 1 : 0), 10000);
    await review(OWNED);
    await f.locator(".dlg footer .apply").click();
    if (await f.locator(".dlg .replace-ok").count()) await f.locator(".dlg .replace-ok").check();
    await f.locator(".dlg footer .confirm").click();
    await waitFor(() => stripRow("partial"), 15000);
    await f.locator("#strip .partial .finish").click();
    const fin = await waitFor(async () => ((await app.host("designer", { fn: "pendingRecovery" })).value.length === 0 && (await blockState(OWNED)) === "current" ? 1 : 0), 15000);
    rec("C3c Update the block now completes it: the block matches the saved source and the record is cleared", !!fin);
    await app.host("save", { path: CA }); await sleep(800);
  });

  await step("C3d a save setting that changes the source", async () => {
    await app.host("setGlobal", { section: "files", key: "trimTrailingWhitespace", value: true });   // the isolated test profile only
    await app.host("replace", { path: CA, find: 'B["Dirty source"]', replace: 'B["Trailing"]  ', after: `diagram:start ${OWNED} ` });
    await waitFor(async () => ((await blockState(OWNED)) === "conflict" ? 1 : 0), 10000);
    await review(OWNED);
    await f.locator(".dlg footer .apply").click();
    if (await f.locator(".dlg .replace-ok").count()) await f.locator(".dlg .replace-ok").check();
    await f.locator(".dlg footer .confirm").click();
    const row = await waitFor(() => stripRow("partial"), 10000);
    const pending = (await app.host("designer", { fn: "pendingRecovery" })).value;
    const src = fs.readFileSync(path.join(WS, ownedSrc), "utf8");
    await snap("b2a-trim-partial");
    rec("C3d when a save setting changes the source as it is saved, Apply to source stops: the strip shows Partly done at once, a durable record is kept, and the manual edit stays in the document",
        /Partly done/.test(row || "") && /Restore the original source/.test(row || "") && pending.length === 1 && pending[0].state === "partial" &&
        src.includes('B["Trailing"]') && (await caText()).includes('B["Trailing"]  '), { row: (row || "").slice(0, 140), pending });
    await app.host("setGlobal", { section: "files", key: "trimTrailingWhitespace", value: false });
    await app.host("command", { id: "featureDesigner.recovery" }, 4000).catch(() => {});
    await dialogButton("Keep the current source (forget)");
    await dialogButton("Keep the current source");
    const cleared = await waitFor(async () => ((await app.host("designer", { fn: "pendingRecovery" })).value.length === 0 && (await stripRow("partial")) === "" ? 1 : 0), 10000);
    rec("C3e the interrupted operation is resolved explicitly (keep the current source); the record and the strip row are cleared", !!cleared);
    await review(OWNED);
    await f.locator(".dlg footer .discard").click();
    await f.locator(".dlg footer .confirm").click();
    await sleep(1000);
    await app.host("save", { path: CA }); await sleep(800);
  });

  await step("S12 status strip and navigation", async () => {
    await app.host("replace", { path: CA, find: 'B["Trailing"]', replace: 'B["Navigate"]', after: `diagram:start ${OWNED} ` });
    await waitFor(async () => ((await blockState(OWNED)) === "conflict" ? 1 : 0), 10000);
    await f.evaluate(() => window.scrollTo(0, document.body.scrollHeight)); await sleep(500);
    const visible = await f.evaluate(() => { const s = document.querySelector("#strip"); const r = s.getBoundingClientRect(); return !s.hidden && r.top >= 0 && r.bottom < 260 ? s.innerText : ""; });
    await f.locator("#strip .counts .next").click(); await sleep(800);
    const nav = await f.evaluate(() => { const g = document.querySelector(".gen.dg.flash"); if (!g) return null; const r = g.getBoundingClientRect(); return { id: g.dataset.diagram, inView: r.top < innerHeight && r.bottom > 0 }; });
    await snap("b2a-strip");
    rec("S12 the status strip stays visible while scrolling, counts the blocks that need attention, and Next scrolls to one",
        /1 conflict/.test(visible || "") && nav && nav.id === OWNED && nav.inView, { visible: (visible || "").slice(0, 80), nav });
    await review(OWNED);
    await f.locator(".dlg footer .discard").click();
    await f.locator(".dlg footer .confirm").click();
    await sleep(1000);
    await app.host("save", { path: CA }); await sleep(800);
  });

  await step("S13 event storm", async () => {
    const t0 = await caText();
    write(OWN_SRC, 'B["Auto five"]', 'B["Storm"]');
    for (const e of extra) write(e, 'B["New step (planned)"]', 'B["Storm"]');
    await sleep(5000);
    const manual = await waitFor(() => stripRow("manual"), 8000);
    rec("S13 when more than 5 sources change within 2 seconds nothing is refreshed automatically; the strip says so and offers Refresh now",
        (await caText()) === t0 && /Many diagram sources changed at once \(6\)/.test(manual || ""), (manual || "").slice(0, 140));
    await f.locator("#strip .manual .refresh-now").click();
    await waitFor(async () => (await caText()).includes('B["Storm"]'), 10000);
    await app.host("save", { path: CA }); await sleep(800);
  });

  await step("S7 other editors", async () => {
    await app.host("openText", { path: CA, column: 2 });
    await sleep(1000);
    const t0 = await caText();
    write(OWN_SRC, 'B["Storm"]', 'B["Text editor open"]');
    await sleep(3500);
    const manual = await waitFor(() => stripRow("manual"), 8000);
    rec("S7 a document also open in the text editor is not refreshed automatically", (await caText()) === t0 && /also open in the text editor/.test(manual || ""), (manual || "").slice(0, 120));
    if (!app.markSharp) { rec("S7b Mark Sharp", false, "Mark Sharp not available"); return; }
    await openCa();
    await app.host("openWith", { path: CA, viewType: "msharp.customEditor", column: 2 });
    await sleep(2500);
    await app.host("command", { id: "workbench.action.focusFirstEditorGroup" });
    f = await designerFrame(app.page);
    const t1 = await caText();
    write(OWN_SRC, 'B["Text editor open"]', 'B["Mark Sharp open"]');
    await sleep(3500);
    const ms = await waitFor(() => stripRow("manual"), 8000);
    const changedAuto = (await caText()).includes('B["Mark Sharp open"]');
    rec("S7b a document also open in Mark Sharp is not refreshed automatically", !changedAuto && /Mark Sharp/.test(ms || ""), { ms: (ms || "").slice(0, 120), t1Same: (await caText()) === t1 });
  });

  await step("S15 safety", async () => {
    rec("S15 docs/architecture/ unchanged byte for byte through every PR B2a step", archHash() === archBefore);
  });
}

/** Keep the Feature Designer log of this VS Code session in the evidence folder (the profile is replaced on relaunch). */
async function saveLog() {
  const logs = path.join(RUN, "user", "logs");
  const found = [];
  const walk = (d) => { for (const n of fs.existsSync(d) ? fs.readdirSync(d) : []) { const q = path.join(d, n); if (fs.statSync(q).isDirectory()) walk(q); else if (n.endsWith("Feature Designer.log")) found.push(q); } };
  walk(logs);
  for (const q of found) fs.appendFileSync(path.join(EV, "feature-designer.log"), `==== ${q}\n${fs.readFileSync(q, "utf8")}\n`);
}
// ---------------------------------------------------------------------------------------- PR B2b-1
const { spawn } = require("child_process");
const CLOSED = [];
const TX = "designs/diagrams/.transactions";
const readWs = (rel) => fs.readFileSync(path.join(WS, rel), "utf8");
const SETUP_CLOSED = `
import json, os, sys
sys.path.insert(0, os.getcwd())
from pathlib import Path
from tools.design import designer_api
from tools.design.workspace import new_feature
root = Path(".").resolve()
out = []
for name in sys.argv[1:]:
    f = new_feature(root, name)
    text = (root / f.path).read_text(encoding="utf-8")
    lines = text.split("\\n")
    i = next(n for n, l in enumerate(lines) if l.startswith("- **Desired outcome:**"))
    while lines[i].strip():
        i += 1
    r, _ = designer_api.handle(root, {"version": 1, "op": "insert", "path": f.path, "text": text, "at": i, "diagram_id": "FD-0001-D1"})
    for e in reversed(r["edits"]):
        lines[e["start"]:e["end"]] = e["lines"]
    (root / f.path).write_bytes(r["newline"].join(lines).encode("utf-8"))
    out.append(f.path)
print(json.dumps(out))
`;
let srcLabel = 0;
/** Change the owned source's second node label (the closed documents' FD-0001-D1 blocks become out of date). */
function changeSource() {
  const p = path.join(WS, OWN_SRC), s = fs.readFileSync(p, "utf8");
  const label = `Closed ${++srcLabel}`;
  const next = s.replace(/B\["[^"]*"\]/, `B["${label}"]`);
  if (next === s) throw new Error("no B node in the source");
  fs.writeFileSync(p, next);
  return label;
}
const records = () => { try { return JSON.parse(py(["-m", "tools.design", "transaction", "status", "--json"])).records; } catch { return null; } };
async function panelFrame(kind, timeout = 20000) {
  return waitFor(async () => {
    for (const fr of app.page.frames())
      if (await fr.evaluate((k) => { const m = document.querySelector(`#main[data-kind="${k}"]`); return !!m && m.children.length > 0; }, kind).catch(() => false)) return fr;
    return null;
  }, timeout);
}
const resultOf = (pf) => waitFor(() => pf.evaluate(() => { const r = document.querySelector("#result"); return r ? `${r.className}|${r.innerText}` : ""; }), 60000);
async function clearResult(pf) { await pf.evaluate(() => { const r = document.querySelector("#result"); if (r) r.remove(); }); }
async function toast(re, ms = 15000) {
  return waitFor(async () => {
    const texts = await app.page.locator(".notification-toast .notification-list-item-message").allInnerTexts().catch(() => []);
    return texts.find((t) => re.test(t)) || "";
  }, ms);
}
async function openUpdatePanel(expectRow) {
  const row = await waitFor(async () => { const r = await stripRow("closed"); return r && (!expectRow || expectRow.test(r)) ? r : ""; }, 25000);
  await f.locator("#strip .update-closed").click();
  const pf = await panelFrame("update");
  // the panel may still show the previous list: wait for the new one (enabled Update); GUI run fix3-1, S10b
  await waitFor(() => pf.evaluate(() => { const b = document.querySelector(".confirm-update"); return !!b && !b.disabled; }), 15000);
  return { row, pf };
}
const listedIn = (pf) => pf.evaluate(() => [...document.querySelectorAll("table.docs tbody tr td:first-child")].map((td) => td.textContent));
const notIncluded = (pf) => pf.evaluate(() => [...document.querySelectorAll("ul.excluded li")].map((li) => li.textContent));
/** `index` on disk, with the open document saved first (never written under an unsaved buffer). */
async function indexNow() { if ((await doc(CA)) && (await doc(CA)).isDirty) { await app.host("save", { path: CA }); await sleep(600); } py(["-m", "tools.design", "index"]); await sleep(600); }
async function backToDesigner() {                          // condition analysis's view in front (a panel may cover it)
  await app.host("openWith", { path: CA, viewType: "featureDesigner.editor", column: 1 }); await sleep(400);
  f = await designerFrame(app.page);
}
async function crashUpdate(point) {
  await app.host("designerCall", { fn: "setDesignFault", args: [point, "$root"] });
  try {
    changeSource();
    const { pf } = await openUpdatePanel();
    await clearResult(pf);
    await pf.locator(".confirm-update").click();
    const r = await resultOf(pf);
    await pf.locator(".cancel").click(); await sleep(300);
    return r;
  } finally { await app.host("designerCall", { fn: "setDesignFault", args: [""] }); }
}

async function prB2b1Steps() {
  const archBefore = archHash();
  await step("B2b-1 setup", async () => {
    if ((await doc(CA)) && (await doc(CA)).isDirty) await app.host("save", { path: CA });
    await app.host("closeAll"); await dialogDismissIfAny();
    if ((await app.host("tabs")).length) { await app.host("revert", { path: FEATURE }); await app.host("revert", { path: CA }); await app.host("closeAll"); await dialogDismissIfAny(); }
    const script = path.join(RUN, "setup-closed.py");
    fs.writeFileSync(script, SETUP_CLOSED);
    const out = py([script, "Closed one", "Closed two", "Closed three"]);
    CLOSED.push(...JSON.parse(out.trim().split(/\r?\n/).pop()));
    py(["-m", "tools.design", "index"]);
    await openCa();
    const ok = CLOSED.length === 3 && CLOSED.every((c) => markerAt(readWs(c).split(/\r?\n/), "FD-0001-D1") > 0) && (records() || []).length === 0;
    rec("B2b-1 setup: three closed feature documents with a block of FD-0001-D1, all current; condition analysis open in Feature Designer", ok, CLOSED);
  });

  await step("S10 update closed documents", async () => {
    const caDisk = readWs(CA);
    const label = changeSource();
    const { row, pf } = await openUpdatePanel(/3 other documents/);
    const listed = await listedIn(pf), skipped = await notIncluded(pf);
    await snap("b2b1-update-panel");
    await pf.locator(".confirm-update").click();
    const result = await resultOf(pf);
    await snap("b2b1-updated");
    const after = CLOSED.map(readWs);
    rec("S10 the strip offers the closed documents; Update lists each one and writes all of them (one update); the open document is left to the editor; no record is left",
        /3 other documents \(not open\) have out-of-date diagrams/.test(row || "") && JSON.stringify([...listed].sort()) === JSON.stringify([...CLOSED].sort()) &&
        (markerAt(caDisk.split(/\r?\n/), "FD-0001-D1") < 0 || skipped.some((s) => s.startsWith(CA) && /open in this window/.test(s))) && /result ok/.test(result || "") &&
        after.every((t) => t.includes(`B["${label}"]`)) && readWs(CA) === caDisk && (records() || [1]).length === 0,
        { row: (row || "").slice(0, 100), listed, skipped, result: (result || "").slice(0, 120) });
    await pf.locator(".cancel").click(); await sleep(500);
  });

  await step("S10b a document changed between listing and confirming: nothing is written", async () => {
    await backToDesigner();
    const label = changeSource();
    // The source change makes B2a recount the closed documents a moment later, which redraws an open
    // panel in place. Wait for that recount (the strip shows the new count) before opening the panel,
    // so the hand edit below lands after the list is final (found in GUI runs: a redraw after the edit
    // showed the new list, which was then rightly updated).
    const { pf } = await openUpdatePanel(/3 other documents/);
    // The hand edit itself is a change on disk, so the panel is redrawn with the new list a moment later
    // (correct: Confirm then updates exactly what is shown; found in the pre-PR GUI run). To test a list
    // that changed *before* Confirm, the button of the list shown before the edit is tagged and clicked
    // inside the panel in one step, only if no redraw replaced it; otherwise the attempt is repeated.
    let before = [], edited = "", result = "", how = "";
    for (let attempt = 0; attempt < 5 && how !== "clicked"; attempt++) {
      await sleep(800);                                                        // a pending redraw settles first
      await waitFor(() => pf.evaluate(() => { const b = document.querySelector(".confirm-update"); return !!b && !b.disabled; }), 15000);
      await pf.evaluate(() => { document.querySelector(".confirm-update").dataset.listedBeforeEdit = "1"; });
      before = CLOSED.map(readWs);
      fs.appendFileSync(path.join(WS, CLOSED[0]), "\nA hand edit made after the list was shown.\n");
      edited = readWs(CLOSED[0]);
      how = await pf.evaluate(() => {
        const b = document.querySelector(".confirm-update");
        if (!b || b.dataset.listedBeforeEdit !== "1" || b.disabled) return "redrawn";
        b.click();
        return "clicked";
      });
    }
    if (how === "clicked") result = await resultOf(pf);
    const unchanged = readWs(CLOSED[0]) === edited && readWs(CLOSED[1]) === before[1] && readWs(CLOSED[2]) === before[2];
    await clearResult(pf);
    await waitFor(() => pf.evaluate(() => { const b = document.querySelector(".confirm-update"); return b && !b.disabled; }), 10000);
    await pf.locator(".confirm-update").click();                              // the new list, confirmed again
    const again = await resultOf(pf);
    rec("S10b a document changed after the list was shown: nothing is written and the new list is shown; confirming it updates every document and keeps the hand edit",
        /result fail/.test(result || "") && /changed since the list was shown/.test(result || "") && unchanged &&
        /result ok/.test(again || "") && CLOSED.every((c) => readWs(c).includes(`B["${label}"]`)) && readWs(CLOSED[0]).includes("A hand edit made after"),
        { result: (result || "").slice(0, 140), again: (again || "").slice(0, 80) });
    await pf.locator(".cancel").click(); await sleep(500);
  });

  await step("S10c a document open in this window is updated in the editor, not on disk", async () => {
    await backToDesigner();
    await app.host("openText", { path: CLOSED[1], column: 2 }); await sleep(800);
    await backToDesigner();
    const disk1 = readWs(CLOSED[1]);
    const label = changeSource();
    const { pf } = await openUpdatePanel(/2 other documents/);
    const listed = await listedIn(pf), skipped = await notIncluded(pf);
    await pf.locator(".confirm-update").click();
    const result = await resultOf(pf);
    rec("S10c a document open in a text editor tab of this window is not included (disk unchanged); the others are updated",
        JSON.stringify(listed.sort()) === JSON.stringify([CLOSED[0], CLOSED[2]].sort()) && skipped.some((s) => s.startsWith(CLOSED[1]) && /open in this window/.test(s)) &&
        /result ok/.test(result || "") && readWs(CLOSED[1]) === disk1 && readWs(CLOSED[0]).includes(`B["${label}"]`) && readWs(CLOSED[2]).includes(`B["${label}"]`),
        { listed, skipped, result: (result || "").slice(0, 300), disk1Same: readWs(CLOSED[1]) === disk1, label,
          c0: readWs(CLOSED[0]).includes(`B["${label}"]`), c2: readWs(CLOSED[2]).includes(`B["${label}"]`) });
    await pf.locator(".cancel").click(); await sleep(400);
    await indexNow();                                                         // bring the one left out up to date again
    await openCa();
  });

  await step("S14 the registry lock held by a command-line command", async () => {
    const holder = spawn(PY, ["-B", "-c", "import sys\nfrom pathlib import Path\nfrom tools.design import registry\nwith registry.lock(Path(sys.argv[1])):\n print('held', flush=True)\n sys.stdin.read()", WS],
                         { cwd: WS, stdio: ["pipe", "pipe", "ignore"] });
    try {
      await new Promise((res, rej) => { holder.stdout.once("data", res); setTimeout(() => rej(new Error("the lock holder did not start")), 15000); });
      const label = changeSource();
      const { pf } = await openUpdatePanel();
      const before = CLOSED.map(readWs);
      await pf.locator(".confirm-update").click();
      const result = await resultOf(pf);
      const unchanged = CLOSED.every((c, i) => readWs(c) === before[i]);
      holder.stdin.end();
      await new Promise((res) => holder.once("exit", res));
      await clearResult(pf);
      await waitFor(() => pf.evaluate(() => { const b = document.querySelector(".confirm-update"); return b && !b.disabled; }), 10000);
      await pf.locator(".confirm-update").click();
      const again = await resultOf(pf);
      rec("S14 while another diagram command holds the registry lock the update is refused (E12) and nothing is written; afterwards it succeeds",
          /result fail/.test(result || "") && /E12/.test(result || "") && unchanged && /result ok/.test(again || "") && CLOSED.every((c) => readWs(c).includes(`B["${label}"]`)),
          { result: (result || "").slice(0, 140) });
      await pf.locator(".cancel").click(); await sleep(400);
    } finally { try { holder.kill(); } catch { /* ended */ } }
  });

  await step("S14b a document another Feature Designer window has open is never written", async () => {
    await backToDesigner();
    const dir = path.join(WS, TX, "windows"), other = path.join(dir, "00000000000000ab.json");
    // a live process on this computer (this test runner): the extension removes the records of ended processes
    const beat = () => fs.writeFileSync(other, JSON.stringify({ format: "feature-designer-window", version: 1, window: "00000000000000ab", pid: process.pid,
      host: require("os").hostname(), platform: process.platform, heartbeat: Date.now() / 1000, documents: [{ path: CLOSED[2], dirty: true }] }));
    beat(); const keep = setInterval(beat, 3000);
    try {
      const disk2 = readWs(CLOSED[2]);
      const label = changeSource();
      const { row, pf } = await openUpdatePanel(/1 more is open in another window/);
      const skipped = await notIncluded(pf);
      await pf.locator(".confirm-update").click();
      const result = await resultOf(pf);
      rec("S14b a document listed as open (unsaved) by another window is excluded and never written; the strip says it is updated there",
          skipped.some((s) => s.startsWith(CLOSED[2]) && s.includes(`VS Code window (process ${process.pid}) with unsaved changes`)) && /result ok/.test(result || "") &&
          readWs(CLOSED[2]) === disk2 && readWs(CLOSED[0]).includes(`B["${label}"]`), { row: (row || "").slice(0, 120), skipped, result: (result || "").slice(0, 300),
          disk2Same: readWs(CLOSED[2]) === disk2, c0: readWs(CLOSED[0]).includes(`B["${label}"]`) });
      await pf.locator(".cancel").click(); await sleep(400);
    } finally { clearInterval(keep); fs.rmSync(other, { force: true }); }
    await indexNow();
  });

  await step("S14c a window that stopped responding keeps protecting its documents; an ended window's record is removed", async () => {
    // pre-merge review: a suspended or hung window (process running, heartbeat old) may hold unsaved changes
    await backToDesigner();
    const dir = path.join(WS, TX, "windows"), hung = path.join(dir, "00000000000000ac.json"), ended = path.join(dir, "00000000000000ad.json");
    const old = Date.now() / 1000 - 600;
    const write = (file, id, pid, doc) => {
      fs.writeFileSync(file, JSON.stringify({ format: "feature-designer-window", version: 1, window: id, pid,
        host: require("os").hostname(), platform: process.platform, heartbeat: old, documents: [{ path: doc, dirty: true }] }));
      fs.utimesSync(file, new Date(old * 1000), new Date(old * 1000));
    };
    write(hung, "00000000000000ac", process.pid, CLOSED[2]);        // this test runner: running, but silent for 10 min
    write(ended, "00000000000000ad", 999999, CLOSED[1]);            // no such process: its record is swept
    try {
      const disk2 = readWs(CLOSED[2]);
      const label = changeSource();
      const { row, pf } = await openUpdatePanel(/1 more is open in another window/);
      const skipped = await notIncluded(pf);
      await pf.locator(".confirm-update").click();
      const result = await resultOf(pf);
      rec("S14c the silent window's document is excluded (not responding) and never written; the ended window's record is removed and its document updated",
          skipped.some((s) => s.startsWith(CLOSED[2]) && /has not responded for 10 min/.test(s)) && /result ok/.test(result || "") &&
          readWs(CLOSED[2]) === disk2 && readWs(CLOSED[1]).includes(`B["${label}"]`) && !fs.existsSync(ended) && fs.existsSync(hung),
          { row: (row || "").slice(0, 120), skipped, result: (result || "").slice(0, 300), disk2Same: readWs(CLOSED[2]) === disk2,
            c1: readWs(CLOSED[1]).includes(`B["${label}"]`), endedGone: !fs.existsSync(ended), hungKept: fs.existsSync(hung) });
      await pf.locator(".cancel").click(); await sleep(400);
    } finally { fs.rmSync(hung, { force: true }); fs.rmSync(ended, { force: true }); }
    await indexNow();
  });

  await step("S16 an update interrupted part-way: explicit recovery, nothing preselected", async () => {
    await backToDesigner();
    const before = CLOSED.map(readWs);
    const result = await crashUpdate("after-replace:1");
    const recs = records() || [];
    const offer = await toast(/update of closed feature documents was interrupted/);
    await snap("b2b1-interrupted");
    await app.host("command", { id: "notifications.clearAll" }); await sleep(800);    // dismissing keeps the record (D8)
    const kept = (records() || []).length === 1;
    // requirement 10: a document held by the record is not refreshed, even clean and open only in Feature Designer
    const heldDoc = recs.length ? recs[0].files.find((x) => x.state === "original").path : CLOSED[1];
    await app.host("openWith", { path: heldDoc, viewType: "featureDesigner.editor", column: 2 });
    const fh = await waitFor(async () => {                                        // the view of that document (not condition analysis)
      for (const fr of app.page.frames()) if (await fr.evaluate((r) => !!window.FD_DEBUG && window.FD_DEBUG.state.rel === r, heldDoc).catch(() => false)) return fr;
      return null;
    }, 20000);
    f = fh;
    const heldRow = await waitFor(() => stripRow("held"), 15000);
    const noRefreshNow = await f.evaluate(() => !document.querySelector("#strip .refresh-now"));
    await app.host("command", { id: "featureDesigner.checkSources" });           // a sync that would refresh a clean document
    await sleep(2500);
    const notRefreshed = (await doc(heldDoc)).text === readWs(heldDoc) && !(await doc(heldDoc)).isDirty;
    await snap("b2b1-held");
    await app.host("command", { id: "featureDesigner.resolveUpdate" });
    let pf = await panelFrame("recovery");
    await waitFor(() => pf.evaluate(() => !!document.querySelector(".record")), 10000);
    const blockedOpen = await pf.evaluate(() => !!document.querySelector(".choice-complete") && document.querySelector(".choice-complete").disabled &&
                                                /close .* first/.test(document.querySelector(".decide").innerText));
    await pf.locator(".cancel").last().click(); await sleep(300);
    await openCa();                                                               // the held document is closed again
    await sleep(1500);                                                            // this window's open-document list is published
    await app.host("command", { id: "featureDesigner.resolveUpdate" });
    pf = await panelFrame("recovery");
    await waitFor(() => pf.evaluate(() => !!document.querySelector(".record") && !document.querySelector(".choice-complete").disabled), 15000);
    const ui = await pf.evaluate(() => ({ checked: [...document.querySelectorAll('input[type="radio"]')].filter((x) => x.checked).length,
      confirmDisabled: document.querySelector(".confirm").disabled, states: [...document.querySelectorAll("table.files tbody tr td:last-child")].map((td) => td.textContent),
      ackDisabled: document.querySelector(".abandon-ack").disabled }));
    await snap("b2b1-recovery-panel");
    await pf.locator(".choice-complete").check();
    const label = await pf.evaluate(() => ({ text: document.querySelector(".confirm").textContent, disabled: document.querySelector(".confirm").disabled }));
    await pf.locator(".confirm").click();
    const done = await resultOf(pf);
    const known = before.map((b, i) => readWs(CLOSED[i]));
    rec("S16 interrupted update: reported as such; dismissing the notification keeps the record; a held document is not refreshed; recovery is refused while one of its documents is open",
        /result fail/.test(result || "") && recs.length === 1 && !!offer && kept && /interrupted update of closed documents/.test(heldRow || "") && noRefreshNow && notRefreshed && blockedOpen,
        { result: (result || "").slice(0, 100), files: recs.length && recs[0].files.map((x) => x.state), offer: (offer || "").slice(0, 80),
          kept, heldRow: (heldRow || "").slice(0, 80), noRefreshNow, notRefreshed, blockedOpen });
    rec("S16b the recovery panel shows every file's state with nothing selected; Confirm stays disabled until an action is chosen; Complete finishes the update and removes the record",
        ui.checked === 0 && ui.confirmDisabled && ui.ackDisabled && ui.states.filter((s) => /^Updated/.test(s)).length === 1 && ui.states.filter((s) => /^Not updated/.test(s)).length === 2 &&
        label.text === "Complete the update" && !label.disabled && /result ok/.test(done || "") && (records() || [1]).length === 0 &&
        known.every((t) => t.includes(`B["Closed ${srcLabel}"]`)), { ui, done: (done || "").slice(0, 80) });
    await pf.locator(".cancel").last().click(); await sleep(400);
  });

  await step("S17 a corrupted record: never used, only an informed Abandon", async () => {
    await backToDesigner();
    await crashUpdate("after-replace:2");
    const recs = records() || [];
    const now = CLOSED.map(readWs);
    const jp = path.join(WS, TX, recs[0].id, "journal.json");
    const damaged = fs.readFileSync(jp, "utf8").replace('"state": "committing"', '"state": "prepared"');
    if (!damaged.includes('"state": "prepared"')) throw new Error("the record has no committing state to damage");
    fs.writeFileSync(jp, damaged);                                                // damaged: the checksum no longer matches
    await app.host("command", { id: "notifications.clearAll" });
    await app.host("command", { id: "featureDesigner.resolveUpdate" });
    const pf = await panelFrame("recovery");
    await waitFor(() => pf.evaluate(() => /cannot be trusted/.test(document.body.innerText)), 15000);
    const ui = await pf.evaluate(() => ({ complete: document.querySelector(".choice-complete").disabled, undo: document.querySelector(".choice-undo").disabled,
                                         abandon: document.querySelector(".choice-abandon").disabled }));
    await pf.locator(".choice-abandon").check();
    const beforeAck = await pf.evaluate(() => document.querySelector(".confirm").disabled);
    await pf.locator(".abandon-ack").check();
    const afterAck = await pf.evaluate(() => document.querySelector(".confirm").disabled);
    await snap("b2b1-corrupt-abandon");
    py(["-m", "tools.design", "registry", "unlock", "--confirm"]);                 // the ended update's lock, as a person would
    const blocked = py(["-m", "tools.design", "index"]);
    await pf.locator(".confirm").click();
    const done = await resultOf(pf);
    rec("S17 a damaged record cannot be completed or undone; every writer refuses meanwhile; Abandon needs its own acknowledgement and changes no document",
        ui.complete && ui.undo && !ui.abandon && beforeAck && !afterAck && /cannot be read/.test(blocked) && /result ok/.test(done || "") &&
        (records() || [1]).length === 0 && CLOSED.every((c, i) => readWs(c) === now[i]), { ui, blocked: blocked.trim().slice(0, 120) });
    await pf.locator(".cancel").last().click(); await sleep(400);
    await indexNow();
  });

  await step("S16c restart recovery: an update interrupted by ending VS Code is offered at the next start; Undo restores every original", async () => {
    await backToDesigner();
    const before = CLOSED.map(readWs);
    await app.host("designerCall", { fn: "setDesignFault", args: ["after-replace:2", "$root", "sleep"] });   // waits there
    changeSource();
    const { pf } = await openUpdatePanel();
    const can = await waitFor(() => pf.evaluate(() => { const b = document.querySelector(".confirm-update"); return b && !b.disabled; }), 15000);
    if (!can) console.log(`DEBUG S16c update panel: ${(await pf.evaluate(() => document.body.innerText)).slice(0, 800).replace(/\n/g, " | ")}`);
    await pf.locator(".confirm-update").click();
    const running = await waitFor(() => { const r = records(); return r && r.length && r[0].live ? r : null; }, 30000);
    await saveLog();
    await close(app); app = null;                                                  // VS Code ended hard, with the update in flight
    for (const line of execFileSync("powershell", ["-NoProfile", "-Command",       // and the update process with it
      "(Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | Where-Object { $_.CommandLine -like '*refresh-blocks*' }).ProcessId"], { encoding: "utf8" }).split(/\s+/).filter(Boolean))
      try { process.kill(Number(line)); } catch { /* gone */ }
    await sleep(1500);
    const mid = CLOSED.map(readWs);
    app = await launch({ trust: false, markSharp: true });
    await app.host("setGlobal", { section: "featureDesigner", key: "pythonPath", value: PY });
    const offer = await toast(/update of closed feature documents was interrupted/, 30000);
    await snap("b2b1-after-restart");
    const review = app.page.locator(".notification-toast .monaco-button").filter({ hasText: "Review" }).first();
    const clicked = await review.click({ timeout: 10000 }).then(() => true, () => false);
    if (!clicked) { console.log(`DEBUG S16c toast buttons: ${await app.page.locator(".notifications-toasts").innerHTML().catch(() => "").then((h) => h.slice(0, 800))}`);
                    await app.host("command", { id: "featureDesigner.resolveUpdate" }); }
    const rf = await panelFrame("recovery");
    await waitFor(() => rf.evaluate(() => !!document.querySelector(".record") && !document.querySelector(".choice-undo").disabled), 20000);
    const checked = await rf.evaluate(() => [...document.querySelectorAll('input[type="radio"]')].filter((x) => x.checked).length);
    await rf.locator(".choice-undo").check();
    await rf.locator(".confirm").click();
    const done = await resultOf(rf);
    rec("S16c the update was running when VS Code ended; after the restart the interrupted update is offered; nothing is preselected; Undo restores every original exactly",
        !!running && clicked && mid.every((t, i) => t === before[i] || t.includes("Closed ")) && !!offer && checked === 0 && /result ok/.test(done || "") &&
        CLOSED.every((c, i) => readWs(c) === before[i]) && (records() || [1]).length === 0, { offer: (offer || "").slice(0, 80), done: (done || "").slice(0, 80), running: !!running, clicked, checked, midOk: mid.every((t, i) => t === before[i] || t.includes("Closed ")) });
    await rf.locator(".cancel").last().click(); await sleep(300);
    await app.host("designerCall", { fn: "setDesignFault", args: [""] });
  });

  await step("S15b safety", async () => {
    rec("S15b docs/architecture/ unchanged byte for byte through every PR B2b-1 step", archHash() === archBefore);
  });
}

async function dialogDismissIfAny() {                       // "save changes?" prompts on close: keep the buffer
  await sleep(500);
  const dlg = app.page.locator(".monaco-dialog-box");
  if (await dlg.count()) {
    const cancel = dlg.locator(".monaco-button").filter({ hasText: /^Cancel$/ });   // never "Don't Save": that would discard the buffer
    if (await cancel.count()) await cancel.first().click();
  }
}

// ---------------------------------------------------------------------------------------- PR B2b-2b
// Renames of diagram sources through VS Code (the Explorer, and the workspace rename API that runs the same
// will/did-rename participants): one modal prompt per batch with Not now first (focused), the four choices, the
// E6 strip row, Move back, the architecture notice, held paths, ambiguity, and move records in the recovery panel.
const B2 = {};
const REGISTRY_YML = "designs/diagrams/registry.yml";
const SETUP_B2B2B = `
import json, os, sys
sys.path.insert(0, os.getcwd())
from pathlib import Path
from tools.design import designer_api, ownership
from tools.design.workspace import new_feature
root = Path(".").resolve()
def place(doc, did):
    text = (root / doc).read_bytes().decode("utf-8")
    lines = text.split("\\n")
    i = next(n for n, l in enumerate(lines) if l.startswith("- **Desired outcome:**"))
    while lines[i].strip():
        i += 1
    r, code = designer_api.handle(root, {"version": 1, "op": "insert", "path": doc, "text": text, "at": i, "diagram_id": did})
    assert code == 0, r
    for e in reversed(r["edits"]):
        lines[e["start"]:e["end"]] = e["lines"]
    (root / doc).write_bytes(r["newline"].join(lines).encode("utf-8"))
out = {}
for key, title in (("r1", "Rename one"), ("r2", "Rename two"), ("r3", "Rename three")):
    d = ownership.new_diagram(root, "FD-0001", title, "process")
    out[key] = {"id": d.diagram_id, "path": d.path}
parent = new_feature(root, "Rename parent")
child = new_feature(root, "Rename child", parent=parent.feature_id, convert_parent=True)
out["folder"] = [ownership.new_diagram(root, child.feature_id, f"Folder {n}", "process").path for n in "abcdef"]
out["folder_ids"] = []
for key, name in (("open", "Rename open"), ("dirty", "Rename dirty"), ("closed", "Rename closed")):
    out[key] = new_feature(root, name).path
    place(out[key], out["r1"]["id"])
from tools.design import registry
reg = registry.load(root)
out["folder_ids"] = [e.diagram_id for e in reg.entries if e.path in out["folder"]]
place(out["open"], out["folder_ids"][0])
out["parent"] = posix = Path(out["folder"][0]).parent.parent.as_posix()
print(json.dumps(out))
`;
const reg = () => readWs(REGISTRY_YML);
const pathOf = (id) => { const r = JSON.parse(py(["-m", "tools.design", "resolve", id])); return r.path; };
const exists = (rel) => { const p = path.join(WS, ...rel.split("/")); try { return fs.readdirSync(path.dirname(p)).includes(path.basename(p)); } catch { return false; } };
const moveFs = (a, b) => { fs.mkdirSync(path.dirname(path.join(WS, b)), { recursive: true }); fs.renameSync(path.join(WS, a), path.join(WS, b)); };
function fdLog() {
  const found = [];
  const walk = (d) => { for (const n of fs.existsSync(d) ? fs.readdirSync(d) : []) { const q = path.join(d, n); if (fs.statSync(q).isDirectory()) walk(q); else if (n.endsWith("Feature Designer.log")) found.push(q); } };
  walk(path.join(RUN, "user", "logs"));
  return found.map((q) => fs.readFileSync(q, "utf8")).join("\n");
}
/** The modal prompt (VS Code's custom dialog): message, detail, buttons in order and the focused one. */
async function prompt(timeout = 25000) {
  const box = app.page.locator(".monaco-dialog-box");
  await box.waitFor({ timeout });
  // earlier notifications are cleared now, so a later toast() wait sees only the outcome of this prompt
  await app.host("command", { id: "notifications.clearAll" });
  await sleep(400);
  return app.page.evaluate(() => {
    const b = document.querySelector(".monaco-dialog-box");
    const q = (s) => (b.querySelector(s) || {}).innerText || "";
    const buttons = [...b.querySelectorAll(".dialog-buttons .monaco-button")].map((x) => x.innerText.trim());
    const a = document.activeElement;
    return { message: q(".dialog-message-text"), detail: q(".dialog-message-detail"), buttons,
             focused: a && b.contains(a) ? (a.innerText || a.textContent || "").trim() : "(outside the dialog)" };
  });
}
const noPrompt = async (ms = 4000) => !(await waitFor(async () => (await app.page.locator(".monaco-dialog-box").count()) > 0, ms, 200));
async function frameFor(rel, timeout = 20000) {
  return waitFor(async () => {
    for (const fr of app.page.frames()) if (await fr.evaluate((r) => !!window.FD_DEBUG && window.FD_DEBUG.state.rel === r, rel).catch(() => false)) return fr;
    return null;
  }, timeout);
}
async function openB2(rel, column = 1) {
  await app.host("openWith", { path: rel, viewType: "featureDesigner.editor", column });
  const fr = await frameFor(rel);
  if (!fr) throw new Error(`Feature Designer did not open ${rel}`);
  await waitFor(() => fr.evaluate(() => !!document.querySelector("h1")), 15000);
  return fr;
}
const rowIn = (fr, cls) => fr.evaluate((c) => { const r = document.querySelector(`#strip .strip-row.${c}`); return r ? r.innerText : ""; }, cls).catch(() => "");
const plainRegistry = (t) => t.replace(/\r\n/g, "\n");
/** Run the design tooling with a crash injection point (the process ends there, as in a power cut). */
function pyFault(args, point) {
  const env = { ...process.env, DESIGN_TEST_FAULT: point, DESIGN_TEST_FAULT_ROOT: WS };
  try { return execFileSync(PY, ["-B", "-m", "tools.design", ...args, "--root", WS], { cwd: WS, encoding: "utf8", env }); }
  catch (e) { return `exit ${e.status} ${e.stdout || ""}${e.stderr || ""}`; }
}

async function prB2b2bSteps() {
  const archBefore = archHash();
  let fo = null, fd = null;                                     // the open (clean) and the dirty document's views
  await step("B2b-2b setup", async () => {
    await app.host("closeAll"); await dialogDismissIfAny();
    for (const t of await app.host("tabs")) if (t.dirty) { await app.host("closeAll"); await dialogDismissIfAny(); }
    const script = path.join(RUN, "setup-b2b2b.py");
    fs.writeFileSync(script, SETUP_B2B2B);
    Object.assign(B2, JSON.parse(py([script]).trim().split(/\r?\n/).pop()));
    py(["-m", "tools.design", "index"]);
    fo = await openB2(B2.open, 1);
    fd = await openB2(B2.dirty, 2);
    await app.host("replace", { path: B2.dirty, find: "## 1. Objective", replace: "## 1. Objective\n\nTyped here, never saved by Feature Designer." });
    B2.dirtyDisk = readWs(B2.dirty);
    await sleep(1500);                                           // presence published; the E6 row computed
    rec("B2b-2b setup: three sources, a folder with six, an open (clean), an open (unsaved) and a closed document referencing them",
        !!B2.r1 && B2.folder.length === 6 && (await doc(B2.dirty)).isDirty && !(await doc(B2.open)).isDirty && (records() || [1]).length === 0,
        { r1: B2.r1, parent: B2.parent });
  });

  await step("R-A1 one source renamed in the Explorer: one prompt, Update the registry", async () => {
    const old = B2.r1.path, now = old.replace(/\.md$/, "-renamed.md");
    const regBefore = reg(), openDisk = readWs(B2.open), closedDisk = readWs(B2.closed), dirtyBuf = (await doc(B2.dirty)).text;
    await app.host("reveal", { path: old }); await sleep(1200);
    await app.page.keyboard.press("F2"); await sleep(600);
    await app.page.keyboard.press("Control+A");
    await app.page.keyboard.type(path.basename(now)); await app.page.keyboard.press("Enter");
    const p = await prompt();
    await snap("b2b2b-prompt-single");
    await dialogButton("Update the registry");
    const done = await toast(/Registry updated:/, 20000);
    const regAfter = reg();
    const refreshed = await waitFor(async () => { const d = await doc(B2.open); return d && d.isDirty && d.text.includes(path.basename(now)) ? d : null; }, 20000);
    const manual = await waitFor(() => rowIn(fd, "manual").then((t) => (/unsaved changes/.test(t) ? t : "")), 15000);
    await snap("b2b2b-after-registry");
    rec("R-A1 an Explorer rename gives one modal prompt: Not now first and focused, then Update the registry, Update the registry and 1 closed document, Move the files back; it lists the ID old → new and the documents",
        p.message === "1 diagram source was renamed: the registry still names the old path" && p.focused === "Not now" &&
        JSON.stringify(p.buttons.slice(0, 4)) === JSON.stringify(["Not now", "Update the registry", "Update the registry and 1 closed document", "Move the files back"]) &&
        p.detail.includes(`${B2.r1.id} "Rename one": ${old} → ${now}`) && p.detail.includes(B2.closed) && p.detail.includes(B2.open),
        { message: p.message, buttons: p.buttons, focused: p.focused, detail: p.detail.slice(0, 400) });
    rec("R-A1 Update the registry changes only the path (the registry is byte-identical otherwise: ID, owner, title, category); the diagram index is reported regenerated",
        plainRegistry(regAfter) === plainRegistry(regBefore).replace(`path: ${old}\n`, `path: ${now}\n`) && regAfter !== regBefore &&
        /diagram-index\.md was regenerated/.test(done || ""), { toast: (done || "").slice(0, 200) });
    rec("R-A1 the clean open document is refreshed by B2a (one edit, not saved); the unsaved one is not, with a notice; nothing is written to either or to the closed document",
        !!refreshed && readWs(B2.open) === openDisk && (await doc(B2.dirty)).text === dirtyBuf && readWs(B2.dirty) === B2.dirtyDisk &&
        !!manual && readWs(B2.closed) === closedDisk, { manual: (manual || "").slice(0, 120) });
    B2.r1.path = now;
    await app.host("save", { path: B2.open }); await sleep(500);
  });

  await step("R-A1b Update the registry and closed documents: the Update Closed Documents confirmation", async () => {
    const old = B2.r1.path, now = old.replace(/-renamed\.md$/, "-again.md");
    await app.host("rename", { pairs: [[old, now]] });
    const p = await prompt();
    await dialogButton("Update the registry and 1 closed document");
    const pf = await panelFrame("update");
    await waitFor(() => pf.evaluate(() => { const b = document.querySelector(".confirm-update"); return !!b && !b.disabled; }), 20000);
    const listed = await listedIn(pf), skipped = await notIncluded(pf);
    const beforeConfirm = readWs(B2.closed);
    await snap("b2b2b-update-closed");
    await pf.locator(".confirm-update").click();
    const r = await resultOf(pf);
    rec("R-A1b the closed document is written only after its own confirmation (listed first); the unsaved open document is left out and never written",
        p.buttons.includes("Update the registry and 1 closed document") && pathOf(B2.r1.id) === now && listed.includes(B2.closed) &&
        !beforeConfirm.includes(path.basename(now)) && /result ok/.test(r || "") && readWs(B2.closed).includes(path.basename(now)) &&
        skipped.some((s) => s.startsWith(B2.dirty)) && readWs(B2.dirty) === B2.dirtyDisk, { listed, skipped, r: (r || "").slice(0, 100) });
    await pf.locator(".cancel").click(); await sleep(400);
    B2.r1.path = now;
    await app.host("save", { path: B2.open }).catch(() => {}); await sleep(400);
  });

  await step("R-A2 a feature folder with six sources renamed: one prompt, one record, the storm summary (C5)", async () => {
    const from = B2.parent, to = B2.parent.replace(/rename-parent$/, "renamed-parent");
    const regBefore = reg(), logBefore = fdLog().length;
    if ((await doc(B2.open)).isDirty) { await app.host("save", { path: B2.open }); await sleep(600); }
    fo = await openB2(B2.open, 1);
    await app.host("rename", { pairs: [[from, to]] });
    const p = await prompt();
    const prompts = await app.page.locator(".monaco-dialog-box").count();
    await snap("b2b2b-prompt-folder");
    await dialogButton("Update the registry");
    await toast(/Registry updated:/, 30000);
    const moved = B2.folder_ids.map(pathOf);
    const want = B2.folder.map((x) => to + x.slice(from.length));
    let expected = plainRegistry(regBefore);
    B2.folder.forEach((x, i) => { expected = expected.replace(`path: ${x}\n`, `path: ${want[i]}\n`); });
    const storm = await waitFor(() => rowIn(fo, "manual").then((t) => (/Many diagram sources changed at once/.test(t) ? t : "")), 15000);
    const log = fdLog().slice(logBefore);
    const txs = [...log.matchAll(/\[renames\] (tx-\S+): adopt/g)].map((m) => m[1]);
    rec("R-A2 one prompt for the whole folder lists six sources; Update the registry adopts all six in one record; only their paths change",
        prompts === 1 && /^6 diagram sources were renamed/.test(p.message) && JSON.stringify([...moved].sort()) === JSON.stringify([...want].sort()) &&
        plainRegistry(reg()) === expected && txs.length === 1, { message: p.message, txs, prompts, moved, want, registry: plainRegistry(reg()) === expected });
    rec("R-A2 the batch counts as one event, and a batch of more than five sources gives the storm summary instead of automatic refreshes (C5)",
        !!storm && !(await doc(B2.open)).isDirty, { storm: (storm || "").slice(0, 120) });
    B2.folder = want; B2.parent = to;
  });

  await step("R-A9 Move the files back: back at the old path; the registry unchanged; no record", async () => {
    const old = B2.r1.path, now = "designs/features/elsewhere/diagrams/rename-one.md";
    const regBefore = reg(), bytes = readWs(old);
    await app.host("rename", { pairs: [[old, now]] });
    const p = await prompt();
    await dialogButton("Move the files back");
    const done = await toast(/Moved back 1 diagram source/, 20000);
    rec("R-A9 Move the files back renames the file back (recorded move), only while it is unchanged and the old path is free; the registry is byte-identical; no record is left",
        p.buttons.includes("Move the files back") && !!done && exists(old) && !exists(now) && readWs(old) === bytes && reg() === regBefore &&
        (records() || [1]).length === 0 && /The registry was not changed/.test(done || ""), { toast: (done || "").slice(0, 160) });
  });

  await step("R-A9b Not now: nothing written; the E6 row in the strip; later adoption from the row", async () => {
    const old = B2.r1.path, now = old.replace(/-again\.md$/, "-later.md");
    const regBefore = reg();
    await app.host("rename", { pairs: [[old, now]] });
    await prompt();
    await dialogButton("Not now");
    await sleep(800);
    const row = await waitFor(() => rowIn(fo, "moved").then((t) => (/1 moved source: registry not updated/.test(t) ? t : "")), 20000);
    await snap("b2b2b-e6-row");
    const untouched = reg() === regBefore && (records() || [1]).length === 0;
    await fo.locator("#strip .review-moves").click();
    const p = await prompt();
    await dialogButton("Update the registry");
    await toast(/Registry updated:/, 20000);
    const gone = await waitFor(() => rowIn(fo, "moved").then((t) => !t), 20000);
    rec("R-A9b Not now writes nothing (no record); every Feature Designer view shows \"1 moved source: registry not updated\"; Review… offers the same prompt and the adoption then clears the row",
        untouched && !!row && /is not at the registered path/.test(p.message) && pathOf(B2.r1.id) === now && !!gone &&
        !/not known here/.test(p.detail), { row, message: p.message });
    B2.r1.path = now;
  });

  await step("R-A4 a case-only rename (Windows): the registry takes the exact new case and check is clean", async () => {
    const old = B2.r1.path, base = path.posix.basename(old), now = `${path.posix.dirname(old)}/${base[0].toUpperCase()}${base.slice(1)}`;
    // In the Explorer (F2): VS Code's WorkspaceEdit.renameFile canonicalises a target that differs only in letter
    // case to the existing file on Windows, so through that API a case-only rename does nothing.
    await app.host("reveal", { path: old }); await sleep(1200);
    await app.page.keyboard.press("F2"); await sleep(600);
    await app.page.keyboard.press("Control+A");
    await app.page.keyboard.type(path.posix.basename(now)); await app.page.keyboard.press("Enter");
    const p = await prompt();
    await snap("b2b2b-case-only");
    await dialogButton("Update the registry");
    await toast(/Registry updated:/, 20000);
    const check = py(["-m", "tools.design", "check"]);
    rec("R-A4 a case-only rename (reported by VS Code with the old letter case) is shown and adopted with the exact new case; check reports no moved or missing source",
        p.detail.includes(`${old} → ${now}`) && pathOf(B2.r1.id) === now && exists(now) && !/\(E6\)|\(E7\)/.test(check),
        { check: check.trim().split("\n").slice(-2), detail: p.detail.slice(0, 300) });
    B2.r1.path = now;
  });

  await step("R-A5 collisions: VS Code refuses an occupied destination; a registered path of another diagram is refused", async () => {
    const regBefore = reg(), a = readWs(B2.r1.path), b = readWs(B2.r2.path);
    const ok = await app.host("rename", { pairs: [[B2.r1.path, B2.r2.path]] }).catch((e) => `threw: ${e.message.slice(0, 80)}`);   // an existing file: VS Code refuses
    const none = await noPrompt(3000);
    const occupied = ok !== true && none && readWs(B2.r1.path) === a && readWs(B2.r2.path) === b && reg() === regBefore;
    const away = "designs/features/away/diagrams/rename-two.md";
    moveFs(B2.r2.path, away);                                                            // r2 moved elsewhere (E6)
    await app.host("rename", { pairs: [[B2.r1.path, B2.r2.path]] });                    // onto r2's registered path
    const p = await prompt();
    await snap("b2b2b-collision");
    await dialogButton("Not now");
    const refused = !p.buttons.includes("Update the registry") && new RegExp(`is the registered path of ${B2.r2.id}`).test(p.detail) && reg() === regBefore;
    moveFs(B2.r2.path, B2.r1.path); moveFs(away, B2.r2.path);                            // put both back (outside VS Code)
    rec("R-A5 a rename onto an existing file is refused by VS Code (nothing changes, no prompt); a rename onto another diagram's registered path cannot be adopted (A5)",
        occupied && refused, { ok, none, detail: p.detail.slice(0, 300) });
  });

  await step("R-A6 docs/architecture/: the notice; the registry and docs/architecture/ unchanged", async () => {
    const regBefore = reg();
    const into = `docs/architecture/${path.posix.basename(B2.r1.path)}`;
    await app.host("rename", { pairs: [[B2.r1.path, into]] });
    const notice = await toast(/Architecture diagram sources change only through technical-lead's documentation workflow \(M1\); the registry was not changed\./, 20000);
    const p = await prompt();
    await dialogButton("Not now");
    moveFs(into, B2.r1.path);                                                           // put back outside VS Code
    const doc0 = fs.readdirSync(path.join(WS, "docs/architecture")).find((n) => n.endsWith(".md"));
    await app.host("command", { id: "notifications.clearAll" });
    await app.host("rename", { pairs: [[`docs/architecture/${doc0}`, `docs/architecture/x-${doc0}`]] });   // an architecture document
    const notice2 = await toast(/Architecture diagram sources change only through technical-lead's documentation workflow/, 20000);
    const none = await noPrompt(3000);
    moveFs(`docs/architecture/x-${doc0}`, `docs/architecture/${doc0}`);
    await sleep(800);
    rec("R-A6 a rename into docs/architecture/ or of an architecture document shows the G5 notice; nothing under docs/architecture/ is adopted or written; the registry is unchanged",
        !!notice && !p.buttons.includes("Update the registry") && !p.buttons.includes("Move the files back") && !!notice2 && none &&
        reg() === regBefore && archHash() === archBefore, { detail: p.detail.slice(0, 200) });
  });

  await step("R-G9 a path held by an unresolved move: warned; the move record in the recovery panel; Complete", async () => {
    const old = B2.r3.path, held = "designs/features/held/diagrams/rename-three.md";
    moveFs(old, held);                                                                  // moved outside VS Code
    const plan = JSON.parse(py(["-m", "tools.design", "registry", "adopt-moves", "--from", old, "--to", held, "--json"]));
    const crashed = pyFault(["registry", "adopt-moves", "--from", old, "--to", held, "--confirm", plan.token], "move-after-prepare");
    py(["-m", "tools.design", "registry", "unlock", "--confirm"]);
    await sleep(1500);
    const heldRow = await waitFor(() => rowIn(fo, "held").then((t) => (/registry move was interrupted/.test(t) ? t : "")), 20000);
    await app.host("command", { id: "notifications.clearAll" }); await sleep(500);
    await app.host("rename", { pairs: [[held, held.replace(".md", "-b.md")]] });     // VS Code cannot be stopped: warned
    const warned = await toast(/held by an unresolved record and VS Code cannot prevent the rename/, 20000);
    const none = await noPrompt(2500);
    await snap("b2b2b-held");
    moveFs(held.replace(".md", "-b.md"), held);
    await app.host("command", { id: "featureDesigner.resolveUpdate" });
    const pf = await panelFrame("recovery");
    await waitFor(() => pf.evaluate(() => /Registry move tx-/.test(document.body.innerText) && !document.querySelector(".choice-complete").disabled), 20000);
    const ui = await pf.evaluate(() => ({ text: document.body.innerText, checked: [...document.querySelectorAll('input[type="radio"]')].filter((x) => x.checked).length,
                                         confirm: document.querySelector(".confirm").disabled }));
    await snap("b2b2b-recovery-move");
    await pf.locator(".choice-complete").check();
    const label = await pf.evaluate(() => document.querySelector(".confirm").textContent);
    await pf.locator(".confirm").click();
    const done = await resultOf(pf);
    rec("R-G9 renaming a path held by an unresolved move is warned (VS Code cannot prevent it; recovery treats the path conservatively); every open document shows the interrupted move",
        /exit 97/.test(crashed) && !!heldRow && !!warned && none, { crashed: crashed.slice(0, 40), warned: (warned || "").slice(0, 200), heldRow: (heldRow || "").slice(0, 100) });
    rec("R-G9 the recovery panel shows the move record with move wording (observed renames, at the new path, registry original), nothing selected; Complete finishes it and says the index was regenerated",
        /Observed renames/.test(ui.text) && /At the new path/.test(ui.text) && /Registry: the original \(not updated\)/.test(ui.text) &&
        ui.checked === 0 && ui.confirm && label === "Complete the move" && /result ok/.test(done || "") && /diagram-index\.md was regenerated/.test(done || "") &&
        pathOf(B2.r3.id) === held && (records() || [1]).length === 0, { done: (done || "").slice(0, 200) });
    await pf.locator(".cancel").last().click(); await sleep(400);
    B2.r3.path = held;
  });

  await step("R-A8 an ambiguous identity (copies at two paths): reported with the candidates, never adopted", async () => {
    const src = B2.r1.path, a = "designs/features/copy-a/diagrams/one.md", b = "designs/features/copy-b/diagrams/one.md";
    for (const x of [a, b]) { fs.mkdirSync(path.dirname(path.join(WS, x)), { recursive: true }); fs.copyFileSync(path.join(WS, src), path.join(WS, x)); }
    fs.unlinkSync(path.join(WS, src));
    const regBefore = reg();
    const row = await waitFor(() => rowIn(fo, "moved").then((t) => (/found at several paths \(never guessed\)/.test(t) ? t : "")), 20000);
    await fo.locator("#strip .review-moves").click();
    const p = await prompt();
    await snap("b2b2b-ambiguous");
    await dialogButton("Not now");
    fs.unlinkSync(path.join(WS, b)); moveFs(a, src);
    const gone = await waitFor(() => rowIn(fo, "moved").then((t) => !t), 20000);
    rec("R-A8 a source found at two unregistered paths is shown in the strip and the prompt with both candidates; nothing can be adopted; nothing was written",
        !!row && p.detail.includes(a) && p.detail.includes(b) && /nothing is guessed/.test(p.detail) && JSON.stringify(p.buttons.slice(0, 1)) === '["Not now"]' &&
        !p.buttons.includes("Update the registry") && reg() === regBefore && !!gone, { row, buttons: p.buttons });
  });

  await step("R-QA3 a source moved out of the workspace: a notice, no prompt, the registry unchanged", async () => {
    const src = B2.r2.path, regBefore = reg(), outside = "../outside-ws/rename-two.md";   // outside the repository folder
    await app.host("command", { id: "notifications.clearAll" });
    const ok = await app.host("rename", { pairs: [[src, outside]] });
    const notice = await toast(/left the design workspace .*The registry is not updated/, 20000);
    const none = await noPrompt(2500);
    await snap("b2b2b-left-workspace");
    fs.renameSync(path.join(WS, ...outside.split("/")), path.join(WS, ...src.split("/")));   // put back outside VS Code
    rec("R-QA3 a registered source dragged out of the workspace is reported (it left the design workspace; the registry is not updated), never silently dropped; no prompt",
        ok === true && !!notice && none && reg() === regBefore && notice.includes(B2.r2.id), { notice: (notice || "").slice(0, 240) });
  });

  await step("R-S safety", async () => {
    rec("R-S the unsaved document was never written by Feature Designer; docs/architecture/ unchanged byte for byte; no record left",
        readWs(B2.dirty) === B2.dirtyDisk && (await doc(B2.dirty)).isDirty && archHash() === archBefore && (records() || [1]).length === 0);
    await app.host("revert", { path: B2.dirty }).catch(() => {});
    if ((await doc(B2.open)) && (await doc(B2.open)).isDirty) { await app.host("save", { path: B2.open }); await sleep(600); }
    await app.host("closeAll", {}, 60000).catch(() => {}); await dialogDismissIfAny();
  });
}
