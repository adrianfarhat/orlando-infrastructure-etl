/* Feature Designer webview (T-97 Phase 2). Renders VS Code's current document buffer and sends
 * intents to the extension host; it never edits text itself. Every change comes back as a new
 * document version. Only implemented options appear in the "+" menu (Q7). */
(function () {
  "use strict";
  const api = window.FD_HOST.api;
  const md = window.markdownit({ html: true, linkify: false });
  const C = window.FDCore;
  const state = { text: "", version: -1, rel: "", lines: [], library: null, others: [] };
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
      if (m.rel) { state.rel = m.rel; toolbar(); }
      banner();
      if (!menuState && !dialogOpen) render(); else render.pending = true;
    } else if (m.type === "others") { state.others = m.others || []; banner(); }
    else if (m.type === "library") { state.library = m.data; if (libraryView) libraryView.fill(); }
    else if (m.type === "generated") {
      const el = $("#stale");
      const n = m.stale || 0, p = (m.blocking || []).length;
      el.hidden = !(n || p);
      el.textContent = p ? `A generated diagram block has a problem (${m.blocking[0]}). Run python -m tools.design check.`
        : `${n} generated diagram block${n === 1 ? " no longer matches its source" : "s no longer match their sources"} ` +
          "(for example after another editor reformatted them). Your own text is unaffected; run python -m tools.design index to regenerate them.";
    }
    else if (m.type === "error") status(m.message, true);
  });

  // ------------------------------------------------------------------ rendering
  function render() {
    render.pending = false;
    const scroll = window.scrollY;
    state.lines = C.splitLines(state.text);
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
    if (seg.kind === "diagram") {
      const label = h("div", { class: "gen-label" }, h("span", { text: `Generated diagram · ${seg.id}` }),
        h("button", { type: "button", class: "edit-source", "data-id": seg.id, onclick: () => post({ type: "editSource", id: seg.id }),
                      "aria-label": `Edit source of diagram ${seg.id}`, text: "Edit source" }));
      return block(seg.start, seg.end, "readonly diagram", h("div", { class: "gen", "data-diagram": seg.id, "aria-readonly": "true" }, label, mdHtml(inner)));
    }
    const labels = { summary: "Generated summary (from the metadata)", related: "Generated Related features rows (from depends_on)" };
    return block(seg.start, seg.end, "readonly", h("div", { class: "gen", "aria-readonly": "true" }, h("div", { class: "gen-label", text: labels[seg.kind] }), mdHtml(inner)));
  }

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
  function openMenu(btn, blockEl) {
    closeMenu();
    const at = +blockEl.dataset.end;
    const items = [["Insert Existing Diagram", () => openLibrary(at)]];            // Q7: only implemented options
    const menu = h("div", { class: "menu", role: "menu", "aria-label": "Insert" },
      ...items.map(([label, fn]) => h("button", { type: "button", role: "menuitem", text: label, onclick: () => { closeMenu(); fn(); } })));
    const r = btn.getBoundingClientRect();
    menu.style.left = `${r.left + window.scrollX}px`; menu.style.top = `${r.bottom + window.scrollY + 4}px`;
    document.body.append(menu);
    btn.setAttribute("aria-expanded", "true"); blockEl.classList.add("insert-target");
    const onDoc = (e) => { if (!menu.contains(e.target) && e.target !== btn) closeMenu(); };
    menu.addEventListener("keydown", (e) => {
      const list = [...menu.querySelectorAll('[role="menuitem"]')], i = list.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { list[(i + 1) % list.length].focus(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { list[(i - 1 + list.length) % list.length].focus(); e.preventDefault(); }
      else if (e.key === "Escape") { closeMenu(); btn.focus(); e.preventDefault(); }
    });
    setTimeout(() => document.addEventListener("mousedown", onDoc), 0);
    menuState = { close: () => { document.removeEventListener("mousedown", onDoc); menu.remove(); btn.setAttribute("aria-expanded", "false");
                                 if (!dialogOpen) blockEl.classList.remove("insert-target"); } };
    menu.querySelector('[role="menuitem"]').focus();
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

  function openLibrary(at) {
    const search = h("input", { type: "search", placeholder: "Search by name, ID, source document or owning feature", "aria-label": "Search diagrams" });
    const tree = h("ul", { class: "tree", role: "tree", "aria-label": "Diagram library" });
    let selected = null;
    const insertBtn = h("button", { type: "button", class: "primary", text: "Insert", disabled: true, onclick: () => { if (selected) choose(selected.dataset.id); } });
    const d = dialog("Insert Existing Diagram", h("div", {}, search, tree),
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
      if (x.owner) extra.push(h("span", { class: "id", text: `owned by ${x.owner}` }));
      if (x.problem) extra.push(h("span", { class: "bad", text: x.problem }));
      const li = node("item", x.title, extra, null, [x.title, x.id, x.owner || "", groupLabel, x.path].join(" "));
      li.dataset.id = x.id; if (x.problem) li.dataset.problem = x.problem;
      return li;
    };
    libraryView = {
      fill() {
        const L = state.library;
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
