// Feature Designer (T-97 Phase 2, PR B1) end-to-end test in the pinned VS Code 1.146 test build, with
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

  // P2-A: no interpreter configured → the .venv interpreter is suggested; saved only after confirmation
  await step("P2-A interpreter suggestion and confirmation", async () => {
    await app.host("openWith", { path: FEATURE, viewType: "featureDesigner.editor" });
    f = await designerFrame(app.page);                    // rendering needs no Python; the library does
    const b0 = await blockAfter("3. Logic");
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

  await prB1Steps();
  await prB2aSteps();

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

async function dialogDismissIfAny() {                       // "save changes?" prompts on close: keep the buffer
  await sleep(500);
  const dlg = app.page.locator(".monaco-dialog-box");
  if (await dlg.count()) {
    const cancel = dlg.locator(".monaco-button").filter({ hasText: /^Cancel$/ });   // never "Don't Save": that would discard the buffer
    if (await cancel.count()) await cancel.first().click();
  }
}
