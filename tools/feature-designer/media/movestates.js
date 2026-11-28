/* Feature Designer: how the Resolve Interrupted Update panel words the states of a record's files (shared by
 * the panel, media/updates.js, and the unit tests). Version 1 records (closed-document updates, PR B2b-1) list
 * documents; version 2 records (registry moves, PR B2b-2a/2b) list renames, judged only by where the source's
 * exact bytes are, and the registry, judged by its bytes. A Move back (mode "restore") goes the other way: its
 * "new" path is the registered path the source returns to, and it never writes the registry. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.FDMoveStates = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const STATE = { updated: "Updated", original: "Not updated (original)", changed: "Changed since: left alone", missing: "Missing: left alone" };
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
  const REGISTRY = "designs/diagrams/registry.yml";
  const isMove = (r) => !!r && r.tool === "registry-move";

  /** A row of a record (or of a result) for a move of `mode` ("move", "adopt", "restore"; null: not a move). */
  function rowText(f, mode) {
    if (f.rename) return ((mode === "restore" ? BACK_STATE : MOVE_STATE)[f.state] || f.state) +
      (f.occupied && f.occupied.length ? ` (occupied by something else: ${f.occupied.join(", ")})` : "");
    if (mode || f.path === REGISTRY) return REGISTRY_STATE[f.state] || STATE[f.state] || f.state;
    return STATE[f.state] || f.state;
  }
  /** A row of a record as shown in the panel. */
  const stateText = (r, f) => rowText(f, isMove(r) ? r.mode : null);
  /** A row of a Complete/Undo result: worded with the mode of the record the action was taken on. */
  const resultState = (f, mode) => rowText(f, mode || null);

  return { STATE, MOVE_STATE, BACK_STATE, REGISTRY_STATE, MODE, REGISTRY, isMove, stateText, resultState };
});
