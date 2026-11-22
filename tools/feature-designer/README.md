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
- **Insert a diagram:** hover beside a block, click **+**, **Insert Existing Diagram**, search
  (by name, ID, source document or owning feature), then Enter or **Insert**. The block is
  inserted below the block you hovered, as one undoable edit. Nothing is saved until you save.
- **Save** as usual (Ctrl+S). When a feature open in Feature Designer is saved,
  `designs/index/feature-index.md` (its Diagrams column) and `designs/index/diagram-index.md`
  (its Used by column) are brought up to date from the saved files, exactly as
  `python -m tools.design index` would write them — unless an index file has unsaved changes
  or cannot be computed, in which case it is left alone and you are told.
- **Edit source** on a diagram opens its authoritative Mermaid source beside it, whether the
  block names the diagram by its stable ID or by an alias (a former catalog ID).
- **Generated blocks** carry a fingerprint in their start marker (diagram registry, T-97 PR A).
  A block changed outside its source (for example reformatted by another editor) is shown in a
  banner and never overwritten automatically; resolve it with `python -m tools.design reconcile`
  (see [designs/README.md](../../designs/README.md#diagrams)).
- **Restricted Mode:** in an untrusted workspace Feature Designer shows a notice only; it
  runs no scripts and no Python. (VS Code does not enforce the manifest's trust setting for
  development-mode extensions, so this is checked at runtime.)
- **Feature Designer: Show Log** shows what it did (Python process, insertions, index updates).

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
