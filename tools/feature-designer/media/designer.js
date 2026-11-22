/* Feature Designer webview (T-97 Phase 2, PR B). Renders VS Code's current document buffer and sends
 * intents to the extension host; it never edits text itself. Every change comes back as a new
 * document version. Only implemented options appear in the "+" menu (Q7). Diagram blocks are drawn
 * from their authoritative sources; a copy that differs is never hidden (decision B2). */
(function () {
  "use strict";
  const api = window.FD_HOST.api;
  const md = window.markdownit({ html: true, linkify: false });
  const C = window.FDCore;
  const state = { text: "", version: -1, rel: "", lines: [], library: null, others: [], featureId: "",
                  blocks: null,                    // {version, list, error}: the state of each diagram block (PR B)
                  pending: null };                 // a diagram created but not inserted: {id, path, reason, placing}
  const CATEGORIES = ["system-architecture", "data-model", "process", "sequence", "state", "ui", "legend", "other"];
  const SECTION_CATEGORY = { 1: "other", 2: "data-model", 3: "process", 4: "system-architecture", 5: "system-architecture", 6: "other" };  // B5
  const CONFLICT_TEXT = {
    case2: "Changed outside its source: the copy in this document was edited by hand (or reformatted by another editor); its source is unchanged.",
    case3: "Changed outside its source: both the copy in this document and its source changed since the copy was generated.",
    legacy: "Possibly changed outside its source: this copy was made before fingerprints and differs from its source, so whether it was edited by hand cannot be established.",
  };
  let nameSeq = 0, nameView = null;
  const svgCache = new Map();
  let mermaidSeq = 0, menuState = null, dialogOpen = false, libraryView = null;

  const $ = (s, el = document) => el.querySelector(s);
  const h = (tag, attrs = {}, ...kids) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") el.className = v; else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v); else el.setAttribute(k, v === true ? "" : v);
    }
    for (const k of kids) if (k !== null && k !== undefined) el.append(k);
    return el;
  };
  // Document HTML is sanitised: no scripts, forms, frames, styles or inline style attributes.
  const PURIFY = { FORBID_TAGS: ["style", "form", "input", "button", "textarea", "select", "iframe", "object", "embed", "link", "meta", "base", "svg", "math"],
                   FORBID_ATTR: ["style", "id"], ADD_ATTR: ["open"] };
  const sanitize = (html) => window.DOMPurify.sanitize(html, PURIFY);
  const post = (msg) => api.postMessage(msg);

  function status(text, err) {
    let el = $("#status");
    if (!el) { el = h("div", { id: "status", role: "status", "aria-live": "polite" }); document.body.append(el); }
    el.textContent = text; el.className = err ? "err" : ""; el.style.display = "block";
    clearTimeout(status.t); status.t = setTimeout(() => (el.style.display = "none"), err ? 7000 : 2500);
  }

  function toolbar() {
    $("#toolbar").replaceChildren(
      h("span", { class: "grow", text: `Feature Designer · ${state.rel}` }),
      h("button", { type: "button", onclick: () => post({ type: "undo" }), title: "Undo (Ctrl+Z)", text: "Undo" }),
      h("button", { type: "button", onclick: () => post({ type: "redo" }), title: "Redo (Ctrl+Y)", text: "Redo" }),
      h("button", { type: "button", onclick: () => post({ type: "showLog" }), title: "Feature Designer: Show Log", text: "Log" }));
  }

  function banner() {
    const el = $("#banner");
    if (state.others.length) {
      el.textContent = `Also open in ${state.others.join(", ")}. Feature Designer edits VS Code's shared document; ` +
                       `pause typing in ${state.others.join(", ")} before inserting.`;
      el.hidden = false;
    } else el.hidden = true;
  }

  window.addEventListener("message", (e) => {
    const m = e.data;
    if (!m || typeof m.type !== "string") return;
    if (m.type === "doc") {
      state.text = m.text; state.version = m.version; state.others = m.others || [];
      state.featureId = ((/^feature_id:\s*"?(FD-\d{4})"?(?=\s|#|$)/m.exec(m.text.split(/\r?\n---\r?\n/)[0] || "")) || [])[1] || "";
      if (state.pending && new RegExp(`<!--\\s*diagram:start\\s+${state.pending.id}\\s`).test(m.text)) { state.pending = null; notice(); }
      if (m.rel) { state.rel = m.rel; toolbar(); }
      banner();
      if (!menuState && !dialogOpen) render(); else render.pending = true;
    } else if (m.type === "others") { state.others = m.others || []; banner(); }
    else if (m.type === "libraryError") { if (libraryView) libraryView.failed(m.message, m.interpreter); else status(m.message, true); }
    else if (m.type === "pythonChanged") { if (libraryView) libraryView.retry(); }
    else if (m.type === "library") { state.library = m.data; if (libraryView) libraryView.fill(); if (nameView) nameView.owners(); }
    else if (m.type === "blocks") {
      state.blocks = { version: m.version, list: m.blocks, error: m.error || "" };
      if (!menuState && !dialogOpen) render(); else render.pending = true;
    }
    else if (m.type === "name") { if (nameView && m.seq === nameSeq) nameView.named(m); }
    else if (m.type === "created") status(`Created ${m.id} (${m.path}) and placed it here; its source is open beside this view.`);
    else if (m.type === "placeLater") { state.pending = { id: m.id, path: m.path, reason: m.reason, placing: false }; notice(); }
    else if (m.type === "placeNow") { if (state.pending && state.pending.id === m.id) placing(true); }
    else if (m.type === "generated") {
      const el = $("#stale");
      const n = m.stale || 0, p = (m.blocking || []).length, c = (m.conflicts || []).length;
      el.hidden = !(n || p || c);
      el.textContent = p ? `A generated diagram block has a problem (${m.blocking[0]}). Run python -m tools.design check.`
        : c ? `${c} generated diagram block${c === 1 ? " was changed outside its source" : "s were changed outside their sources"} ` +
              `(for example reformatted by another editor), so ${c === 1 ? "it is" : "they are"} never overwritten automatically. ` +
              "Your own text is unaffected; resolve them with python -m tools.design reconcile (see python -m tools.design check)."
        : `${n} generated diagram block${n === 1 ? " no longer matches its source" : "s no longer match their sources"}. ` +
          "Your own text is unaffected; run python -m tools.design index to regenerate them.";
    }
    else if (m.type === "error") status(m.message, true);
  });

  // ------------------------------------------------------------------ rendering
  function render() {
    render.pending = false;
    const scroll = window.scrollY;
    state.lines = C.splitLines(state.text);
    render.used = new Set();
    const zone = C.insertionZone(state.text);
    const out = [];
    for (const seg of C.segments(state.text)) {
      if (seg.kind === "markdown") out.push(...markdownBlocks(seg)); else out.push(specialBlock(seg));
    }
    for (const b of out) {
      const end = +b.dataset.end;
      if (zone && end > zone.start && end <= zone.end) b.prepend(plusButton(b));
    }
    $("#doc").replaceChildren(...out);
    $("#doc").querySelectorAll("a").forEach((a) => a.addEventListener("click", (ev) => ev.preventDefault()));
    drawMermaid($("#doc"));
    window.scrollTo(0, scroll);
  }

  const block = (start, end, kind, ...content) => h("div", { class: `block ${kind}`, "data-start": start, "data-end": end }, ...content);
  const mdHtml = (text) => { const d = h("div"); d.innerHTML = sanitize(md.render(text)); return d; };

  function markdownBlocks(seg) {
    const tokens = md.parse(state.lines.slice(seg.start, seg.end).join("\n"), {});
    const blocks = [];
    for (let i = 0; i < tokens.length;) {
      const t = tokens[i]; let j = i;
      if (t.nesting === 1) { let depth = 0; for (j = i; j < tokens.length; j++) { depth += tokens[j].nesting; if (depth === 0) break; } }
      const group = tokens.slice(i, j + 1); i = j + 1;
      if (!t.map) continue;
      const d = h("div"); d.innerHTML = sanitize(md.renderer.render(group, md.options, {}));
      blocks.push(block(seg.start + t.map[0], seg.start + t.map[1], t.type.replace(/_open$/, ""), d));
    }
    return blocks;
  }

  function specialBlock(seg) {
    const inner = state.lines.slice(seg.start + 1, seg.end - 1).join("\n");
    if (seg.kind === "frontmatter") {
      const id = (/^feature_id:\s*(.*)$/m.exec(inner) || [])[1] || "";
      return block(seg.start, seg.end, "readonly", h("div", { class: "meta", text: `Metadata ${id} (YAML) · edit it in the text editor or Mark Sharp` }));
    }
    if (seg.kind === "details") return block(seg.start, seg.end, "details", mdHtml(state.lines.slice(seg.start, seg.end).join("\n")));
    if (seg.kind === "diagram") return diagramBlock(seg);
    const labels = { summary: "Generated summary (from the metadata)", related: "Generated Related features rows (from depends_on)" };
    return block(seg.start, seg.end, "readonly", h("div", { class: "gen", "aria-readonly": "true" }, h("div", { class: "gen-label", text: labels[seg.kind] }), mdHtml(inner)));
  }

  // ------------------------------------------------------------------ diagram blocks (PR B1)
  /** The state of a block. For an older document version it is reused only when the block itself
   *  (marker and copy) is unchanged, since the state depends on nothing else in the document. */
  function infoFor(seg, used) {
    const B = state.blocks;
    if (!B || !B.list) return null;
    const marker = state.lines[seg.start], embedded = state.lines.slice(seg.start + 1, seg.end - 1);
    const same = (b) => b.id === seg.id && b.marker === marker && b.embedded.length === embedded.length && b.embedded.every((l, i) => l === embedded[i]);
    const found = B.version === state.version ? B.list.find((b) => b.start === seg.start && b.id === seg.id)
                                              : B.list.find((b) => !used.has(b) && same(b));
    if (found) used.add(found);
    return found || null;
  }

  function diagramBlock(seg) {
    const embedded = state.lines.slice(seg.start + 1, seg.end - 1);
    const info = infoFor(seg, render.used);
    const st = info ? info.state : "pending";
    const src = info && info.source;
    const pencil = h("button", { type: "button", class: "edit-diagram", "data-id": seg.id, text: "✎",
                                 title: "Edit Diagram: open its authoritative source", "aria-label": `Edit diagram ${seg.id}`,
                                 onclick: () => post({ type: "editDiagram", id: seg.id }) });
    const head = h("div", { class: "gen-label" }, h("span", { text: `Diagram · ${seg.id}` }),
      src && src.id !== seg.id ? h("span", { class: "alias", text: `stable ID ${src.id}` }) : null,
      src && src.path ? h("span", { class: "src", text: `source: ${src.path}` }) : null, h("span", { class: "grow" }), pencil);
    const md = (lines) => mdHtml(lines.join("\n"));
    const note = (cls, text, ...extra) => h("div", { class: `dg-notice ${cls}`, role: cls === "warn" ? "alert" : "note" }, h("span", { text }), ...extra);
    const copy = (label) => h("details", { class: "dg-copy" }, h("summary", { text: label }), md(embedded));
    const version = (cls, label, lines) => h("div", { class: `dg-version ${cls}` }, h("div", { class: "dg-vlabel", text: label }), md(lines));
    const diff = () => (info.diff && info.diff.length ? h("details", { class: "dg-diff" }, h("summary", { text: "Show the text differences" }),
      h("pre", { class: "diff" }, ...info.diff.map((l) => h("span", { class: /^\+(?!\+\+)/.test(l) ? "add" : /^-(?!--)/.test(l) ? "del" : "", text: `${l}\n` })))) : null);
    const body = [];
    if (st === "pending") {
      const why = state.blocks && state.blocks.error;
      body.push(note("info", why ? `Shown as copied in this document: its source could not be checked (${why}).`
                                 : "Shown as copied in this document while its source is checked…"), md(embedded));
    } else if (st === "current") body.push(md(info.generated));
    else if (st === "fingerprint") body.push(md(info.generated), note("info", "Matches its source; only its marker is out of date (python -m tools.design index updates it)."));
    else if (st === "empty") body.push(note("info", "Empty in this document: shown from its source (python -m tools.design index fills it in)."), md(info.generated));
    else if (st === "outdated") body.push(note("info", "Out of date in this document: its source changed and this copy was not edited. Shown from the source; python -m tools.design index updates the copy."),
                                          md(info.generated), copy("Show the out-of-date copy in this document"), diff());
    else if (st === "conflict") body.push(note("warn", `${CONFLICT_TEXT[info.conflict] || "Changed outside its source."} It is never overwritten automatically (E15).`),
      h("div", { class: "dg-both" }, version("authoritative", `Authoritative source${src && src.path ? ` · ${src.path}` : ""}`, info.generated),
                                      version("document-copy", "Copy in this document · differs from its source", embedded)),
      diff(), h("div", { class: "dg-fix", text: info.message }));
    else if (st === "retired") body.push(note("warn", info.message || "This diagram was retired (E11).",
      h("button", { type: "button", class: "remove-ref", text: "Remove reference", title: "Remove this block (one undoable edit)",
                     onclick: () => post({ type: "removeBlock", line: seg.start, id: seg.id, version: state.version }) })),
      copy("Show the copy in this document"));
    else body.push(note("warn", info.message || "This diagram cannot be shown."), copy("Show the copy in this document"));
    return block(seg.start, seg.end, `readonly diagram dg-${st}`,
                 h("div", { class: `gen dg dg-${st}`, "data-diagram": seg.id, "data-state": st, "aria-readonly": "true" }, head, ...body));
  }

  // ------------------------------------------------------------------ a diagram created but not inserted
  function notice() {
    const el = $("#notice"), p = state.pending;
    document.body.classList.toggle("placing", !!(p && p.placing));
    if (!p) { el.hidden = true; el.replaceChildren(); return; }
    el.hidden = false;
    el.replaceChildren(p.placing
      ? h("span", { text: `Click + where diagram ${p.id} should go; Add Existing Diagram then opens with it selected.` })
      : h("span", { text: `Diagram ${p.id} was created and registered (${p.path}), but it was not inserted: ${p.reason}.` }),
      p.placing ? h("button", { type: "button", class: "cancel-place", text: "Cancel", onclick: () => placing(false) })
                : h("button", { type: "button", class: "add-existing", text: "Add Existing Diagram…", onclick: () => placing(true) }),
      h("button", { type: "button", class: "dismiss", text: "Dismiss", title: `The diagram stays registered; place it any time with Add Existing Diagram`,
                    onclick: () => { state.pending = null; notice(); } }));
  }
  function placing(on) { if (state.pending) { state.pending.placing = on; notice(); } }

  async function drawMermaid(rootEl) {
    const codes = [...rootEl.querySelectorAll("pre > code.language-mermaid")];
    if (!codes.length) return;
    if (!drawMermaid.init) {
      const dark = document.body.classList.contains("vscode-dark") || document.body.classList.contains("vscode-high-contrast");
      window.mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "default" });
      drawMermaid.init = true;
    }
    for (const code of codes) {
      const src = code.textContent, pre = code.parentElement;
      const out = h("div", { class: "mermaid-out", role: "img", "aria-label": "Mermaid diagram" });
      pre.replaceWith(out);
      try {
        if (!svgCache.has(src)) svgCache.set(src, (await window.mermaid.render(`fd-m-${++mermaidSeq}`, src)).svg);
        out.innerHTML = svgCache.get(src);
      } catch (err) { out.append(h("div", { class: "mermaid-err", text: `Mermaid error: ${err.message || err}` })); }
    }
  }

  // ------------------------------------------------------------------ "+" and its menu
  function plusButton(blockEl) {
    return h("button", { type: "button", class: "plus", "aria-label": "Insert a block below", title: "Insert a block below",
                         "aria-haspopup": "menu", "aria-expanded": "false", text: "+", onclick: (e) => openMenu(e.currentTarget, blockEl) });
  }
  function closeMenu() { if (menuState) { menuState.close(); menuState = null; if (render.pending && !dialogOpen) render(); } }
  function menuKeys(menu, onLeft) {
    menu.addEventListener("keydown", (e) => {
      const list = [...menu.querySelectorAll('[role="menuitem"]')], i = list.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { list[(i + 1) % list.length].focus(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { list[(i - 1 + list.length) % list.length].focus(); e.preventDefault(); }
      else if (onLeft && (e.key === "ArrowLeft" || e.key === "Escape")) { onLeft(); e.preventDefault(); e.stopPropagation(); }
    });
  }
  function openMenu(btn, blockEl) {
    closeMenu();
    const at = +blockEl.dataset.end;
    if (state.pending && state.pending.placing) { blockEl.classList.add("insert-target"); openLibrary(at, state.pending.id); return; }
    // Q7: only implemented options. Place Diagram ▸ Add Existing Diagram… / Make New Diagram… (PR B)
    const sub = [["Add Existing Diagram…", () => openLibrary(at)], ["Make New Diagram…", () => openMakeNew(at)]];
    const place = h("button", { type: "button", role: "menuitem", class: "has-sub", "aria-haspopup": "menu", "aria-expanded": "false" },
                    h("span", { text: "Place Diagram" }), h("span", { class: "chev", "aria-hidden": "true", text: "▸" }));
    const menu = h("div", { class: "menu", role: "menu", "aria-label": "Insert" }, place);
    let subMenu = null;
    const closeSub = () => { if (subMenu) { subMenu.remove(); subMenu = null; place.setAttribute("aria-expanded", "false"); } };
    const openSub = (focus) => {
      if (!subMenu) {
        subMenu = h("div", { class: "menu sub", role: "menu", "aria-label": "Place Diagram" },
          ...sub.map(([label, fn]) => h("button", { type: "button", role: "menuitem", text: label, onclick: () => { closeMenu(); fn(); } })));
        const r = place.getBoundingClientRect();
        subMenu.style.left = `${r.right + window.scrollX + 2}px`; subMenu.style.top = `${r.top + window.scrollY - 4}px`;
        document.body.append(subMenu);
        place.setAttribute("aria-expanded", "true");
        menuKeys(subMenu, () => { closeSub(); place.focus(); });
      }
      if (focus) subMenu.querySelector('[role="menuitem"]').focus();
    };
    place.addEventListener("click", () => openSub(true));
    place.addEventListener("mouseenter", () => openSub(false));
    place.addEventListener("keydown", (e) => { if (e.key === "ArrowRight" || e.key === "Enter" || e.key === " ") { openSub(true); e.preventDefault(); } });
    const r = btn.getBoundingClientRect();
    menu.style.left = `${r.left + window.scrollX}px`; menu.style.top = `${r.bottom + window.scrollY + 4}px`;
    document.body.append(menu);
    btn.setAttribute("aria-expanded", "true"); blockEl.classList.add("insert-target");
    const onDoc = (e) => { if (!menu.contains(e.target) && !(subMenu && subMenu.contains(e.target)) && e.target !== btn) closeMenu(); };
    menuKeys(menu, null);
    menu.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeMenu(); btn.focus(); e.preventDefault(); } });
    setTimeout(() => document.addEventListener("mousedown", onDoc), 0);
    menuState = { close: () => { document.removeEventListener("mousedown", onDoc); closeSub(); menu.remove(); btn.setAttribute("aria-expanded", "false");
                                 if (!dialogOpen) blockEl.classList.remove("insert-target"); } };
    place.focus();
  }

  // ------------------------------------------------------------------ Make New Diagram (PR B1)
  function sectionAt(at) {
    for (let i = Math.min(at, state.lines.length) - 1; i >= 0; i--) { const m = /^##\s+(\d)\./.exec(state.lines[i]); if (m) return +m[1]; }
    return 0;
  }
  function openMakeNew(at) {
    const own = state.featureId;
    let owner = own, pendingOwner = null, named = null, timer = null;
    const name = h("input", { type: "text", class: "dg-name", "aria-label": "Diagram name", placeholder: "for example Pipe inspection flow", maxlength: "120" });
    const category = h("select", { class: "dg-category", "aria-label": "Category" },
      ...CATEGORIES.map((c) => h("option", { value: c, text: c, selected: c === (SECTION_CATEGORY[sectionAt(at)] || "other") })));
    const ownerText = h("span", { class: "owner-text" });
    const change = h("button", { type: "button", class: "change-owner", text: "Change owner…" });
    const ownerPick = h("div", { class: "owner-pick", hidden: true });
    const file = h("div", { class: "dg-file", role: "status", "aria-live": "polite" });
    const create = h("button", { type: "button", class: "primary", text: "Create and Insert", disabled: true });
    const titleOf = (id) => {
      const g = state.library && state.library.features.find((x) => x.feature_id === id);
      return g && g.title ? `${id} — ${g.title}` : id;
    };
    const showOwner = () => { ownerText.textContent = owner === own ? `${titleOf(owner)} (the feature you are editing)` : `${titleOf(owner)} (not the feature you are editing)`; };
    const preview = () => {
      clearTimeout(timer); named = null; create.disabled = true;
      if (!name.value.trim()) { file.textContent = "Enter a name."; file.className = "dg-file"; return; }
      file.textContent = "Checking the name…"; file.className = "dg-file";
      timer = setTimeout(() => post({ type: "previewName", seq: ++nameSeq, owner, title: name.value, category: category.value }), 200);
    };
    const d = dialog("Make New Diagram", h("div", { class: "make-new" },
        h("label", {}, "Name", name), h("label", {}, "Category", category),
        h("div", { class: "owner-row" }, h("span", { class: "k", text: "Owner" }), ownerText, change), ownerPick,
        h("div", { class: "dg-hint", text: "Creates one standalone Mermaid source owned by this feature, registers it with a stable ID, and inserts a reference here. The source is not copied into this document." }),
        file),
      [h("button", { type: "button", text: "Cancel", onclick: () => d.close() }), create], () => { nameView = null; clearTimeout(timer); });
    nameView = {
      named(m) { named = m; file.textContent = m.problem || `File: ${m.path}`; file.className = m.problem ? "dg-file bad" : "dg-file"; create.disabled = !!m.problem || !m.path || !!pendingOwner; },
      owners() { showOwner(); },
    };
    change.addEventListener("click", () => {                    // explicit, secondary, confirmed (decision B9/ownership)
      const others = ((state.library && state.library.features) || []).filter((g) => g.feature_id !== owner);
      const pick = h("select", { class: "owner-select", "aria-label": "New owner" }, ...others.map((g) => h("option", { value: g.feature_id, text: titleOf(g.feature_id) })));
      const use = h("button", { type: "button", class: "use-owner", text: "Use this owner", disabled: !others.length });
      ownerPick.hidden = false;
      ownerPick.replaceChildren(others.length ? pick : h("span", { text: "No other feature can own it." }), use,
                                h("button", { type: "button", text: "Keep current owner", onclick: () => { pendingOwner = null; ownerPick.hidden = true; preview(); } }));
      use.addEventListener("click", () => {
        pendingOwner = pick.value; create.disabled = true;
        ownerPick.replaceChildren(h("div", { class: "confirm-text", text: `The new diagram will be owned by ${titleOf(pendingOwner)}, not by ${titleOf(own)} (the feature you are editing). ` +
            `Its source goes next to ${pendingOwner}'s specification and changes only through ${pendingOwner}; placing it here does not change its owner.` }),
          h("button", { type: "button", class: "confirm-owner", text: `Confirm owner ${pendingOwner}`, onclick: () => { owner = pendingOwner; pendingOwner = null; ownerPick.hidden = true; showOwner(); preview(); } }),
          h("button", { type: "button", text: `Keep ${owner}`, onclick: () => { pendingOwner = null; ownerPick.hidden = true; preview(); } }));
      });
    });
    create.addEventListener("click", () => {
      if (create.disabled || !named || named.problem) return;
      d.close();
      status("Creating the diagram…");
      post({ type: "makeNew", at, version: state.version, owner, title: name.value, category: category.value });
    });
    name.addEventListener("input", preview); category.addEventListener("change", preview);
    name.addEventListener("keydown", (e) => { if (e.key === "Enter") { create.click(); e.preventDefault(); } });
    showOwner();
    if (!own) { file.textContent = "This document has no feature ID, so it cannot own a diagram; fix its metadata first."; file.className = "dg-file bad"; name.disabled = true; }
    if (!state.library) post({ type: "library" });
    name.focus();
  }

  // ------------------------------------------------------------------ the diagram library
  function dialog(title, body, buttons, onClose) {
    dialogOpen = true;
    const back = h("div", { class: "backdrop" });
    const dlg = h("div", { class: "dlg", role: "dialog", "aria-modal": "true", "aria-label": title },
      h("header", { text: title }), h("div", { class: "body" }, body), h("footer", {}, ...buttons));
    back.append(dlg); document.body.append(back);
    const close = () => { dialogOpen = false; back.remove(); document.querySelectorAll(".insert-target").forEach((b) => b.classList.remove("insert-target"));
                          if (onClose) onClose(); if (render.pending) render(); };
    back.addEventListener("mousedown", (e) => { if (e.target === back) close(); });
    dlg.addEventListener("keydown", (e) => { if (e.key === "Escape") { close(); e.preventDefault(); } });
    return { dlg, close };
  }

  function openLibrary(at, preset) {
    const search = h("input", { type: "search", placeholder: "Search by name, ID, former ID, category, source document or owning feature", "aria-label": "Search diagrams" });
    if (preset) search.value = preset;
    const tree = h("ul", { class: "tree", role: "tree", "aria-label": "Diagram library" });
    let selected = null;
    const insertBtn = h("button", { type: "button", class: "primary", text: "Insert", disabled: true, onclick: () => { if (selected) choose(selected.dataset.id); } });
    const d = dialog(preset ? `Add Existing Diagram — place ${preset}` : "Add Existing Diagram", h("div", {}, search, tree),
                     [h("button", { type: "button", text: "Cancel", onclick: () => d.close() }), insertBtn], () => (libraryView = null));
    const version = state.version;
    const choose = (id) => { d.close(); post({ type: "insertDiagram", at, id, version }); };
    const select = (li) => {
      tree.querySelectorAll('.row[aria-selected="true"]').forEach((r) => r.setAttribute("aria-selected", "false"));
      selected = li && li.classList.contains("item") && !li.dataset.problem ? li : null;
      if (li) { li.querySelector(".row").setAttribute("aria-selected", "true"); li.querySelector(".row").scrollIntoView({ block: "nearest" }); }
      insertBtn.disabled = !selected;
    };
    function setOpen(li, open) {
      li.setAttribute("aria-expanded", open ? "true" : "false");
      const tw = li.querySelector(":scope > .row .twisty"); if (tw) tw.textContent = open ? "▾" : "▸";
      li.querySelector(":scope > ul").hidden = !open;
    }
    const node = (cls, label, extra, kids, hay) => {
      const row = h("div", { class: "row" }, kids ? h("span", { class: "twisty", text: "▸" }) : null, h("span", { class: "label", text: label }), ...extra);
      const li = h("li", { class: cls, role: "treeitem" }, row);
      if (kids) { li.append(h("ul", { role: "group" }, ...kids)); setOpen(li, cls === "cat"); }
      if (hay) li.dataset.hay = hay.toLowerCase();
      row.addEventListener("click", () => { if (kids) setOpen(li, li.getAttribute("aria-expanded") !== "true"); select(li); });
      if (cls === "item") row.addEventListener("dblclick", () => { if (!li.dataset.problem) choose(li.dataset.id); });
      return li;
    };
    const item = (x, groupLabel) => {
      const extra = [h("span", { class: "id", text: x.id })];
      if (x.category) extra.push(h("span", { class: "cat-tag", text: x.category }));
      if (x.owner) extra.push(h("span", { class: "id", text: `owned by ${x.owner}` }));
      if (x.problem) extra.push(h("span", { class: "bad", text: x.problem }));
      const li = node("item", x.title, extra, null, [x.title, x.id, ...(x.aliases || []), x.category || "", x.owner || "", groupLabel, x.path].join(" "));
      li.dataset.id = x.id; if (x.problem) li.dataset.problem = x.problem;
      return li;
    };
    libraryView = {
      failed(message, interpreter) {               // never leave the dialog on "Loading…"
        tree.replaceChildren(h("li", { class: "lib-error", role: "alert" },
          h("div", { class: "bad", text: `The diagram library could not be loaded: ${message}` }),
          h("div", { class: "lib-actions" },
            h("button", { type: "button", class: "retry", text: "Retry", onclick: () => libraryView && libraryView.retry() }),
            interpreter ? h("button", { type: "button", class: "change-python", text: "Change Interpreter…", onclick: () => post({ type: "selectPython" }) }) : null)));
      },
      retry() { tree.replaceChildren(h("li", { text: "Loading the diagram library…" })); search.focus(); post({ type: "library" }); },
      fill() {
        const live = (list) => list.filter((x) => x.status !== "retired");          // decision B7: retired diagrams are hidden
        const L = { ...state.library, architecture: state.library.architecture.map((g) => ({ ...g, diagrams: live(g.diagrams) })).filter((g) => g.diagrams.length),
                    features: state.library.features.map((g) => ({ ...g, diagrams: live(g.diagrams) })), unowned: live(state.library.unowned) };
        const arch = L.architecture.map((g) => node("grp", g.title, [h("span", { class: "id", text: g.document })], g.diagrams.map((x) => item(x, `${g.title} ${g.document}`))));
        const feats = L.features.map((g) => node("grp", `${g.feature_id} — ${g.title}`, [h("span", { class: "id", text: `${g.diagrams.length} diagram(s)` })],
          g.diagrams.length ? g.diagrams.map((x) => item(x, `${g.feature_id} ${g.title}`))
                            : [h("li", { class: "empty", role: "none" }, h("div", { class: "row id", text: "no diagrams owned by this feature" }))]));
        if (L.unowned.length) feats.push(node("grp", "Diagram files without a valid owner", [], L.unowned.map((x) => item(x, "unowned"))));
        tree.replaceChildren(node("cat", "Main Branch — Architecture", [h("span", { class: "id", text: "current architecture" })], arch),
                             node("cat", "Feature Documents", [h("span", { class: "id", text: "owned by features (proposed)" })], feats));
        filter();
      },
    };
    function filter() {
      const words = search.value.toLowerCase().split(/\s+/).filter(Boolean);
      tree.querySelectorAll("li.item").forEach((li) => (li.hidden = !words.every((w) => li.dataset.hay.includes(w))));
      tree.querySelectorAll("li.grp, li.cat").forEach((li) => {
        const any = [...li.querySelectorAll("li.item")].some((x) => !x.hidden) || (!words.length && li.querySelector("li.empty"));
        li.hidden = !any && words.length > 0;
        if (words.length) setOpen(li, any);
      });
      if (!words.length) tree.querySelectorAll("li.grp").forEach((li) => setOpen(li, false));
      const first = tree.querySelector("li.item:not([hidden])");
      select(words.length && first ? first : null);
    }
    search.addEventListener("input", filter);
    const visibleRows = () => [...tree.querySelectorAll("li")].filter((li) => li.offsetParent !== null && li.querySelector(":scope > .row"));
    d.dlg.addEventListener("keydown", (e) => {
      const rows = visibleRows(), cur = tree.querySelector('.row[aria-selected="true"]'), i = cur ? rows.indexOf(cur.parentElement) : -1;
      if (e.key === "ArrowDown") { select(rows[Math.min(rows.length - 1, i + 1)]); e.preventDefault(); }
      else if (e.key === "ArrowUp") { select(rows[Math.max(0, i - 1)]); e.preventDefault(); }
      else if ((e.key === "ArrowRight" || e.key === "ArrowLeft") && cur && cur.parentElement.querySelector(":scope > ul") && e.target !== search) { setOpen(cur.parentElement, e.key === "ArrowRight"); e.preventDefault(); }
      else if (e.key === "Enter" && cur) {
        const li = cur.parentElement;
        if (li.classList.contains("item")) { if (!li.dataset.problem) choose(li.dataset.id); } else setOpen(li, li.getAttribute("aria-expanded") !== "true");
        e.preventDefault();
      }
    });
    if (state.library) libraryView.fill(); else tree.replaceChildren(h("li", { text: "Loading the diagram library…" }));
    post({ type: "library" });                                   // always fresh: sources may have changed
    search.focus();
  }

  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
  toolbar();
  post({ type: "ready" });
  window.FD_DEBUG = { state };
})();
