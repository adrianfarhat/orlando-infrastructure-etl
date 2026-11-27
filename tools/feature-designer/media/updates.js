// The Update Closed Documents and Resolve Interrupted Update panels (T-97 PR B2b-1).
// Everything shown is built with textContent (no HTML from data). Recovery never preselects an
// action: the Confirm button stays disabled until one is chosen, and Abandon also needs its own
// acknowledgement (D2, D8). Closing the panel changes nothing.
(function () {
  "use strict";
  const api = acquireVsCodeApi();
  const main = document.getElementById("main");
  const post = (m) => api.postMessage(m);
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "text") el.textContent = v;
      else if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : String(v));
    }
    for (const kid of kids.flat()) if (kid) el.append(kid);
    return el;
  }
  const STATE = { updated: "Updated", original: "Not updated (original)", changed: "Changed since: left alone", missing: "Missing: left alone" };
  // PR B2b-2b: a registry move (version 2 record): each rename is judged only by where the source's exact bytes
  // are, and the registry by its bytes. A file in an unexpected state is never overwritten or deleted.
  const MOVE_STATE = { old: "At the old path", new: "At the new path", temp: "At the temporary path (case-only rename)",
                       both: "At more than one path: left alone", neither: "At neither path: left alone",
                       changed: "Changed (other content): left alone" };
  const BACK_STATE = { old: "Where it was found (not moved back yet)", new: "Back at its registered path", temp: MOVE_STATE.temp,
                       both: MOVE_STATE.both, neither: MOVE_STATE.neither, changed: MOVE_STATE.changed };
  const REGISTRY_STATE = { original: "Registry: the original (not updated)", replacement: "Registry: the replacement (updated)",
                           changed: "Registry: changed by something else: never overwritten",
                           unchanged: "Registry: not changed by this move (it never is)" };
  const MODE = { move: "A tool-initiated move: the tooling renames the files, then writes the registry.",
                 adopt: "Observed renames: the files were already renamed (by VS Code, Git or another program); only the registry follows. " +
                        "Undo restores only the registry: the files stay where they were found.",
                 restore: "Move the files back: the tooling renames the files back to their registered paths. The registry is never written." };
  const isMove = (r) => r.tool === "registry-move";
  const REGISTRY = "designs/diagrams/registry.yml";
  function stateText(r, f) {
    if (!isMove(r)) return STATE[f.state] || f.state;
    if (!f.rename) return REGISTRY_STATE[f.state] || f.state;
    return ((r.mode === "restore" ? BACK_STATE : MOVE_STATE)[f.state] || f.state) +
      (f.occupied && f.occupied.length ? ` (occupied by something else: ${f.occupied.join(", ")})` : "");
  }
  function resultState(f) {                         // a result row: a document, a rename or the registry
    if (f.rename) return MOVE_STATE[f.state] || f.state;
    if (f.path === REGISTRY) return REGISTRY_STATE[f.state] || f.state;
    return STATE[f.state] || f.state;
  }
  let result = null;

  function showResult() {
    const old = document.getElementById("result");
    if (old) old.remove();
    if (!result) return;
    // the index line is shown only when it was regenerated; a failure is part of the tooling's message (never claimed)
    const box = h("div", { id: "result", class: result.ok ? "result ok" : "result fail", role: "status" },
      h("p", { text: result.message }), result.note ? h("p", { text: result.note }) : null,
      result.index && result.index.regenerated ? h("p", { class: "index", text: "designs/index/diagram-index.md was regenerated." }) : null,
      (result.files || []).length ? h("ul", {}, result.files.map((f) => h("li", { text: `${f.rename ? `${f.rename.from} → ${f.rename.to}` : f.path}: ${resultState(f)}` }))) : null);
    main.prepend(box);
  }

  function update(m) {
    main.replaceChildren();
    main.append(h("h1", { text: "Update closed documents" }));
    if (!m.eligible.length) main.append(h("p", { class: "none", text: "No closed document has an out-of-date diagram block." }));
    else {
      main.append(h("p", { text: "These feature documents are not open in this window. Their out-of-date diagram blocks are refreshed " +
        "from their sources and written on disk as one recoverable update: if one cannot be written, the documents already " +
        "written are put back. Conflicts are never changed. A record keeps every original until the update is finished: if the " +
        "update is interrupted, or a document is changed by another program meanwhile (it is then left alone), the update is " +
        "reported as partly done and can be completed or undone." }));
      main.append(h("table", { class: "docs" },
        h("thead", {}, h("tr", {}, h("th", { text: "Document" }), h("th", { text: "Diagrams refreshed" }), h("th", { text: "Conflicts left alone" }))),
        h("tbody", {}, m.eligible.map((d) => h("tr", {}, h("td", { text: d.path }), h("td", { text: d.blocks.join(", ") }),
                                                       h("td", { text: (d.conflicts || []).join(", ") || "none" }))))));
    }
    if (m.excluded.length) {
      main.append(h("h2", { text: "Not included" }));
      main.append(h("ul", { class: "excluded" }, m.excluded.map((d) => h("li", { text: `${d.path}: ${d.excluded}` }))));
    }
    if (m.unknown.length) main.append(h("p", { class: "warn", text: "A Feature Designer window's list of open documents cannot be read right now, " +
      "so the update would be refused; try again in a moment. If it stays unreadable: python -m tools.design transaction windows." }));
    main.append(h("p", { class: "limit", text: "Limitation: a document open with unsaved changes in a VS Code window that does not run " +
      "Feature Designer, or in another editor, cannot be detected. VS Code reports that the file changed on disk and asks before " +
      "saving over it; other editors may not, so close the document there first. A Feature Designer window that stops responding " +
      "keeps protecting its documents until it is closed." }));
    const files = m.eligible.map((d) => ({ path: d.path, sha256: d.sha256 }));
    const go = h("button", { type: "button", class: "confirm-update", disabled: !files.length || m.busy,
                             text: files.length ? `Update ${files.length} document${files.length === 1 ? "" : "s"}` : "Update",
                             onclick: () => { result = null; showResult(); go.disabled = true; go.textContent = "Updating…"; post({ type: "confirmUpdate", files, token: m.token }); } });
    main.append(h("div", { class: "actions" }, go, h("button", { type: "button", class: "cancel", text: "Close", onclick: () => post({ type: "close" }) })));
    showResult();
  }

  function record(r) {
    const sec = h("section", { class: "record", "data-id": r.id || "" });
    if (r.error) { sec.append(h("p", { class: "warn", text: `${r.root}: the records could not be read (${r.error}).` })); return sec; }
    const move = r.valid && isMove(r);
    sec.append(h("h2", { text: move ? `Registry move ${r.id}` : `Update ${r.id}` }));
    if (!r.valid) sec.append(h("p", { class: "warn", text: `This record cannot be trusted: ${r.problem}. It is never used to change a document. ` +
      "Until it is removed, no feature document in this repository is written by the design tooling." }));
    else {
      sec.append(h("p", { text: `Prepared ${r.created} (state: ${r.state}${r.action ? `; last action started: ${r.action}` : ""})${r.live ? ". It is STILL RUNNING in another process." : "."}` }));
      if (move) sec.append(h("p", { class: "mode", text: MODE[r.mode] || r.mode }));
      sec.append(h("table", { class: "files" },
        h("thead", {}, h("tr", {}, h("th", { text: move ? "Diagram source (old → new) or registry" : "Document" }), h("th", { text: "Diagrams" }),
                                   h("th", { text: "Current state" }))),
        h("tbody", {}, r.files.map((f) => h("tr", { class: `st-${f.state}` }, h("td", { text: f.rename ? `${f.rename.from} → ${f.rename.to}` : f.path }),
                                                h("td", { text: f.blocks.join(", ") }), h("td", { text: stateText(r, f) }))))));
      if (r.source_changes.length) sec.append(h("p", { class: "warn", text: `Changed since the update was prepared: ${r.source_changes.join(", ")}.` }));
      if (move) sec.append(h("p", { class: "limit", text: "A move is a recoverable transaction, not an atomic multi-file operation: each step is " +
        "checked on disk, and a file or registry in an unexpected state is left alone and reported." }));
    }
    const name = `act-${r.id}`;
    const choices = [];
    const option = (value, label, possible, consequence) => {
      const input = h("input", { type: "radio", name, value, disabled: !possible, class: `choice-${value}` });
      choices.push(input);
      return h("label", { class: possible ? "choice" : "choice disabled" }, input, h("span", { class: "label", text: label }),
               h("span", { class: "consequence", text: consequence }));
    };
    const c = r.complete, u = r.undo;
    const left = (list) => (list && list.length ? ` Left alone (${move ? "in an unexpected state, or occupied" : "they changed since, or are missing"}): ${list.join(", ")}.` : "");
    const back = move && r.mode === "restore";
    const label = move ? { complete: back ? "Complete the move back" : "Complete the move", undo: back ? "Undo the move back" : "Undo the move",
                           abandon: "Abandon the record" }
      : { complete: "Complete the update", undo: "Undo the update", abandon: "Abandon the record" };
    const box = h("fieldset", { class: "decide" }, h("legend", { text: "Choose what to do (nothing is selected):" }),
      option("complete", label.complete, c.possible,
             c.possible ? (move ? `Finishes: ${c.writes.join(", ") || "(nothing left; only the record is removed)"}.${left(c.left_alone)}${c.reason ? ` ${c.reason}.` : ""}`
                               : `Writes the updated text into: ${c.writes.join(", ") || "(none left; only the record is removed)"}.${left(c.left_alone)}`) : c.reason),
      option("undo", label.undo, u.possible,
             u.possible ? (move ? `Puts back: ${u.restores.join(", ") || "(nothing; only the record is removed)"}.${left(u.left_alone)}`
                               : `Restores the original text of: ${u.restores.join(", ") || "(none; only the record is removed)"}.${left(u.left_alone)}`) : u.reason),
      option("abandon", label.abandon, r.abandon.possible, `${r.abandon.effect}. ${move ? "The record" : "The preserved copies"} cannot be recovered afterwards.`));
    const ack = h("input", { type: "checkbox", class: "abandon-ack", disabled: true });
    const ackLabel = h("label", { class: "ack" }, ack, h("span", { text: move ? "I understand that abandoning deletes the move record (and its registry copies) and changes no file."
                                                                               : "I understand that abandoning deletes the preserved original and updated copies and changes no document." }));
    const confirm = h("button", { type: "button", class: "confirm", disabled: true, text: "Confirm" });
    const sync = () => {
      const chosen = choices.find((x) => x.checked);
      ack.disabled = !(chosen && chosen.value === "abandon");
      if (ack.disabled) ack.checked = false;
      confirm.disabled = !chosen || (chosen.value === "abandon" && !ack.checked);
      confirm.textContent = !chosen ? "Confirm" : label[chosen.value];
    };
    choices.forEach((x) => x.addEventListener("change", sync));
    ack.addEventListener("change", sync);
    confirm.addEventListener("click", () => {
      const chosen = choices.find((x) => x.checked);
      if (!chosen) return;
      result = null; showResult(); confirm.disabled = true; confirm.textContent = "Working…";   // the previous outcome is gone
      post({ type: "resolve", root: r.root, id: r.id, action: chosen.value, token: r.token });
    });
    sec.append(box, ackLabel, h("div", { class: "actions" }, confirm));
    return sec;
  }

  function recovery(m) {
    main.replaceChildren();
    main.append(h("h1", { text: "Resolve interrupted update" }));
    if (!m.records.length) main.append(h("p", { class: "none", text: "No interrupted update: nothing to resolve." }));
    else main.append(h("p", { text: "An update of closed feature documents or a registry move did not finish. Each document or diagram source is " +
      "shown with its current state; one that changed since is never overwritten. Closing this panel or dismissing the notification keeps the record." }));
    for (const r of m.records) main.append(record(r));
    if ((m.cleanup || []).length) {                                   // B2b-2a pre-PR review: discoverable, never an operation
      main.append(h("h2", { text: "Cleanup pending" }));
      main.append(h("ul", { class: "cleanup" }, m.cleanup.map((c) => h("li", { text: `${c.folder}: ${c.kind}. It holds nothing and is never carried out ` +
        "again; diagram commands retry its removal, which may stay pending until the cause (for example another program using the folder) is removed." }))));
    }
    main.append(h("div", { class: "actions" }, h("button", { type: "button", class: "cancel", text: "Close", onclick: () => post({ type: "close" }) })));
    showResult();
  }

  // A choice being made is kept: the panel is drawn again only when what it shows changed (a new
  // token, other documents), never just because it was sent again.
  let shown = "";
  window.addEventListener("message", (e) => {
    const m = e.data;
    if (!m || typeof m.type !== "string") return;
    const sig = m.type === "update" ? JSON.stringify([m.token, m.eligible, m.excluded, m.unknown, m.busy])
      : m.type === "recovery" ? JSON.stringify([m.records.map((r) => [r.root, r.id, r.token || r.error]), (m.cleanup || []).map((c) => c.folder)]) : "";
    if ((m.type === "update" || m.type === "recovery") && sig === shown && !m.force) return;
    if (sig) shown = sig;
    if (m.type === "update") update(m);
    else if (m.type === "recovery") recovery(m);
    else if (m.type === "result") { result = m; showResult(); }
  });
  post({ type: "ready" });
})();
