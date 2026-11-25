# Feature Designer (T-97)

A VS Code editor for the feature specifications in `designs/features/`: it shows a feature
formatted, with its Mermaid diagrams drawn, and a **"+"** beside each block (inside the six
sections) to **insert an existing diagram** from a searchable library. The Markdown file stays
the only storage, and every change goes through VS Code's document editing, so undo/redo,
unsaved changes and the other editors (text editor, Mark Sharp) keep working.

Status: Phase 2 (MVP) — diagram insertion only. Tables, code blocks, refresh-on-save and an
installable package come in later T-97 phases. It runs in **development mode**: nothing is
installed, and your VS Code extensions and settings are not changed.

## Set up (once)

From the repository root, in a terminal:

```
.venv\Scripts\python tools\feature-designer\toolchain\bootstrap.py
```

This downloads the pinned Node.js 26.13.0 (Windows x64; its SHA-256 is checked against the
value published by nodejs.org) into `tools/feature-designer/.toolchain/` and installs the
exact dependencies from `package-lock.json` with `npm ci --ignore-scripts` into
`tools/feature-designer/node_modules/`. Nothing global is installed and PATH is not changed;
both folders are ignored by Git. Add `--vscode-test` to also download the pinned VS Code
1.146.0 test build (only needed for the automated GUI tests or `dev.py --isolated`).

## Open it (development mode)

```
.venv\Scripts\python tools\feature-designer\toolchain\dev.py
```

A new VS Code window opens on this repository with Feature Designer loaded from this folder
(`--extensionDevelopmentPath`); its title starts with "[Extension Development Host]". Your
installed extensions, including Mark Sharp, are available as usual. Close that window to
unload it. You can also pass a file: `dev.py designs\features\test1.md`.

Then open a feature: right-click it in the Explorer → **Open With…** → **Feature Designer**
(or, with the file open, the editor title's "…" → Reopen Editor With…).

- **First use:** Feature Designer runs `python -m tools.design` and asks which Python to use.
  It suggests the repository's `.venv` interpreter; choose **Use and Save** to store it in
  your user (machine-level) settings as `featureDesigner.pythonPath`. A value in workspace or
  folder settings is ignored, so a repository cannot choose the program that runs. Change it
  later with **Feature Designer: Select Python Interpreter**. The value must be an absolute path
  to an existing file named like a Python interpreter (`python.exe`, `python3`, `python3.12`,
  `pythonw.exe`); anything else is refused before it runs. If the interpreter cannot start the
  design tooling (for example it exits or never answers), the library shows the reason with
  **Retry** and **Change Interpreter…**.
- **Place a diagram:** hover beside a block, click **+** → **Place Diagram** →
  - **Add Existing Diagram…**: search the library (by name, stable ID, former catalog ID,
    category, source document or owning feature; retired diagrams are not listed), then Enter
    or **Insert**. Only a reference is inserted (the generated block with the stable ID); the
    source is never copied and its owner never changes.
  - **Make New Diagram…**: enter a name; the category is preselected from the section (1 other,
    2 data-model, 3 process, 4 and 5 system-architecture, 6 other) and can be changed; the owner
    is the feature you are editing (**Change owner…** picks another feature, after a
    confirmation naming both). The file name it will get is shown before you create it.
    **Create and Insert** runs `python -m tools.design new diagram` (the same command, lock and
    checks as on the command line), which creates and registers one standalone Mermaid source;
    the reference is then inserted and the source opens beside the view. If the document
    changed meanwhile, the diagram stays created and registered, and a notice shows its ID with
    **Add Existing Diagram…**: click **+** where it should go and it is preselected.

  Insertions are one undoable edit, below the block you hovered. Nothing is saved until you save.
- **Save** as usual (Ctrl+S). When a feature open in Feature Designer is saved,
  `designs/index/feature-index.md` (its Diagrams column) and `designs/index/diagram-index.md`
  (its Used by column) are brought up to date from the saved files, exactly as
  `python -m tools.design index` would write them — unless an index file has unsaved changes
  or cannot be computed, in which case it is left alone and you are told.
- **Edit Diagram (✎)** in a diagram's upper-right corner opens its authoritative source beside
  the view, at its Mermaid block, whether the block names the diagram by its stable ID or by a
  former catalog ID; another feature's diagram opens that feature's source. An architecture
  diagram opens its document with a notice: changes there go through technical-lead's
  documentation workflow, and Feature Designer never writes under `docs/architecture/`. A
  retired or missing diagram is explained instead of opened.
- **Diagrams are drawn from their sources**, as saved on disk (they are redrawn when a source,
  an architecture document or the registry changes). When the copy in the document differs,
  the block says so and nothing is hidden:
  - *out of date* (the source changed, the copy was not edited): drawn from the source; the
    old copy and the text differences can be shown (see the next item for how it is updated);
  - *changed outside its source* (edited by hand, reformatted by another editor, or made
    before fingerprints and different): the authoritative source and the document copy are
    shown side by side, with the text differences; it is never overwritten automatically;
    **Review…** resolves it (below), as does `python -m tools.design reconcile` (see
    [designs/README.md](../../designs/README.md#diagrams));
  - *retired* (E11): a placeholder with **Remove reference** (one undoable edit); *missing*
    (E6/E7) or *unknown* (E1): a placeholder with the problem and its fix. The copy in the
    document can still be shown.
- **When a diagram source changes** (saved in VS Code or changed on disk), out-of-date copies in
  open documents are updated as follows; conflicts are never touched:
  - a document with **no unsaved changes**, shown **only in Feature Designer** (not also in
    Mark Sharp or the text editor), is refreshed automatically as **one undoable edit that is
    not saved**; the status strip offers **Undo**, **Show changes** (against the saved file) and
    **Save**;
  - any other open document is left alone; the status strip says why and offers **Refresh now**
    (one undoable edit, computed on the text as it is then);
  - when more than 5 sources change within 2 seconds (for example a branch switch), nothing is
    refreshed automatically; **Refresh now** is offered instead;
  - **closed documents** (not open in any editor of this window) are offered in the status strip:
    **Update…** lists each document, the diagrams refreshed and the conflicts left alone, and
    the documents left out (open in this window, open in another Feature Designer window, or
    part of an interrupted update). Confirming writes them on disk as **one update: all of them,
    or none**. If anything changed since the list was shown, nothing is written and the new
    list is shown. Also **Feature Designer: Update Closed Documents…**;
  - **Feature Designer: Check Diagram Sources** checks again when a change was missed.
- **Review…** on a conflicting block shows both versions and the differences, then:
  - **Discard manual change** restores the generated copy here (one undoable edit; not saved;
    the source is not changed);
  - **Apply to source** (feature-owned diagrams only; never architecture diagrams) writes the
    copy into its source and saves it, then updates the block (not saved). It is refused if the
    source has unsaved changes, and if the document or the source changed since the review
    (review again). When it would replace changes made in the source, you must tick that
    explicitly. Ctrl+Z in the document reverts only the block; the saved source change is undone
    in the source file. If the source is saved but the block cannot be updated, you are told
    that it was only partly done, with **Update the block now** and **Restore the original
    source**; the original is kept (outside the repository, in VS Code's storage for this
    extension) until the operation is resolved, also across restarts (**Feature Designer:
    Resolve Interrupted Apply to Source**).
- **An interrupted update** (for example VS Code or the computer stopped part-way) keeps a
  record in `designs/diagrams/.transactions/` (ignored by Git) with every original and updated
  copy. You are told at the next start, and **Feature Designer: Resolve Interrupted Update**
  shows each document's current state and what each action would do; nothing is selected for
  you:
  - **Complete the update** writes the updated text into the documents not yet updated; it is
    refused if a diagram source or the registry changed since (then use Undo and update again);
  - **Undo the update** restores the original text of the documents already updated;
  - **Abandon the record** removes the record and its copies and changes no document; it needs
    its own acknowledgement. A record that cannot be trusted (damaged) can only be abandoned.
  - A document that changed since, or is missing, is never overwritten; one open in an editor
    must be closed first. Dismissing the notification or closing the panel keeps the record.
    Until it is resolved, the documents it holds are not refreshed or edited by Feature
    Designer or the design tooling (the strip says so), and `check` reports it (E16).
- **Documents open in other windows.** Each Feature Designer window lists the feature documents
  it has open (and whether they have unsaved changes) in
  `designs/diagrams/.transactions/windows/`, every 5 seconds; an update never writes a document
  a window that may still be running lists. A VS Code window that does not run Feature Designer
  (another installation, Restricted Mode) or another editor cannot be detected: if one has the
  file open with unsaved changes, it reports that the file changed on disk and asks before
  saving over it.
- **Status strip:** stays visible under the toolbar while you scroll: how many diagrams are out
  of date, in conflict or have a problem, with **Previous** / **Next** to go to each.
- **Restricted Mode:** in an untrusted workspace Feature Designer shows a notice only; it
  runs no scripts and no Python. (VS Code does not enforce the manifest's trust setting for
  development-mode extensions, so this is checked at runtime.)
- **Feature Designer: Show Log** shows what it did (Python process, insertions, new diagrams,
  index updates).

`--isolated` opens the pinned VS Code test build with an empty profile instead
(`tools/feature-designer/.toolchain/profile`), for a clean check without your extensions.

## Using it with Mark Sharp and the text editor

All three editors work on VS Code's single shared document for the file (Mark Sharp is a
text-based custom editor too), so unsaved changes made in one appear in the others, and
switching editors loses nothing. Tested in the GUI tests (real Mark Sharp 1.13.0):

- typing in the text editor or Mark Sharp shows up in Feature Designer immediately, unsaved;
- inserting a diagram while the file is also open in Mark Sharp asks first (a modal warning
  names Mark Sharp; the Designer also shows a banner), because text you are still typing in
  Mark Sharp may not have reached the shared document yet: pause typing there before inserting;
- after an insertion, if another editor's change removes the inserted block, Feature
  Designer warns you (your own Undo/Redo does not trigger this);
- **Mark Sharp reformats generated blocks when it writes the file**: in the test it added
  blank lines and removed indentation inside generated diagram blocks and re-padded the
  generated Related features table. Your own text was unchanged. `check` reports such blocks,
  Feature Designer shows a banner, and `python -m tools.design index` regenerates them
  exactly. Run `index` (and `check`) before committing, as the designs README already says.

## Tests

PowerShell, from the repository root:

```
$env:FEATURE_DESIGNER_TEST_PYTHON = "$PWD\.venv\Scripts\python.exe"
tools\feature-designer\.toolchain\node-v26.13.0-win-x64\node --test tools\feature-designer\test\unit
tools\feature-designer\.toolchain\node-v26.13.0-win-x64\node tools\feature-designer\test\gui\e2e.js
```

(The GUI test needs `bootstrap.py --vscode-test` once, and Mark Sharp 1.13.0 installed for its
interoperability checks.)

The unit tests cover edit application (identical to the Python side, CRLF, end of file,
stale edits refused), the Python process (restart, timeout, no orphan process) and the
interpreter rules. The GUI test runs the pinned VS Code test build with an isolated profile
on a throwaway fixture repository (`test/gui/.run/`, ignored by Git), drives it with real
pointer and keyboard input, and loads a small test-only helper extension
(`test/gui/helper/`, never part of Feature Designer). It copies your installed Mark Sharp
1.13.0 into the test profile (read-only) for the interoperability checks.

## How it is built

- `src/extension.js` — the custom text editor (`featureDesigner.editor`, priority "option").
- `src/bridge.js` — one long-running `python -m tools.design designer --serve` (JSON lines).
- `src/edits.js` — applies the tooling's proposed edits only to the exact text they were
  computed from (SHA-256 and line count); otherwise the edit is refused as stale.
- `src/python.js` — interpreter selection (machine-level setting, confirmed suggestion).
- `media/` — the webview: rendering (markdown-it, DOMPurify, Mermaid in strict mode), the
  "+" menu and the library. Content-Security-Policy: scripts only with a per-load random
  nonce, no remote content, no command links.
