# Diagram Library (proposed)

> **PROPOSED — approved design (2026-11-22), not implemented.** Nothing on this page
> is built. In the terms of the
> [implementation-status legend](conventions.md#1-implementation-status-legend), every
> component described here is `planned`; none is `unverified` or `verified`. The built
> current state is described in the other `docs/architecture/` documents and in
> [designs/README.md](../../designs/README.md). Where this page states what exists
> today (section 2), it says so explicitly. Decisions U1–U14 were **approved on
> 2026-11-22** ([section 14](#14-decisions-u1u14-approved-2026-11-22)); U13 and U14
> supersede T-96 decisions 2 and 3. Items deferred to stage M1 are listed in
> [section 12.2](#122-stage-m1-extract-per-document). Statements that rest on a
> decision cite it as "(Un)".

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
   portable rendering. A generated copy is a representation of the source, not a
   second diagram (section 6.4).
2. **The stable ID is the identity.** File names are descriptive and may change; the ID
   never changes and is never reused.
3. **One library, one registry, one workflow** for both formats: Mermaid (code-first)
   and draw.io (visual-first). The format decides which editor opens.
4. **Reuse never copies.** A diagram used by several documents has one source and one
   owner.
5. **Existing diagrams behave as if made with Make New Diagram.** Each gets a registry
   entry and, after an approved migration, its own source document. Nothing is
   converted between formats.
6. **Unsaved edits and manual changes are never overwritten.** Generated content is the
   only thing tools rewrite, never in a document with unsaved changes, and never
   silently when the generated content was changed by hand (section 6.5).

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
| `document` | a repository document that is not a feature, for example `docs/architecture/system-architecture.md` | `AD-<nnnn>` (architecture/document diagram) (U1) | The same never-reuse allocator: working tree, Git history and registry |

- The ID prefix must match the owner kind.
- **Aliases.** A registry entry may list aliases. A former catalog ID becomes a
  permanent alias of its `AD-` ID and keeps resolving forever (U4).
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
| `mermaid-md` | `.md` | code | text editor, at the Mermaid block | Mermaid copy (T-96) | front matter: `diagram_id`, `title`, and `feature_id` (feature-owned) or `owner_document` (document-owned) (U10) |
| `drawio-svg` | `.drawio.svg` | visual | draw.io (pinned, section 10) | image link | root-cell properties: `fd_diagram_id`, and `fd_feature_id` (feature-owned) or `fd_owner_document` (document-owned) (U10) |
| `mermaid-embedded` | none (a block inside a document) | code, **transitional** | text editor, at the block in the owning document | the document itself | located by owner document + heading anchor + ordinal (renamed headings: U11) |
| `mermaid-mmd` | `.mmd` | code, **reserved** | not accepted yet | Mermaid copy | `%% diagram_id:` lines |
| `dbml` | `.dbml` | code, **reserved** | not accepted yet | to be designed | to be designed |

- **`mermaid-md`**: a standalone `.md` source document with front matter and exactly one
  Mermaid block (today's diagram file format, unchanged).
- **`drawio-svg`**: one diagram per file and **exactly one page**, because the saved
  image shows whichever page was active when saving. The ID is stored as a property on
  the diagram's root cell (for a feature-owned diagram
  `<UserObject id="0" fd_diagram_id fd_feature_id>`), visible in
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
- **Owner in the file (U10).** `owner_document` (front matter) and `fd_owner_document`
  (draw.io root property) hold the repository path of the original owning document, so
  ownership is recorded independently of the file name. Feature-owned diagrams keep
  `feature_id` and `fd_feature_id`. Moving architecture diagrams to draw.io is not part
  of this design and needs a plan of its own.

## 5. Naming and directories

### 5.1 File names

```text
<owner-slug>_<category>_<diagram-name>.<ext>
```

- **`owner-slug`**: the owning feature's file name without `.md` (for a parent feature,
  its folder name), or the owning document's file name without `.md`
  (`system-architecture`).
- **`category`**: from the controlled list `system-architecture`, `data-model`,
  `process`, `sequence`, `state`, `ui`, `legend`, `other` (U7). Make New
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

- **Sources stay in their approved directories (U12):** document-owned sources in
  `docs/architecture/diagrams/`, feature-owned sources in a `diagrams/` folder under
  `designs/features/`. `registry relink` refuses any other location.
- Document-owned sources in `docs/architecture/diagrams/` are owned and edited by
  technical-lead, like the documents themselves.
- **One write guard for architecture files.** Every file the diagram commands write
  passes one guard that refuses anything under `docs/architecture/`, including
  `docs/architecture/diagrams/`. Changes there are made only through technical-lead's
  documentation workflow; any change to this restriction is deferred to M1
  (section 12.2).

### 5.3 Reuse by several features

- The source keeps its owner's name and location.
- Other features and documents insert a reference (a marker with the ID). Reuse across
  documents happens only through stable IDs (U12). Nothing is copied, renamed or moved;
  the library shows "used by".
- **A reference is not ownership (U10).** Reuse never changes the owner recorded in the
  registry and in the file (`feature_id` or `owner_document`).
- Changing a diagram's owner is a separate, explicit command, not part of this design.

## 6. References, resolution and rendering

### 6.1 Canonical ID references

- A referencing document holds the T-96 marker pair. **The canonical reference is the
  start marker, which holds the ID** (or an alias) and, inside the same HTML comment,
  the fingerprint of the content last generated for that block (U13, section 6.5):

  ```text
  <!-- diagram:start FD-0001-D3 -->
  ...generated lines...
  <!-- diagram:end -->
  ```

- **Everything between the markers is generated** from the registry and the source. It
  is never read back to find a diagram: a path inside a block exists only because
  ordinary Markdown viewers need one, and no command reads a path out of a block. The
  only command that reads a block's content is the explicit "Apply to source" action of
  U13 (section 6.5).
- Former catalog IDs in existing markers keep resolving through aliases; markers are
  not rewritten to the new ID automatically (U4).
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
   document, heading anchor and ordinal. If that heading is renamed between M0 and M1,
   the reference is reported as broken (E7, with the candidate block it can see) and is
   re-pointed only by an explicit `registry relink`; nothing is guessed and the former
   catalog ID stays an alias (U11).
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
   what `resolve` produces. The registry fields that shape a block (title, path) count
   as part of the source, so an untouched block after a relink is case 1 of
   section 6.5 (source changed, copy untouched). A block whose marker has no
   fingerprint yet is refreshed only when that is lossless (section 6.5, "Markers
   without a fingerprint").
3. Refreshing:
   - **open documents without unsaved changes**: Feature Designer applies a guarded
     refresh edit (base SHA-256, line count and document version must match) that
     rewrites only the lines between that ID's markers;
   - **open documents with unsaved changes**: an "out of date" notice with a Refresh
     button; nothing is written until the user clicks;
   - **closed documents**: `python -m tools.design index`, which rewrites only the lines
     between markers, in files without a structural problem (T-96 rule).
   - Only case 1 blocks are refreshed automatically. A block with a manual
     modification (cases 2 and 3) is never refreshed by any of these paths
     (section 6.5).
4. Until refreshed, `check` reports E14, and Feature Designer still shows the right
   diagram, because it resolves by ID, not by the stale path.

### 6.4 Generated representations: one authority (U3, U5)

After extraction, the standalone source is the **only authoritative, editable version**
of a diagram. Mermaid kept inside an architecture page, or any other document, is a
**generated representation** of that source, not a second diagram. The system:

1. tracks each generated block by its stable diagram ID (the start marker);
2. refreshes it when the source changes, automatically only in documents without
   unsaved changes and only the lines between that ID's markers, listing every
   refreshed document in a notification (U5);
3. preserves the existing appearance and Mermaid content during migration
   (sections 6.6 and 12.2);
4. detects manual modifications to generated content (section 6.5);
5. never silently overwrites manual or unsaved changes;
6. reports conflicts clearly (E15) and offers a safe way to reconcile them
   (section 6.5).

Generated blocks are never counted as diagrams: the catalog lists each diagram once, by
its registry ID (U9, section 12.2).

### 6.5 Generated-content fingerprints (U13)

U13 supersedes T-96 decision 2 ("check compares the whole block … not a fingerprint").

**Fingerprint.** The start marker stores, inside its HTML comment, a fingerprint of the
content last generated for that block, for example:

```text
<!-- diagram:start AD-0013 sha256:<first 16 hex digits> -->
```

- It is invisible in rendered Markdown and backward compatible: markers without a
  fingerprint keep working, and existing IDs and aliases keep resolving.

**Three-way classification.** For each block, compare three things:

- `F`: the fingerprint in the marker (the content last generated);
- `B`: the block's current content;
- `G`: the content the source would generate now. The "source" includes the registry
  fields that shape the block (title, path), so a relink changes `G`.

`≡` means "equal content, ignoring only line endings" (below).

| Condition | Case | Meaning | What happens |
|---|---|---|---|
| `B ≡ F` and `G ≡ F` | current | nothing changed | nothing |
| `B ≡ F` and `G ≢ F` | **case 1** | source changed, copy untouched (includes a relink) | refreshed; the **only** case refreshed automatically, and only in documents without unsaved changes (section 6.3, U5) |
| `B ≢ F` and `G ≡ F` | **case 2** | manual edit, source unchanged | conflict E15 (manual edit) |
| `B ≢ F` and `G ≢ F` | **case 3** | both the block and the source changed | conflict E15 (distinct message: both changed) |
| `B ≢ F` but `B ≡ G` | special case (checked before cases 2 and 3) | the block was edited to exactly the new output | no conflict; the fingerprint is simply updated |

A conflict is never overwritten automatically and is never refreshed by `index` or
Feature Designer.

**Exact comparison** (clarified 2026-11-22, item 25 of the
[diagram library decisions](../../designs/DECISIONS.md#2026-11-22-t-97-diagram-library--visual-and-code-first-diagrams-approved-by-the-user)).

- **Content is compared exactly.** The only normalisation is line endings (CRLF and
  LF), for every diagram type.
- **Indentation and blank lines are never ignored**, even where the diagram would
  render the same: they matter for readability, maintainability and future Mermaid
  versions. There is no diagram-type allow-list.
- **Mark Sharp.** Its known reformatting of generated blocks in feature documents is
  reported as a conflict (E15) and reconciled explicitly; Discard manual change restores
  the generated content.
- **A more permissive rule** for Mark Sharp compatibility may be adopted only after
  tests demonstrate the exact need, and only with the user's explicit approval. No such
  rule is part of this design.

**Reconciliation (cases 2 and 3).** There are two actions. Both show a diff and require
explicit confirmation; neither is applied to a document with unsaved changes without
the user's click; each is one undoable step.

1. **Discard manual change.** Shows the diff of what will be lost, then regenerates the
   block from the source.
2. **Apply to source.** Previews the diff to the source. Before writing, it verifies
   that the source has not changed since the preview (by comparing its hash); if it
   changed, it stops and the preview must be made again. It then regenerates the block.
   - **Architecture (document-owned) sources** change only through technical-lead's
     documentation workflow. Feature Designer does not write them; it prepares the
     proposed change for that workflow. Reconciliation never writes under
     `docs/architecture/`: the write guard of section 5.2 refuses it.
   - **Feature-owned sources** follow ownership and the existing editing safeguards:
     the guarded edit with base hash, the unsaved-edit rules, and only the owner's
     file.

**Markers without a fingerprint** (blocks generated before U13). Such a marker gives no
record of what was generated, so a hand edit cannot be told from a stale copy. The
block is therefore:

- **migrated only when that is lossless**: when the block is exactly what its source
  generates now, only the start marker gains its fingerprint and the content is
  unchanged;
- otherwise **preserved and reported as E15** ("generated before fingerprints"); it
  changes only through explicit reconciliation (Discard manual change or Apply to
  source, above).

Nothing is overwritten on the assumption that it is a stale copy.

### 6.6 Rendering in Markdown

| Where | Content between the markers |
|---|---|
| Feature documents, `mermaid-md` | Caption (title linked to the source, ID, "generated copy; edit the source") plus the Mermaid copy, with the T-96 `%%` blank-line rule; byte-identical to T-96 output |
| Feature documents, `drawio-svg` | Caption plus `![<title>](<relative path>)`; stale only when the title or path changes, never when content changes |
| Architecture documents (during and after stage M1) | The Mermaid copy only, with an HTML comment naming the ID and source, so the rendered page is unchanged (U3). Written verbatim (U14) |

- **Feature documents** keep the T-96 rule that blank source lines are written as `%%`
  where needed, so the block stays contiguous for Mark Sharp.
- **Architecture documents (U14).** U14 supersedes T-96 decision 3 for architecture
  documents. During and after M1, generated copies in `docs/architecture/` documents
  are byte-for-byte the source's Mermaid lines: blank lines are **not** replaced by
  `%%`. Reason: 7 of the 14 architecture diagrams contain blank lines, and the `%%`
  rule exists only because Mark Sharp, used for `designs/`, truncates a block at a
  blank line; architecture documents are not edited with Mark Sharp.

### 6.7 Rendering in Feature Designer

- Every diagram block renders **from its resolved source**, not from the Markdown copy.
- Every diagram block carries an **Edit Diagram** button in its upper-right corner.
- If the Markdown copy differs from the source, a small "copy out of date" badge is
  shown. A block with a manual modification (case 2 or 3) is marked as a conflict and
  offers Discard manual change and Apply to source (U13, section 6.5).
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
| A source is saved (either format) | Every open view re-renders that diagram at once, from source | Visual: never (the image link points at the source). Mermaid: copies refreshed automatically (U5), never in a document with unsaved changes and never over a manual modification |
| Title or path changed (relink) | Marks captions and links out of date | Documents without unsaved changes only (section 6.3) |
| Registry changed outside Feature Designer | Reloads the library and re-resolves | No |

- For Mermaid copies, the refresh after a save is automatic in documents without
  unsaved changes: only the generated lines are rewritten, and every refreshed document
  is listed in a notification (U5). Documents with unsaved changes get a banner and a
  Refresh button. Only untouched blocks (case 1 of section 6.5) are refreshed; blocks
  with a manual modification (cases 2 and 3) are reported as conflicts (E15, U13) and
  left unchanged.
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
  `mermaid-md` front matter of a feature-owned source); captions are refreshed as
  above. For document-owned diagrams the write guard of section 5.2 applies:
  - a **standalone source** in `docs/architecture/diagrams/`: the registry is updated
    only when the source already has that title (technical-lead changes the file
    first);
  - an **embedded diagram** (`mermaid-embedded`): only the registry changes.
- The owner never changes on a move. `relink` accepts only the approved directory of
  the owner kind: `docs/architecture/diagrams/` for document-owned sources, a
  `diagrams/` folder under `designs/features/` for feature-owned sources (U12).
- A transitional `mermaid-embedded` entry whose heading was renamed is reported (E7)
  and re-pointed only by an explicit `registry relink` (U11).

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

1. **Take the lock.** Create `designs/diagrams/.registry.lock` (git-ignored). The
   running command holds an operating-system lock on that file, which the system
   releases when the process ends, however it ends; the file records the process ID
   and the computer. If another command holds the lock, refuse with "another diagram
   command is running".
   - **A lock is never broken automatically.** `python -m tools.design registry unlock`
     removes a leftover lock file only after verifying, by taking that operating-system
     lock itself, that no process holds it, only on the same computer, and only with
     `--confirm`.
   - A held, foreign (other computer) or unreadable lock is always kept.
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
- **Manual modifications are never overwritten silently.** A generated block that was
  changed by hand is a conflict (E15, U13); only the user's explicit, confirmed Discard
  manual change or Apply to source resolves it (section 6.5).
- **Diagram sources are never written by `index` or `refresh`, and Feature Designer
  never writes a document-owned source.** draw.io writes `.drawio.svg`; the user writes
  `mermaid-md`; only `new diagram` creates sources, and only exclusively. The one
  exception is U13's Apply to source for a **feature-owned** Mermaid source: confirmed
  after a diff preview, refused if the source's hash changed since the preview, and
  applied as a guarded edit to the owner's file only. For a document-owned source,
  Apply to source only prepares the proposed change for technical-lead's documentation
  workflow.

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
| E7 | Registered path missing, not found (for `mermaid-embedded`: the block is not found at its owner document, heading and ordinal, for example after a heading rename; U11) | `FD-0001-D3's source … does not exist` / `AD-0013: no diagram at system-architecture.md#<anchor> (block 1); candidate: line …; run registry relink AD-0013 …` |
| E8 | An ID and an alias collide (for example a former catalog ID issued or registered as an ID) | `… is both a registry ID and an alias of AD-0010` |
| E9 | Owner does not exist, or the ID prefix does not match the owner kind | `FD-0002-D1 is owned by FD-0001 in the registry: the ID prefix must be the owner's` / `AD-0003 is owned by a feature: AD- IDs belong to document owners` |
| E10 | Visual file has more than one page, no decodable graph, or a transparent background | a specific message for each |
| E11 | Reference to a retired diagram | `FD-0001-D3 was retired on …` |
| E12 | Lock held, or registry changed during a command | `another diagram command is running` / `the registry changed while creating …; nothing was written` (a leftover lock is removed only with `registry unlock --confirm`, section 8.1) |
| E13 | Hand-written image link to a `.drawio.svg` outside a diagram block | `…md line 40 links …x.drawio.svg directly: use a diagram block (FD-0001-D3) so the reference survives moves` |
| E14 | A generated path in a block no longer matches the registry | `stale image path in the FD-0001-D3 block of …md: expected …; run index or Refresh` |
| E15 | Generated content changed by hand (U13): case 2, the block differs from its fingerprint and the source is unchanged; or case 3, the block and the source have both changed; or a block without a fingerprint that differs from what its source generates now ("generated before fingerprints") | Case 2: `…md line 52: the AD-0013 block was edited by hand (n lines changed: …); the source is unchanged; not refreshed. Choose Discard manual change or Apply to source` / Case 3: `…md line 52: the AD-0013 block was edited by hand and its source has also changed since the block was generated; not refreshed. Review both diffs, then choose Discard manual change or Apply to source` |

E15 also covers a block whose marker has no fingerprint yet and whose content differs
from what its source generates now ("generated before fingerprints"): a hand edit
cannot be told from a stale copy, so the block is preserved and changes only through
explicit reconciliation (section 6.5). A block that matches its source exactly is
migrated losslessly instead (only the marker gains its fingerprint).

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

The order is U8: M0 together with the registry's introduction, then M1 per document.
Nothing runs without approval; each stage, and each M1 document, is approved
separately.

### 12.1 Stage M0: adopt in place (no document changes)

M0 is approved as the first implementation migration scope. It has not been executed.

- One registry entry per architecture diagram: an `AD-nnnn` ID, the current catalog ID
  as an alias, and format `mermaid-embedded` pointing at the current block.
- Every architecture diagram is then in the library, with a stable ID and an Edit
  Diagram target.
- **M0 changes no document and no diagram.** Every existing diagram's content, its
  rendering and every existing reference (catalog IDs in T-96 markers, now aliases)
  are therefore preserved by construction. The only generated change is the
  architecture index, which lists the new IDs beside the aliases.
- From M0 on, the diagram list comes from the registry (U9).

### 12.2 Stage M1: extract per document

Done by technical-lead, one document at a time, each separately approved. For each
diagram:

1. Create `docs/architecture/diagrams/<doc>_<category>_<name>.md` holding exactly the
   current Mermaid lines (byte-identical).
2. Switch the registry entry to `mermaid-md` with the new path.
3. Replace the embedded block in the document with the marker pair plus the generated
   Mermaid copy (with the HTML comment of U3).

The migration is designed to be lossless: the source holds the original lines
unchanged; the generated copy is byte-for-byte the original embedded lines, blank lines
included, never `%%` (U14); the rendering is identical; and the ID and alias are
unchanged. M1 verification includes tests that all 14 architecture diagrams keep their
exact original Mermaid content (byte comparison against the pre-migration lines) and
their rendering (output of the pinned Mermaid compared before and after). The full
verification steps are on the T-97 card.

**Deferred to M1 (not decided now).**

1. Any change to the restrictions on writing into `docs/architecture/` (T-94 Phase 2
   decision 2, and the T-82 docs lint) waits until M1 is separately authorised.
2. Applying changes to architecture (document-owned) sources always goes through
   technical-lead's documentation workflow.
3. Legend placement and lint rules are coordinated with T-82 as part of M1, without
   weakening those checks to fit the marker.

**Uniqueness by registry identity (U9).** Today's architecture-document scan
(`documents()` in `tools/design/architecture.py`) reads every Markdown file under
`docs/architecture/` at any depth, so extracted sources would otherwise be read as
documents and their diagrams counted twice. Under U9:

- the catalog lists each diagram once, by its registry ID;
- standalone sources in `docs/architecture/diagrams/` are not scanned as architecture
  documents; they are listed under their owning document;
- generated blocks (between markers) are never counted as diagrams;
- validation reports missing (E1, E7), duplicate (E2) and inconsistent (E3, E8, E14,
  E15) references;
- a test proves the count stays 14 through M0 and M1.

**Heading renames (U11).** Transitional `mermaid-embedded` entries depend on their
heading until their document is extracted. A heading renamed between M0 and M1 is
reported as a broken reference (E7) and needs an explicit `registry relink`; nothing is
guessed. Keeping the interval between M0 and M1 short limits this exposure.

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

- **`docs/agents/development-status.md`** (7 planning diagrams): out of the library
  (U2): they are project planning, not architecture, and T-94 Phase 2 decision 1
  excludes `docs/agents/`.
- **Placeholder diagrams in feature specifications**: the template's example, not
  adopted. Real embedded diagrams in features use Extract to diagram source
  (section 7.7).
- **The feature template's embedded example** becomes guidance to use + → Place Diagram
  (U6).

## 13. Compatibility

- **T-97 Phase 1**: feature diagram IDs, ownership checks and the allocator stay. The
  allocator also reads registry list lines (`- diagram_id:`), aliases and decoded
  draw.io root IDs, and learns `AD-` IDs. Existing fixtures allocate the same IDs.
- **T-96**: markers keep working with catalog IDs (now aliases) and accept new IDs.
  Mermaid copies in feature documents stay byte-identical to today until a source
  changes. U13 supersedes T-96 decision 2 (whole-block comparison, not a fingerprint):
  start markers carry a fingerprint inside their HTML comment. Markers without one keep
  resolving; their blocks are migrated only when lossless and are otherwise preserved
  and reported (E15). U14 supersedes T-96 decision 3 for
  architecture documents only (verbatim copies, no `%%`); feature documents keep the
  `%%` rule.
- **T-94**: the architecture catalog and index become registry-backed after M0; until
  M1 they still read the embedded blocks. The architecture-document scan excludes
  `docs/architecture/diagrams/` and never counts generated blocks (U9). Existing
  `check` output is unchanged on today's repository. Exit codes are unchanged.
- **T-97 Phase 2 (Feature Designer)**: the menu item "Insert Existing Diagram" becomes
  Place Diagram → Add Existing Diagram; the JSON interface keeps response version 1 and
  only adds fields and the `resolve` operation. Feature Designer's tests that count 14
  architecture diagrams stay valid (same diagrams, same count; U9).
- **No format conversion.** No Mermaid diagram is converted to draw.io. Importing a
  Mermaid diagram into draw.io is only ever an explicit "new visual diagram from …"
  recorded in `created_from` (a later item, VE-3). `.mmd`, DBML and moving
  architecture diagrams to draw.io are not part of this design.
- **Change impact (T-83)**: `designs/diagrams/**`, `.gitattributes` and the draw.io
  toolchain script are to be registered in `registry/components.yml` and `impact.yml`.

## 14. Decisions U1–U14 (approved 2026-11-22)

U1–U14 were approved by the user on 2026-11-22, with the clarifications written into
sections 5.3, 6.4, 6.5, 6.6, 12.1 and 12.2. Decisions are recorded in
[designs/DECISIONS.md](../../designs/DECISIONS.md). The design as a whole remains
PROPOSED: approved, not implemented.

### 14.1 Approved (2026-11-22)

| # | Question | Decision |
|---|---|---|
| U1 | ID scheme for document-owned diagrams | `AD-nnnn` via the never-reuse allocator; former catalog IDs kept as permanent aliases |
| U2 | The 7 planning diagrams in `docs/agents/development-status.md` | Out of the library (project planning, not architecture) |
| U3 | What architecture documents show after extraction | The Mermaid copy only, with an invisible HTML comment naming the ID and source (rendering unchanged). The standalone source is the only authoritative, editable version; the copy is a generated representation (section 6.4) |
| U4 | Existing markers that use catalog IDs | Keep resolving via aliases; no automatic rewrite |
| U5 | Refreshing Markdown copies after a source is saved | Automatically in documents without unsaved changes (only generated lines, listed in a notification); never in documents with unsaved changes; never silently over manual changes (section 6.4) |
| U6 | Feature template's embedded example diagram | Replace with guidance to use Place Diagram, together with the registry's introduction |
| U7 | Category list (supersedes R5's `architecture`) | `system-architecture`, `data-model`, `process`, `sequence`, `state`, `ui`, `legend`, `other` |
| U8 | Migration order | M0 together with the registry's introduction (registry only), approved as the first implementation migration scope; M1 per document after the pinned-editor work and the hands-on test, each separately approved |
| U9 | Catalog scan after extraction: `documents()` in `tools/design/architecture.py` reads every Markdown file under `docs/architecture/` at any depth, so extracted sources in `docs/architecture/diagrams/` would be read as architecture documents and their diagrams counted twice | Uniqueness by registry identity: from M0 the catalog lists each diagram once, by registry ID; the architecture-document scan excludes `docs/architecture/diagrams/` (sources are listed under their owning document); generated blocks are never counted; validation reports missing (E1, E7), duplicate (E2) and inconsistent (E3, E8, E14, E15) references; a test proves the count stays 14 through M0 and M1 |
| U10 | In-file identity for document-owned diagrams | `mermaid-md` front matter `diagram_id`, `title` and `owner_document` (repository path); `.drawio.svg` root-cell properties `fd_diagram_id` and `fd_owner_document`; feature-owned diagrams keep `feature_id` / `fd_feature_id`. The owner is recorded independently of the file name; reuse never changes the owner (a reference is not ownership) |
| U11 | Heading renamed before M1 (transitional `mermaid-embedded` entries are found by owner document + heading anchor + ordinal) | `check` reports the broken reference (E7) with the candidate block it can see; the entry is re-pointed only by an explicit `registry relink`; nothing is guessed; the former catalog ID stays an alias; keeping the M0 → M1 interval short limits exposure |
| U12 | Move limits for document-owned sources | Sources stay in their approved directories: document-owned in `docs/architecture/diagrams/` (`relink` refuses other locations), feature-owned in a `diagrams/` folder under `designs/features/`; reuse across documents only through stable IDs |
| U13 | How manual modifications to generated content are detected and reconciled | Generated-content fingerprints (section 6.5): the start marker stores, inside its HTML comment, a fingerprint of the content last generated (backward compatible). Three-way classification of fingerprint, block and newly generated content: current; case 1 (source changed, copy untouched, including a relink), the only case refreshed automatically and only in documents without unsaved changes; case 2 (manual edit) and case 3 (both changed), conflicts E15 with distinct messages; a block edited to exactly the new output only updates the fingerprint. Exact content comparison (clarified 2026-11-22, DECISIONS item 25): line endings are the only normalisation; indentation and blank lines are never ignored; no diagram-type allow-list. Mark Sharp's reformatting of a generated block is a conflict (E15), reconciled explicitly; a more permissive rule only after tests show the exact need and with the user's explicit approval. Reconciliation by Discard manual change or Apply to source, each with a diff, explicit confirmation and one undoable step; Apply to source checks the source's hash before writing; document-owned sources only through technical-lead's documentation workflow; feature-owned sources only through the guarded edit of the owner's file |
| U14 | How generated copies preserve Mermaid content in architecture documents | During and after M1, generated copies in `docs/architecture/` documents are byte-for-byte the source's Mermaid lines; blank lines are not replaced by `%%`. Feature documents keep the `%%` rule where needed for Mark Sharp (section 6.6). M1 verification includes tests that all 14 architecture diagrams keep their exact original Mermaid content (byte comparison) and rendering (pinned Mermaid output before and after) |

### 14.2 Superseded decisions

- **U13 supersedes T-96 decision 2** ("check compares the whole block … not a
  fingerprint").
- **U14 supersedes T-96 decision 3 for architecture documents** (blank source lines
  written as `%%`); feature documents keep that rule.
