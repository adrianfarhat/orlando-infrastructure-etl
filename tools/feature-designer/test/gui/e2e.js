// Feature Designer (T-97 Phase 2) end-to-end test in the pinned VS Code 1.146 test build, with
// real pointer and keyboard input (Playwright over CDP). Writes evidence to test/gui/.run/.
"use strict";
const fs = require("fs");
const path = require("path");
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
  try { await fn(); } catch (e) { rec(name, false, String(e.message || e).split("\n")[0]); await snap(`FAILED-${name.replace(/[^a-z0-9]+/gi, "-")}`); await app.page.keyboard.press("Escape").catch(() => {}); }
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
async function insertVia(heading, query) {
  const b = await blockAfter(heading);
  await app.page.mouse.move(...Object.values(center(await box(blockSel(b.idx)))), { steps: 4 });
  await f.locator(`${blockSel(b.idx)} >> .plus`).click();
  await f.locator('.menu [role="menuitem"]', { hasText: "Insert Existing Diagram" }).click();
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

  // P2-A: no interpreter configured → the .venv interpreter is suggested; saved only after confirmation
  await step("P2-A interpreter suggestion and confirmation", async () => {
    await app.host("openWith", { path: FEATURE, viewType: "featureDesigner.editor" });
    f = await designerFrame(app.page);                    // rendering needs no Python; the library does
    const b0 = await blockAfter("3. Logic");
    await app.page.mouse.move(...Object.values(center(await box(blockSel(b0.idx)))), { steps: 3 });
    await f.locator(`${blockSel(b0.idx)} >> .plus`).click();
    await f.locator('.menu [role="menuitem"]').first().click();
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
    await app.page.mouse.move(...Object.values(center(await box(blockSel(b.idx)))), { steps: 6 }); await sleep(400);
    const after = await f.locator(plus).evaluate((el) => getComputedStyle(el).opacity);
    await app.page.mouse.move(...Object.values(center(await box(plus))), { steps: 4 }); await sleep(200);
    const onIt = await f.locator(plus).evaluate((el) => getComputedStyle(el).opacity);
    await f.locator(plus).click();
    const items = await f.locator('.menu [role="menuitem"]').allTextContents();
    await snap("menu");
    rec("2 hover reveals + (stays while moving onto it); the menu shows only Insert Existing Diagram",
        before === "0" && after === "1" && onIt === "1" && JSON.stringify(items) === '["Insert Existing Diagram"]', { before, after, onIt, items });
    await app.page.keyboard.press("Escape");
  });

  await step("3 library", async () => {
    const b = await blockAfter("3. Logic");
    await f.locator(`${blockSel(b.idx)} >> .plus`).click();
    await f.locator('.menu [role="menuitem"]').first().click();
    await f.waitForSelector(".tree li.item", { state: "attached", timeout: 20000 });
    const lib = await f.evaluate(() => ({
      cats: [...document.querySelectorAll(".tree > li.cat > .row .label")].map((x) => x.textContent),
      arch: document.querySelectorAll(".tree > li.cat:nth-child(1) li.item").length,
      feats: [...document.querySelectorAll(".tree > li.cat:nth-child(2) li.grp > .row .label")].map((x) => x.textContent),
      owned: [...document.querySelectorAll(".tree > li.cat:nth-child(2) li.item")].map((x) => x.dataset.id) }));
    const search = f.locator('.dlg input[type="search"]');
    const visible = async (q) => { await search.fill(q); await sleep(150); return f.evaluate(() => [...document.querySelectorAll(".tree li.item")].filter((li) => li.offsetParent).map((li) => li.dataset.id)); };
    const byName = await visible("credential"), byOwner = await visible("FD-0002"), byDoc = await visible("etl-workflow.md");
    await snap("library");
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
    await app.page.mouse.move(...Object.values(center(await box(blockSel(b.idx)))), { steps: 3 });
    await f.locator(`${blockSel(b.idx)} >> .plus`).click();
    await f.locator('.menu [role="menuitem"]').first().click();
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
    const t0 = Date.now();
    await f.locator('.menu [role="menuitem"]').first().click();
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

  let insertedText;
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
    await f.locator(`.edit-source[data-id="${CRED}"]`).scrollIntoViewIfNeeded();
    await f.locator(`.edit-source[data-id="${CRED}"]`).click();
    const tab = await waitFor(async () => (await app.host("tabs")).find((t) => t.label === "system-architecture.md" && t.kind === "text"));
    const line = await waitFor(() => app.page.locator(".line-numbers.active-line-number").allTextContents().then((x) => x.map((s) => s.trim()).filter(Boolean)));
    const src = fs.readFileSync(path.join(WS, "docs/architecture/system-architecture.md"), "utf8").split(/\r?\n/);
    rec("8 Edit source opens the authoritative Mermaid line", !!tab && line && line.some((n) => src[+n - 1] && src[+n - 1].startsWith("```mermaid")), { line });
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
    await app.page.mouse.move(...Object.values(center(await box(blockSel(b.idx)))), { steps: 3 });
    await f.locator(`${blockSel(b.idx)} >> .plus`).click();
    await f.locator('.menu [role="menuitem"]').first().click();
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

async function dialogDismissIfAny() {                       // "save changes?" prompts on close: keep the buffer
  await sleep(500);
  const dlg = app.page.locator(".monaco-dialog-box");
  if (await dlg.count()) {
    const cancel = dlg.locator(".monaco-button").filter({ hasText: /^Cancel$/ });   // never "Don't Save": that would discard the buffer
    if (await cancel.count()) await cancel.first().click();
  }
}
