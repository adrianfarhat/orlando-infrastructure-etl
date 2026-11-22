# Diagram Library (proposed)

> **PROPOSED — approved design (2026-11-22), not implemented.** Nothing on this page
> is built. In the terms of the
> [implementation-status legend](conventions.md#1-implementation-status-legend), every
> component described here is `planned`; none is `unverified` or `verified`. The built
> current state is described in the other `docs/architecture/` documents and in
> [designs/README.md](../../designs/README.md). Where this page states what exists
> today (section 2), it says so explicitly. Decisions U1–U12 are **still open**
> ([section 14](#14-open-decisions-u1u12)); the statements that depend on them are
> marked "(decision Un)".

The diagram library gives every diagram in the project (architecture diagrams and
feature diagrams, code-first Mermaid and visual draw.io) one stable ID, one
authoritative source document, one owner and one registry entry, and one workflow for
finding, placing, editing and maintaining it.

- Task status, scope, priority, dependencies, delivery order and acceptance criteria
  live on the T-97 card in [GitHub Project #1](https://github.com/users/adrianfarhat/projects/1)
  (private); decisions are recorded in [designs/DECISIONS.md](../../designs/DECISIONS.md)
  and verification evidence in [docs/agents/task-board.md](../agents/task-board.md).
- Related pages: [conventions.md](conventions.md) (diagram legend, diagram types,
  docs workflow), [system-architecture.md](system-architecture.md),
  [designs/README.md](../../designs/README.md) (diagram blocks and IDs as built today).
- This page contains no Mermaid diagram on purpose: the architecture catalog reads every
  Mermaid block in `docs/architecture/`, and the set of 14 architecture diagrams must
  stay unchanged. Sketches are plain text.

## 1. Principles

1. **Every diagram is its own source document**, even when it is shown inside another
   document. A feature or architecture document never holds a diagram's authoritative
   source; it holds a reference (the stable ID) and a generated copy or image for
   portable rendering.
2. **The stable ID is the identity.** File names are descriptive and may change; the ID
   never changes and is never reused.
3. **One library, one registry, one workflow** for both formats: Mermaid (code-first)
   and draw.io (visual-first). The format decides which editor opens.
4. **Reuse never copies.** A diagram used by several documents has one source and one
   owner.
5. **Existing diagrams behave as if made with Make New Diagram.** Each gets a registry
   entry and, after an approved migration, its own source document. Nothing is
   converted between formats.
6. **Unsaved edits are never overwritten.** Generated content is the only thing tools
   rewrite, and never in a document with unsaved changes.

## 2. What exists today

Inventory as of 2026-11-22, `main` at `56e708f`. This section describes the current
state, not the design.

| Where | Diagrams | Stored as | Referenced elsewhere |
|---|---|---|---|
| `docs/architecture/conventions.md` | 1 | embedded Mermaid | no |
| `docs/architecture/database-schema.md` | 3 | embedded Mermaid | no |
| `docs/architecture/etl-workflow.md` | 5 | embedded Mermaid | no |
| `docs/architecture/system-architecture.md` | 5 | embedded Mermaid | no |
| `docs/agents/development-status.md` | 7 | embedded Mermaid (planning, not in the catalog) | no |
| Feature specifications (`designs/features/`, uncommitted user files) | 2 | the template's placeholder flowchart, embedded, unchanged | no |
| `designs/templates/` | 2 | examples in templates (not diagrams) | no |
| Standalone diagram source documents in the repository | 0 | — | — |

- The 14 architecture diagrams have positional catalog IDs
  (`<document>/<heading anchor>`, T-94 Phase 2 decision 2 in
  [DECISIONS.md](../../designs/DECISIONS.md)). T-96 diagram markers and the
  [architecture index](../../designs/index/architecture-index.md) use them. No two
  diagrams are duplicates.
- Built and recorded in the [Evidence log](../agents/task-board.md#evidence-log): T-96
  diagram blocks (marker pair, generated caption and Mermaid copy, `check` and
  `index`); T-97 Phase 1 feature-owned diagram IDs `FD-nnnn-D<n>` that are never
  reused (Git history allocator) and the Feature Designer JSON interface; T-97 Phase 2
  Feature Designer MVP (menu item "Insert Existing Diagram", library, Edit source).
- Not present today: a diagram registry, `designs/diagrams/`,
  `docs/architecture/diagrams/`, any `.drawio.svg` file, and a repository
  `.gitattributes`.

## 3. Owners, IDs and the registry

### 3.1 Owner kinds and IDs

| Owner kind | Owner reference | Diagram ID | Allocation |
|---|---|---|---|
| `feature` | a feature ID, for example `FD-0001` | `FD-0001-D<n>` (T-97 Phase 1, unchanged) | Phase 1 allocator |
| `document` | a repository document that is not a feature, for example `docs/architecture/system-architecture.md` | `AD-<nnnn>` (architecture/document diagram) (decision U1) | The same never-reuse allocator: working tree, Git history and registry |

- The ID prefix must match the owner kind.
- **Aliases.** A registry entry may list aliases. A former catalog ID becomes a
  permanent alias of its `AD-` ID and keeps resolving forever (decision U4).
- IDs and aliases are globally unique: an alias can never be issued as a new ID, and an
  ID is never reused, including after retirement.

### 3.2 Registry

One registry, `designs/diagrams/registry.yml`, is authoritative for identity, owner,
format, category, title, path and lifecycle. It never holds diagram content. It is
written only by `python -m tools.design` commands (new diagram, `registry relink`,
`registry retire`, `registry adopt`).

```text
version: 1
diagrams:
  - diagram_id: AD-0013             # first key on its own line: the Git-history ID scan reads it
    title: One map pan, step by step
    owner: {kind: document, ref: docs/architecture/system-architecture.md}
    format: mermaid-md
    category: sequence
    path: docs/architecture/diagrams/system-architecture_sequence_one-map-pan.md
    aliases: [system-architecture/3-one-map-pan-step-by-step]   # former catalog ID
    status: active                  # active | retired
    created: 2026-11-22
    created_from: null              # or {diagram: <ID>, commit: <hash>, via: <method>}
  - diagram_id: FD-0001-D1
    title: One map pan
    owner: {kind: feature, ref: FD-0001}
    format: drawio-svg
    category: system-architecture
    path: designs/features/diagrams/test1_system-architecture_one-map-pan.drawio.svg
    aliases: []
    status: active
    created: 2026-11-22
```

Rules:

- **Authority.** The registry decides identity, owner, format and path. The in-file
  identity (front matter, or the draw.io root property) is compared with the registry
  and never overrides it.
- IDs and aliases are globally unique; the ID prefix matches the owner kind.
- Paths are repository-relative with `/` separators and must exist with exact case.
- Titles are kept in the registry and, for `mermaid-md`, also in the front matter;
  `check` reports a mismatch.
- **Retirement** sets `status: retired` and `retired: <date>`; the entry stays and the
  ID is never issued again (section 7.6).
- The category list is part of the registry schema (`version: 1`). Adding a category is
  a controlled schema change (a DECISIONS entry, the list in the tooling, tests);
  removing or renaming one requires a version bump and a migration command.
- A generated `designs/index/diagram-index.md` lists every diagram from the registry,
  the catalog and the reference markers, with the columns ID, title, format, category,
  owner, status, path and used by. It is never edited by hand; `index --check` reports
  it stale.

## 4. Formats

One table in the tooling drives validation, resolution, rendering and the editor.

| `format` | Extension | Kind | Editor | Rendering in Markdown | In-file identity |
|---|---|---|---|---|---|
| `mermaid-md` | `.md` | code | text editor, at the Mermaid block | Mermaid copy (T-96) | front matter (`diagram_id`, owner, `title`; owner field for documents: decision U10) |
| `drawio-svg` | `.drawio.svg` | visual | draw.io (pinned, section 10) | image link | properties on the diagram's root cell (owner property for documents: decision U10) |
| `mermaid-embedded` | none (a block inside a document) | code, **transitional** | text editor, at the block in the owning document | the document itself | located by owner document + heading anchor + ordinal (renamed headings: decision U11) |
| `mermaid-mmd` | `.mmd` | code, **reserved** | not accepted yet | Mermaid copy | `%% diagram_id:` lines |
| `dbml` | `.dbml` | code, **reserved** | not accepted yet | to be designed | to be designed |

- **`mermaid-md`**: a standalone `.md` source document with front matter and exactly one
  Mermaid block (today's diagram file format, unchanged).
- **`drawio-svg`**: one diagram per file and **exactly one page**, because the saved
  image shows whichever page was active when saving. The ID is stored as a property on
  the diagram's root cell (`<UserObject id="0" fd_diagram_id fd_feature_id>`), visible in
  draw.io's Edit Data; this was the only placement tested that survived repeated draw.io
  saves (an attribute in the SVG image part is lost on the first save; an attribute on
  `<mxfile>` survives but is undocumented and is not relied on). New files are created
  with a white background, which reaches the exported image and keeps contrast in dark
  themes. The extension always compresses the embedded graph, so readable diffs need
  the diff helper (section 11).
- **`mermaid-embedded`** exists for adoption only (stage M0, section 12). It is
  read-only to tools and disappears when the diagram is extracted (stage M1).
- **Reserved** formats are not accepted until a later, separately approved design.
  Adding one means adding a table row and a reader, with no registry migration.
- The owner fields of the in-file identity for `document`-owned diagrams are open
  (decision U10). Feature-owned diagrams keep `feature_id` (front matter) and
  `fd_feature_id` (draw.io root property). Moving architecture diagrams to draw.io is
  not part of this design and needs a plan of its own.

## 5. Naming and directories

### 5.1 File names

```text
<owner-slug>_<category>_<diagram-name>.<ext>
```

- **`owner-slug`**: the owning feature's file name without `.md` (for a parent feature,
  its folder name), or the owning document's file name without `.md`
  (`system-architecture`).
- **`category`**: from the controlled list `system-architecture`, `data-model`,
  `process`, `sequence`, `state`, `ui`, `legend`, `other` (decision U7). Make New
  Diagram preselects a category from the section where "+" was used and lets the user
  change it.
- **`diagram-name`**: from the title, with the T-94 file-name rules (lower case,
  hyphens, Unicode dashes become `-`).
- Example: "One Map Pan" made in `designs/features/test1.md` becomes
  `test1_system-architecture_one-map-pan.md` (Mermaid) or
  `test1_system-architecture_one-map-pan.drawio.svg` (visual).
- Collisions are refused. Names are made once, at creation, and are never parsed for
  identity. A rename (`registry relink`) never changes the ID. The naming rule applies
  to new names only: a moved file keeps any valid name.

### 5.2 Directories

The source lives with its owner.

```text
designs/
  diagrams/
    registry.yml                       the single registry
  features/
    diagrams/                          sources owned by standalone features
    <parent>/diagrams/                 sources owned by a parent feature folder
  index/
    diagram-index.md                   generated from the registry
  templates/
    visual-diagram.drawio.svg          Make New Diagram's starter file (visual)
    diagram.md                         unchanged (Mermaid)
docs/architecture/
  diagrams/                            sources owned by documents (technical-lead)
.gitattributes                         *.drawio.svg diff=drawio -merge
```

- Whether a source may later be moved to another location is decision U12; the
  recommendation keeps each source in the directory of its owner kind.
- Document-owned sources in `docs/architecture/diagrams/` are owned and edited by
  technical-lead, like the documents themselves.

### 5.3 Reuse by several features

- The source keeps its owner's name and location.
- Other features insert a reference (a marker with the ID). Nothing is copied, renamed
  or moved, and the owner is unchanged; the library shows "used by".
- Changing a diagram's owner is a separate, explicit command, not part of this design.

## 6. References, resolution and rendering

### 6.1 Canonical ID references

- A referencing document holds the T-96 marker pair. **The canonical reference is the
  start marker, which holds only the ID** (or an alias):

  ```text
  <!-- diagram:start FD-0001-D3 -->
  ...generated lines...
  <!-- diagram:end -->
  ```

- **Everything between the markers is generated** from the registry and never read
  back. A path inside a block exists only because ordinary Markdown viewers need one;
  no command reads a path out of a block to find a diagram.
- Former catalog IDs in existing markers keep resolving through aliases. `index` may
  rewrite a marker to the new ID only when that is approved (decision U4; the
  recommendation is no automatic rewrite).
- Hand-written image links to a `*.drawio.svg` outside a diagram block (under
  `designs/`) are reported (E13), because a bare path cannot follow a move.

### 6.2 Resolving an ID to a path

One function, `resolve(ID)`, serves `check`, `index`, the library, insert, refresh and
Edit Diagram, so they can never disagree:

1. Look up the ID, or an alias, in the registry. Before stage M0, a catalog ID is still
   found in the architecture catalog. A missing, duplicated or colliding ID or alias is
   an error (E1, E2, E8). Nothing is guessed.
2. Take the registry `path` and check that it exists with exact case (E6 if the file is
   found elsewhere, E7 if not). A `mermaid-embedded` entry is located by owner
   document, heading anchor and ordinal; what happens when that heading is renamed
   before M1 is decision U11.
3. Check the file's in-file identity against the registry (E3 on mismatch).
4. For a referencing document at `D`, the generated link is
   `posixpath.relpath(path, dirname(D))`, percent-encoded.

The JSON interface gains a read-only `resolve` operation; its response version stays 1
and fields are only added.

### 6.3 Keeping generated paths right after moves and renames

1. `registry relink` changes one registry field, `path` (or `title` with `--title`),
   under the lock with compare-and-swap (section 8.1). No document is touched by this
   step.
2. Every block for that ID is now stale, because its generated content differs from
   what `resolve` produces. This is detected by the whole-block comparison T-96 already
   uses.
3. Refreshing:
   - **open documents without unsaved changes**: Feature Designer applies a guarded
     refresh edit (base SHA-256, line count and document version must match) that
     rewrites only the lines between that ID's markers;
   - **open documents with unsaved changes**: an "out of date" notice with a Refresh
     button; nothing is written until the user clicks;
   - **closed documents**: `python -m tools.design index`, which rewrites only the lines
     between markers, in files without a structural problem (T-96 rule).
4. Until refreshed, `check` reports E14, and Feature Designer still shows the right
   diagram, because it resolves by ID, not by the stale path.

### 6.4 Rendering in Markdown

| Where | Content between the markers |
|---|---|
| Feature documents, `mermaid-md` | Caption (title linked to the source, ID, "generated copy; edit the source") plus the Mermaid copy, byte-identical to T-96 output |
| Feature documents, `drawio-svg` | Caption plus `![<title>](<relative path>)`; stale only when the title or path changes, never when content changes |
| Architecture documents (after stage M1) | The Mermaid copy only, with an HTML comment naming the ID and source, so the rendered page is unchanged (decision U3) |

The Mermaid copy keeps the T-96 rule that blank source lines are written as `%%`, so the
block stays contiguous.

### 6.5 Rendering in Feature Designer

- Every diagram block renders **from its resolved source**, not from the Markdown copy.
- Every diagram block carries an **Edit Diagram** button in its upper-right corner.
- If the Markdown copy differs from the source, a small "copy out of date" badge is
  shown.
- Visual images are shown through webview URIs with `?v=<mtime>`; `designs/` is added
  to the webview's local resource roots (read-only). The content security policy is
  unchanged, and SVG is shown only through `<img>`.

```text
+--------------------------------------------------- [Edit Diagram] -+
|                                                                    |
|      diagram rendered from its resolved source                      |
|                                                                    |
+--------------------------------------------------------------------+
  One map pan · AD-0013 · source: docs/architecture/diagrams/...   [copy out of date]
```

## 7. Workflows

### 7.1 + → Place Diagram → Add Existing Diagram

- The searchable library, under a Place Diagram submenu, in three groups:
  architecture/document diagrams; feature diagrams by owner, with format badges; and
  problems (missing, ambiguous, moved or retired diagrams), shown but not insertable.
- Inserting adds a reference by ID through the existing guarded `insert`. Nothing is
  copied, and the owner is unchanged.

### 7.2 + → Place Diagram → Make New Diagram

1. The dialog asks for a name, a category (preselected from the section) and a format
   (Mermaid or visual draw.io; DBML shown as "later").
2. The owner is the open feature, shown read-only. Another owner only through the
   explicit **Change owner…** action, which offers only valid, existing owners and asks
   for a confirmation naming both.
3. Feature Designer runs `python -m tools.design new diagram` (owner, title, format,
   category). It creates the source document and the registry entry safely
   (section 8.1) and returns JSON. It never stages, commits or pushes.
4. It inserts the reference with the guarded `insert`. If the document changed in the
   meantime, the insert is refused; the diagram stays complete and registered, appears
   in the library, and the user is told to place it again.
5. It opens the source in its editor: the text editor at the Mermaid block, or the
   pinned draw.io beside the document (subject to section 10).

### 7.3 Edit Diagram

- Resolve the ID (or alias) through the registry, then open the authoritative source in
  the format's editor:
  - `drawio-svg`: `vscode.openWith(uri, "hediet.vscode-drawio-text")`;
  - `mermaid-md`: the text editor at the Mermaid block;
  - `mermaid-embedded` (transitional): the owning document at its block.
- A diagram owned elsewhere opens its original source, never a copy.
- A missing, ambiguous, moved or retired diagram shows its catalogued error with the
  fix (section 9).

### 7.4 Saving a source (sync)

A debounced file watcher covers `designs/**/*.drawio.svg`, the registered `mermaid-md`
sources and `registry.yml`.

| Event | Feature Designer | Markdown written? |
|---|---|---|
| A source is saved (either format) | Every open view re-renders that diagram at once, from source | Visual: never (the image link points at the source). Mermaid: copies refreshed per decision U5, never in a document with unsaved changes |
| Title or path changed (relink) | Marks captions and links out of date | Documents without unsaved changes only (section 6.3) |
| Registry changed outside Feature Designer | Reloads the library and re-resolves | No |

- For Mermaid copies, decision U5 chooses between refreshing automatically after the
  save (only the generated lines, listed in a notification) and refreshing on one
  click. Documents with unsaved changes get a banner and a Refresh button.
- `index` covers everything, including closed documents; `check` reports any stale
  copy.
- Feature Designer never writes a diagram source.

### 7.5 Rename or move (relink)

- **References never break**, because documents reference IDs, not paths.
- **Inside VS Code** (Explorer rename or move), Feature Designer asks "Update the diagram
  registry?" each time. Yes runs `registry relink <ID> <new path>`, which checks that
  the file's in-file identity equals the ID, updates `path` under the lock with
  compare-and-swap, and refreshes generated links as in section 6.3.
- **Outside VS Code** (Git, file explorer), `check` and `resolve` match the missing
  registered path to the unregistered file with the same in-file ID and report it as
  moved, with the exact `registry relink` command (E6).
- **Title only**: `registry relink --title` updates the registry title (and the
  `mermaid-md` front matter); captions are refreshed as above.
- The owner never changes on a move. Which target locations `relink` accepts for each
  owner kind is decision U12.
- Re-pointing a transitional `mermaid-embedded` entry after its heading is renamed is
  decision U11.

### 7.6 Retire

- `registry retire <ID>` first lists every reference: diagram blocks, hand-written
  image links and `created_from` links.
- It requires explicit confirmation (`--confirm` on the command line; a modal listing
  the references in Feature Designer).
- It then sets `status: retired` and `retired: <date>`. Deleting the file is a separate,
  optional step.
- Remaining references render a retired-diagram notice and are reported (E11). The ID is
  never issued again.

### 7.7 Extract to diagram source (features)

A feature document that contains a real embedded Mermaid diagram gets an explicit
**Extract to diagram source** action, per diagram and confirmed by the user. It creates
the source, registers it and replaces the block with a reference. Until warning levels
exist (T-97 Q4), `check` reports embedded diagrams in features as advisory.

## 8. Safety

### 8.1 Safe creation

`new diagram` runs these steps, in order, under a registry lock:

1. **Take the lock.** Create `designs/diagrams/.registry.lock` exclusively (with process
   ID and time; git-ignored). If it exists, refuse with "another diagram command is
   running". A stale lock older than 10 minutes is reported, never broken
   automatically.
2. **Read and validate the registry and remember its SHA-256.** Refuse if the registry
   has problems.
3. **Allocate the ID** with the never-reuse allocator, now also counting registry IDs,
   aliases and decoded draw.io IDs.
4. **Create the source exclusively.** Write a temporary file in the same folder, then
   link it to the final name with an operation that fails if the name exists. The file
   appears whole or not at all and is never overwritten.
5. **Update the registry by compare-and-swap.** Write the new registry to a temporary
   file, check that the registry still has the remembered SHA-256, then replace it
   atomically (`os.replace`). A round-trip YAML writer (`ruamel.yaml`) keeps comments and
   order and appends the entry.
6. **Roll back on any failure in steps 4–5**: delete only the file this command created
   in step 4, leave the registry as it was, release the lock and exit with code 2,
   saying what happened.

The result is all or nothing: the file and its entry, or neither. A crash between
steps 4 and 5 can leave an unregistered file, which `check` reports with
`registry adopt <path>` as the fix. It never leaves a registry entry without its file.
`relink` and `retire` use the same lock and compare-and-swap.

### 8.2 Never overwriting unsaved edits

- **Feature Designer** edits a document only through a single, undoable WorkspaceEdit
  carrying the base SHA-256, line count and document version. It never edits a document
  with unsaved changes automatically.
- **`index`** writes files on disk. If one of them is open with unsaved changes, VS Code
  does not discard them: it reports that the file changed on disk when the user saves.
  Feature Designer's Refresh button is the recommended path for open documents; the
  README asks users to save open documents before running `index`.
- **Diagram sources are never written by Feature Designer, `index` or `refresh`.**
  draw.io writes `.drawio.svg`; the user writes `mermaid-md`; only `new diagram` creates
  sources, and only exclusively.

## 9. Error catalogue

Every message names the file and line where possible, and the fix. Exit codes are
unchanged from T-97 Phase 1 (decision 4 in [DECISIONS.md](../../designs/DECISIONS.md)).
`<ID>` stands for a feature diagram ID (`FD-0001-D3`) or a document diagram ID
(`AD-0013`); "alias" means a former catalog ID.

| Code | Situation | Message (shortened) |
|---|---|---|
| E1 | ID or alias referenced, found nowhere | `AD-0099 is not in the registry as an ID or an alias` (before M0: "or the architecture catalog"), plus "did you mean" |
| E2 | Same ID, or same alias, twice in the registry | `FD-0001-D3 is registered twice (lines 12 and 31)` / `system-architecture/3-one-map-pan-step-by-step is an alias of two entries (lines …)` |
| E3 | The registered file's in-file identity differs | `…x.drawio.svg holds FD-0001-D4 but the registry maps FD-0001-D3 to it` |
| E4 | Unregistered visual file whose ID belongs to another path | `…copy.drawio.svg is a copy of FD-0001-D3 (…original): create diagrams with Make New Diagram` |
| E5 | Unregistered visual file with an unknown or no ID | `…x.drawio.svg is not registered: run registry adopt …` |
| E6 | Registered path missing, file found elsewhere | `AD-0013 moved to …: run registry relink AD-0013 …` |
| E7 | Registered path missing, not found (for `mermaid-embedded`: the block is not found at its owner document, heading and ordinal; decision U11) | `FD-0001-D3's source … does not exist` |
| E8 | An ID and an alias collide (for example a former catalog ID issued or registered as an ID) | `… is both a registry ID and an alias of AD-0010` |
| E9 | Owner does not exist, or the ID prefix does not match the owner kind | `FD-0002-D1 is owned by FD-0001 in the registry: the ID prefix must be the owner's` / `AD-0003 is owned by a feature: AD- IDs belong to document owners` |
| E10 | Visual file has more than one page, no decodable graph, or a transparent background | a specific message for each |
| E11 | Reference to a retired diagram | `FD-0001-D3 was retired on …` |
| E12 | Lock held, or registry changed during a command | `another diagram command is running` / `the registry changed while creating …; nothing was written` |
| E13 | Hand-written image link to a `.drawio.svg` outside a diagram block | `…md line 40 links …x.drawio.svg directly: use a diagram block (FD-0001-D3) so the reference survives moves` |
| E14 | A generated path in a block no longer matches the registry | `stale image path in the FD-0001-D3 block of …md: expected …; run index or Refresh` |

## 10. Visual editor rules (draw.io)

- **Reviewed version.** `hediet.vscode-drawio` **1.19.261106065**, VSIX SHA-256
  `740eb40aa35478782154a8aac9c41f2f5872d9ef473f9c2749ae9b212556d397`.
- **Development profile and automated tests** use exactly that version, fetched and
  hash-verified by a toolchain script, with auto-update off.
- **Installation scope.** draw.io is installed only in the isolated Feature Designer
  development profile until the hands-on test of the whole workflow passes. Installing
  it in a normal VS Code profile is a later, separate request.
- **Other versions in normal use** get a compatibility warning, not a permanent refusal:
  "Reviewed with 1.19.261106065; you have X. Layout and metadata preservation were
  verified only for the reviewed version." with Open anyway / Cancel, shown once per
  session and version.
- **Missing extension.** Feature Designer explains how to install it and opens nothing
  else.
- **Online mode is refused (R1).** If `hediet.vscode-drawio.offline` is not `true`,
  Edit Diagram and Make New do not open draw.io. The message explains that online mode
  loads the editor from diagrams.net and gives the exact fix: set

  ```text
  "hediet.vscode-drawio.offline": true
  ```

  in the user settings of the profile (Settings → search "drawio offline" → tick
  "Offline"). Make New still creates the diagram file; only opening is refused.
- **Never installs or upgrades the extension.** Feature Designer only reads its version.

## 11. Diffs, merges and `.gitattributes`

- **`.gitattributes`**: one line, scoped to visual diagrams only:

  ```text
  *.drawio.svg diff=drawio -merge
  ```

- **Diff helper**: `python -m tools.design drawio-diff <file>` is the textconv command
  (stable, pretty-printed graph; editor noise dropped). In a test it turned an
  unreadable 13-line diff into the two real changes.
  `python -m tools.design setup-git-diff` writes the local `diff.drawio.textconv`
  setting; it runs only when the user runs it, and without it Git shows its normal diff.
  The ID allocator keeps reading history with `--no-textconv`.
- **Measured merge behaviour** (scratch repository, real draw.io files, both branches
  editing one diagram):

| Situation | Default text merge | With `*.drawio.svg -merge` |
|---|---|---|
| Both branches edited the diagram (merge or rebase) | Conflict reported, but conflict markers are written into the SVG, so it no longer opens or renders until fixed by hand | Conflict reported (`UU`, exit 1); the file stays a valid diagram (the current branch's version); the other version is available with `git checkout --theirs` |
| Only one branch edited it | Clean merge | Clean merge (`-merge` applies only when both sides changed the file) |
| Silent combination of two people's edits | Never (the compressed graph is one line, so it always conflicts) | Never |

Consequences:

- Git never combines two people's edits to one diagram (also true without the
  attribute). The user chooses one version (`git checkout --ours` or `--theirs`) and
  redoes the other change in draw.io; `drawio-diff` on the two versions shows what it
  was.
- The attribute is not global: all other files merge exactly as today.
- GitHub's merge button reports the same conflict and never merges it automatically.
- `-text` is **not** added: it would stop Windows line-ending conversion, which is
  harmless here (draw.io writes LF), and the Gate 2 decision was "no line-ending
  attributes".

## 12. Adoption and migration of existing diagrams

Proposal only: nothing runs without approval, and the order is decision U8.

### 12.1 Stage M0: adopt in place (no document changes)

- One registry entry per architecture diagram: an `AD-nnnn` ID, the current catalog ID
  as an alias, and format `mermaid-embedded` pointing at the current block.
- Every architecture diagram is then in the library, with a stable ID and an Edit
  Diagram target.
- The 14 documents and their rendering are unchanged; the architecture index lists the
  new IDs beside the aliases.

### 12.2 Stage M1: extract per document

Done by technical-lead, one document at a time, each separately approved. For each
diagram:

1. Create `docs/architecture/diagrams/<doc>_<category>_<name>.md` holding exactly the
   current Mermaid lines (byte-identical).
2. Switch the registry entry to `mermaid-md` with the new path.
3. Replace the embedded block in the document with the marker pair plus the generated
   Mermaid copy (with the HTML comment of decision U3).

The migration is designed to be lossless: the source holds the original lines
unchanged, the generated copy differs only by the T-96 `%%` blank-line rule, the
diagram renders the same, and the ID and alias are unchanged. The verification steps
are on the T-97 card.

Today's architecture-document scan (`documents()` in `tools/design/architecture.py`)
reads every Markdown file under `docs/architecture/` at any depth. Without a change,
extracted sources in `docs/architecture/diagrams/` would be read as architecture
documents and their diagrams counted twice (decision U9). The transitional entries are
also exposed to heading renames until their document is extracted (decision U11).

### 12.3 Proposed IDs and names

To be confirmed before M0.

| ID | Former catalog ID (alias) | Proposed source file (`docs/architecture/diagrams/`) |
|---|---|---|
| AD-0001 | conventions/1-implementation-status-legend | conventions_legend_implementation-status.md |
| AD-0002 | database-schema/1-current-model-built-schema-public-real-data | database-schema_data-model_current-model.md |
| AD-0003 | database-schema/2-target-model-proposed-not-built | database-schema_data-model_target-model.md |
| AD-0004 | database-schema/a-the-team-workflow | database-schema_process_team-workflow.md |
| AD-0005 | etl-workflow/the-common-pattern | etl-workflow_process_common-pattern.md |
| AD-0006 | etl-workflow/streets--road_segments | etl-workflow_process_streets-road-segments.md |
| AD-0007 | etl-workflow/wastewater--utility_lines | etl-workflow_process_wastewater-utility-lines.md |
| AD-0008 | etl-workflow/manholes--manholes | etl-workflow_process_manholes.md |
| AD-0009 | etl-workflow/safety-gates | etl-workflow_process_safety-gates.md |
| AD-0010 | system-architecture/1-current-state-the-big-picture | system-architecture_system-architecture_current-state.md |
| AD-0011 | system-architecture/credential-boundary | system-architecture_system-architecture_credential-boundary.md |
| AD-0012 | system-architecture/2-current-state-inside-the-web-app | system-architecture_system-architecture_inside-the-web-app.md |
| AD-0013 | system-architecture/3-one-map-pan-step-by-step | system-architecture_sequence_one-map-pan.md |
| AD-0014 | system-architecture/4-target-state-the-product-vision-mostly-planned | system-architecture_system-architecture_target-state.md |

### 12.4 Other diagrams

- **`docs/agents/development-status.md`** (7 planning diagrams): decision U2; the
  recommendation is to keep them out of the library (project planning, not
  architecture; T-94 Phase 2 decision 1 excludes `docs/agents/`).
- **Placeholder diagrams in feature specifications**: the template's example, not
  adopted. Real embedded diagrams in features use Extract to diagram source
  (section 7.7).
- **The feature template's embedded example** becomes guidance to use + → Place Diagram
  (decision U6).

## 13. Compatibility

- **T-97 Phase 1**: feature diagram IDs, ownership checks and the allocator stay. The
  allocator also reads registry list lines (`- diagram_id:`), aliases and decoded
  draw.io root IDs, and learns `AD-` IDs. Existing fixtures allocate the same IDs.
- **T-96**: markers keep working with catalog IDs (now aliases) and accept new IDs.
  Mermaid copies in feature documents stay byte-identical to today until a source
  changes.
- **T-94**: the architecture catalog and index become registry-backed after M0; until
  M1 they still read the embedded blocks. How the architecture-document scan treats
  `docs/architecture/diagrams/` is decision U9. Existing `check` output is unchanged on
  today's repository. Exit codes are unchanged.
- **T-97 Phase 2 (Feature Designer)**: the menu item "Insert Existing Diagram" becomes
  Place Diagram → Add Existing Diagram; the JSON interface keeps response version 1 and
  only adds fields and the `resolve` operation. Feature Designer's tests that count 14
  architecture diagrams stay valid (same diagrams, same count), provided extracted
  sources are not counted again (decision U9).
- **No format conversion.** No Mermaid diagram is converted to draw.io. Importing a
  Mermaid diagram into draw.io is only ever an explicit "new visual diagram from …"
  recorded in `created_from` (a later item, VE-3). `.mmd`, DBML and moving
  architecture diagrams to draw.io are not part of this design.
- **Change impact (T-83)**: `designs/diagrams/**`, `.gitattributes` and the draw.io
  toolchain script are to be registered in `registry/components.yml` and `impact.yml`.

## 14. Open decisions U1–U12

These decisions are **still open**. The final answers will be recorded in
[designs/DECISIONS.md](../../designs/DECISIONS.md).

| # | Question | Recommendation |
|---|---|---|
| U1 | ID scheme for document-owned diagrams | `AD-nnnn` via the never-reuse allocator; former catalog IDs kept as permanent aliases |
| U2 | The 7 planning diagrams in `docs/agents/development-status.md` | Out of the library (project planning, not architecture) |
| U3 | What architecture documents show after extraction | The Mermaid copy only, with an invisible HTML comment naming the ID and source (rendering unchanged) |
| U4 | Existing markers that use catalog IDs | Keep resolving via aliases; no automatic rewrite |
| U5 | Refreshing Markdown copies after a source is saved | Automatically in documents without unsaved changes (only generated lines, listed in a notification); never in documents with unsaved changes |
| U6 | Feature template's embedded example diagram | Replace with guidance to use Place Diagram, together with the registry's introduction |
| U7 | Category list (supersedes R5's `architecture`) | `system-architecture`, `data-model`, `process`, `sequence`, `state`, `ui`, `legend`, `other` |
| U8 | Migration order | M0 together with the registry's introduction (registry only); M1 per document after the pinned-editor work and the hands-on test, each separately approved |
| U9 | Catalog scan after extraction: `documents()` in `tools/design/architecture.py` reads every Markdown file under `docs/architecture/` at any depth, so extracted sources in `docs/architecture/diagrams/` would be read as architecture documents and their diagrams counted twice | From M0 the diagram list comes from the registry, and the architecture-document scan excludes `docs/architecture/diagrams/` (source documents are listed under their owning document, not as documents); a test proves the count stays 14 through M1 |
| U10 | In-file identity for document-owned diagrams | `mermaid-md` front matter `diagram_id`, `title` and `owner_document` (repository path); `.drawio.svg` root-cell properties `fd_diagram_id` and `fd_owner_document`; feature-owned diagrams keep `feature_id` / `fd_feature_id` |
| U11 | Heading renamed before M1 (transitional `mermaid-embedded` entries are found by owner document + heading anchor + ordinal) | `check` reports the entry as not found (E7) with the candidate block it can see; the entry is re-pointed only by an explicit `registry relink`; the former catalog ID stays an alias; keeping the M0 → M1 interval short limits exposure |
| U12 | Move limits for document-owned sources | Document-owned sources stay in `docs/architecture/diagrams/` (`relink` refuses other locations); feature-owned sources stay in a `diagrams/` folder under `designs/features/` |
