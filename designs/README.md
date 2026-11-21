# Feature Design Workspace

Start here. This folder holds **proposed designs**: features you are investigating or
planning, written before any code changes. The implemented system is described in
[docs/architecture/](../docs/architecture/), which designs never overwrite.

- [IMPLEMENTATION_BRIEF.md](IMPLEMENTATION_BRIEF.md): the governing brief, kept unchanged.
- [DECISIONS.md](DECISIONS.md): decisions taken since the brief.
- [index/feature-index.md](index/feature-index.md): every feature, generated.
- [index/architecture-index.md](index/architecture-index.md): every current-state document
  in `docs/architecture/`, its headings and its Mermaid diagrams (with diagram IDs), generated.
- [templates/](templates/): the feature specification and diagram templates.

## Create a feature

Use **New Feature**. Do not create the file by hand: the command assigns the feature ID,
fills in the full template and updates the index.

- **In VS Code:** Terminal → Run Task… → **New Feature**. Enter the feature name, then a
  parent (a feature ID such as `FD-0003`, a folder under `designs/features/`, or nothing for
  a standalone feature).
- **In a terminal** (from the repository root):

  ```text
  .venv\Scripts\python -m tools.design new feature --name "Pipe road intersections"
  .venv\Scripts\python -m tools.design new feature --name "Maintenance prioritization" --parent FD-0001 --convert-parent
  ```

  Without `--name` the command asks for the name and parent. Press Ctrl+C (or Ctrl+Z
  then Enter on Windows) at a prompt to cancel: nothing is created. An empty or missing
  `--parent` means a standalone feature. Feature IDs are accepted in any case
  (`fd-0003` is `FD-0003`).

The command only creates or moves files in `designs/`. It never stages, commits, creates a
branch or pushes: the new files are ordinary uncommitted changes that you review and commit
yourself.

Other commands:

| Command | What it does |
|---|---|
| `python -m tools.design index` | Refresh each feature's generated summary table and Related features rows from its metadata, then regenerate the feature index and the architecture index |
| `python -m tools.design index --check` | Exit code 1 if either index, any summary table or any Related features rows are out of date (writes nothing) |
| `python -m tools.design check` | Check every feature: IDs (including duplicates), metadata, the six sections, both dependency tables, `depends_on` (unknown IDs, self-dependencies, repeats, cycles), links and references (see below), and the freshness of the generated rows and both indexes |

`check` also validates links and references inside `designs/`, without changing anything:

- **Relative links** in the Markdown files you write (features, `diagrams/`, `evidence/`,
  and the guides in `designs/`): the target must exist, with the exact letter case (GitHub
  is case-sensitive), and stay inside the repository; a `#anchor` into a Markdown file,
  including the documents in `docs/architecture/`, must be one of its headings. Absolute
  paths and `\` are reported. Each problem gives the file, the line and, where it can, a
  "did you mean" suggestion.
- **`architecture_refs`**: each entry must be a path such as
  `docs/architecture/system-architecture.md`, optionally with `#heading-anchor`, to an
  existing document and heading. An entry that is not a valid reference is shown in the
  summary table as plain text, never as a broken link.
- **Proposed diagrams** (files in `diagrams/` folders with metadata): `source_diagram` must
  be a diagram ID in the [architecture index](index/architecture-index.md#diagrams), and
  `source_document` and `source_heading` must exist and agree with it; `base_commit` must
  look like a commit hash.

Not checked here: generated files and blocks (their sources are checked instead),
`designs/templates/`, web links, `#L` line anchors, links in code or HTML comments, and
anything outside `designs/` (repository-wide link checking is T-81), and Mermaid syntax
(T-82). Write a link target that contains parentheses as `<file(1).md>`.

The architecture index is rebuilt from `docs/architecture/`, so a change there that adds,
renames or removes a heading or a Mermaid diagram makes `check` report it as out of date
until `python -m tools.design index` is run and the result committed with that change.
Other edits to those documents leave it up to date (it records no line numbers).

Exit codes: 0 success, 1 problems found, 2 a usage or file error.

## How features are organized

```text
designs/features/
  pavement-condition.md                 # a standalone feature: one file
  road-pipe-coordination/               # a parent feature: a folder
    README.md                           # the parent feature's own specification
    pipe-road-intersections.md          # a subfeature
    diagrams/                           # proposed diagrams (not features)
    evidence/                           # supporting material, only when needed
```

- **One file is enough** for a simple feature. Use a folder only when a feature has
  subfeatures or supporting files.
- **To add a subfeature under a standalone feature**, run New Feature with that feature as
  the parent and `--convert-parent`. The feature moves from `x.md` to `x/README.md` (its ID
  does not change) and its relative links are adjusted.
- **A parent can also be a plain folder** (a group) with no specification of its own.
- **Identity is the feature ID**, not the path. Moving or renaming a file keeps its ID.
  Prefer `design_status: deferred` to deleting a feature, so its ID is never reused.
- **File names** are made from the feature name: letters are lower-cased, accents are
  removed (`Résumé` → `resume`) and everything that is not an ASCII letter or digit
  becomes a hyphen, including Unicode dashes and the minus sign
  (`Pipe–Road Intersection Analysis` → `pipe-road-intersection-analysis.md`). Existing
  files are never renamed. Other characters with no ASCII equivalent (for example 日本語) are dropped
  from the file name, so a name must contain at least one ASCII letter or digit. The
  title in the specification keeps the name as typed, except that leading and trailing
  spaces are removed and repeated spaces become one.
- **Windows line endings are fine.** A Git checkout with `core.autocrlf=true` writes
  generated files with CRLF line endings; `check` and `index` treat them as up to date.
- **One New Feature at a time.** Two commands run at the same moment (for example in two
  terminals) can both take the same next ID. `python -m tools.design check` reports
  duplicate IDs, and New Feature refuses to run until they are fixed: give one of the two
  files the next free ID by hand. The same check catches two branches that each created
  the same ID, once they are merged.

## The feature specification

A feature file reads like a design document: a title, a summary table, an evidence legend,
the six sections, and collapsed "Architecture references" and "Proposed diagrams" at the
end. It renders in VS Code's Markdown preview (Mermaid needs a Mermaid preview extension,
such as "Markdown Preview Mermaid Support") and on GitHub. GitHub also shows the metadata
block itself as a small table at the top.

**The metadata block is the single source of truth.** The summary table under the title
is generated from it, between the lines `<!-- summary:start … -->` and
`<!-- summary:end -->`: New Feature creates it and `python -m tools.design index`
refreshes it. Edit the metadata, never the table: `check` reports a table that no longer
matches, and `index` rewrites only the lines between the two markers, never anything you
wrote elsewhere. A file whose metadata has a problem is left untouched until it is fixed,
and so is a block whose markers are missing, repeated or not closed: `index` prints one
warning line for each such file (and still exits 0), and `check` gives the details.
The "Related features" rows work the same way, between `<!-- related-features:start … -->`
and `<!-- related-features:end -->`, generated from `depends_on` (see
[Dependencies](#dependencies)).

Every feature file starts with a metadata block, then six mandatory sections:

| Metadata | Meaning |
|---|---|
| `feature_id` | Stable ID, assigned by New Feature; never edit it |
| `title` | The feature name |
| `design_status` | `investigating`, `proposed`, `approved`, `implementing`, `verified` or `deferred` |
| `owner`, `branch` | Who is working on it and on which branch, if relevant |
| `architecture_refs` | Repository paths of the current-state documents it builds on |
| `depends_on` | The **only** place feature prerequisites are declared (feature IDs) |

1. **Objective**: the real problem, who needs the result, the observable outcome.
2. **Data contract**: sources, fields, types, IDs, geometry and coordinate systems, limits,
   refresh behaviour, outputs and unknowns, with evidence.
3. **Logic**: processing steps, SQL and spatial operations, assumptions, small examples.
4. **Dependencies**: two tables, **System components** and **Related features**.
5. **Downstream impact**: confirmed, potentially affected and unknown items, kept apart.
6. **Acceptance criteria**: verifiable results, edge cases and the evidence required.

`design_status` describes the design. Task status (Ready, In Progress, Done) lives only on
the GitHub Project card; do not copy it here.

### Dependencies

- **Feature prerequisites** are listed once, in `depends_on`:

  ```yaml
  depends_on:
    - FD-0002
    - id: FD-0005
      optional: true
      condition: "only for the weekly batch"
  ```

  `python -m tools.design index` generates everything else from these lists, so nothing
  is entered twice:
  - each feature's **Related features** rows: a "Depends on" row for each entry in its own
    list (optional entries show their condition) and a "Used by" row for each feature that
    lists it, each with the feature ID, title and a relative link;
  - the **Depends on** and **Used by** columns of the [feature index](index/feature-index.md).

  Every generated relationship is marked 🔷 PROPOSED. Relationships follow the feature
  ID, so after moving or renaming a file, run `index` and the links follow it (New
  Feature does this itself when `--convert-parent` moves a parent). `check` reports rows
  that are out of date, an ID that no feature has, a feature that depends on itself, an
  ID listed twice, and **dependency cycles** (features that depend on each other in a
  circle). A cycle is shown for review; nothing is changed to break it.
- **System components** are written by hand. Use a relationship only when the evidence
  supports it: `reads_from`, `writes_to`, `calls`, `exposes`, `renders`. Label optional or
  conditional dependencies. `related_to` is not `depends_on`.
- **A dependency is a reason to investigate**, not proof that something must change. Keep
  "confirmed affected" separate from "potentially affected" in section 5.

## Evidence classifications

Tag every claim and relationship:

| Tag | Meaning |
|---|---|
| **VERIFIED** | Checked against a source you cite: a file and line or symbol, a query result, an API response or a test |
| **PROPOSED** | Part of the design; not built or not yet checked |
| **UNKNOWN** | Not known yet; say what would settle it |

These tags are **not** the diagram classes in
[conventions.md section 1](../docs/architecture/conventions.md#1-implementation-status-legend).
There, a component is `verified` only when its evidence is recorded in the Evidence log of
the task board. Here, VERIFIED means "I checked this claim against the cited source". In
Mermaid diagrams inside designs, label proposed steps "(planned)", as the conventions
require, so the diagram rules stay the same everywhere.

## Diagrams

- **Find** an existing diagram in the [architecture index](index/architecture-index.md#diagrams).
  Each one has a **diagram ID**: its document and the anchor of the heading above it, for
  example `system-architecture/1-current-state-the-big-picture` (a second diagram under the
  same heading gets `~2`). IDs are derived, never written into `docs/architecture/`, so an
  ID changes when its heading is renamed.
- **Link** to an existing diagram in `docs/architecture/` by its document and heading, for
  example `../docs/architecture/system-architecture.md#1-current-state-the-big-picture`
  (adjust `../` to the file's depth).
- **Create** a proposed diagram from [templates/diagram.md](templates/diagram.md) in a
  `diagrams/` folder next to the feature, and link it from the feature's "Proposed
  diagrams" section.
- **Copy** an existing diagram into a proposed variant: paste its Mermaid source into a new
  diagram file and fill in `source_diagram` (its diagram ID), `source_document`,
  `source_heading` and `base_commit`
  (`git rev-parse --short HEAD`), so the original can always be found. Never edit the
  original in `docs/architecture/` as part of a design.

Mermaid stays editable text. Preview it in VS Code (Markdown preview with Mermaid support)
or on GitHub.

### Showing a diagram inside a feature (generated blocks)

To show an authoritative diagram rendered inside a feature, without copying it by hand, put
two marker lines wherever it helps the reader (any of the six sections, as many as you like,
the same diagram more than once if useful), with a blank line before and after:

```markdown
<!-- diagram:start system-architecture/4-target-state-the-product-vision-mostly-planned -->
<!-- diagram:end -->
```

The ID comes from the [architecture index](index/architecture-index.md#diagrams). Then run
`python -m tools.design index`: it fills the lines between the markers with a caption
(✅ Current architecture, the title linked to the source document and heading, the ID, and a
link to the legend for architecture diagrams) and a copy of the source Mermaid, which renders
in VS Code's preview and on GitHub. Blank lines of the source are written as `%%` (a Mermaid
comment), so the block stays one piece.

- **The source is the only place a diagram is edited.** Change it in `docs/architecture/`
  (through the docs workflow), then run `index` again; every feature that shows it is updated.
- **Never edit between the two markers.** `check` compares each block with what its source
  produces now and fails on stale or hand-edited copies, unknown or renamed IDs (with a
  suggestion), a missing, nested or malformed marker, and a Mermaid fence that is not closed
  before the end marker. `index` never rewrites a file whose diagram blocks have such a
  problem; it says so instead.
- Marker examples inside code blocks (like the one above) are ignored. Files without markers
  are never changed.

## Editing in a formatted view (Mark Sharp)

Feature specifications stay ordinary Markdown. For a document-like editing view, use the
VS Code extension **Mark Sharp** (`jonathan-yeung.mark-sharp`; the free tier is enough).

- **Open a specification:** right-click it → **Open With… → Mark Sharp**. It is opt-in: `.md`
  files still open in the normal text editor by default. **Switch** between the formatted
  view and the Markdown source with `Ctrl+K Y` (the "M→" icon in the editor title).
- **Trust the folder.** Mark Sharp is disabled in VS Code's Restricted Mode: if
  **Open With…** does not list it, trust the folder (Command Palette → "Workspaces: Manage
  Workspace Trust").
- **Headings, paragraphs, lists and checkboxes** are edited directly in the formatted view.
  On the free tier, **editing table cells and rendering Mermaid diagrams are Premium
  features** (Mark Sharp's documentation): edit tables and Mermaid in the source
  (`Ctrl+K Y`) and view diagrams in the preview.
- **Tables are re-aligned when Mark Sharp saves** (setting
  `mark-sharp.formatting.tableAlignment`, default `alignColumns`: cells are padded to the
  column width). The first save of a file therefore re-pads its hand-written tables; later
  saves keep them as they are. The checks compare table columns, not padding, so this never
  breaks `check`. The generated summary and Related features blocks are kept as they are.
  Keep the default: `condensed` (no spaces at all) changes only slightly fewer lines and is
  much harder to read.
- **See diagrams** in VS Code's Markdown preview (`Ctrl+K V`, side by side), which renders
  Mermaid with the Mermaid preview extension. Links in the preview open the target document
  in the preview, at the heading. On GitHub, Mermaid renders in the file view.
- **Navigate the six sections** with the preview, the **Outline** view (Explorer → Outline,
  in the text editor) or `Ctrl+Shift+O` in the text editor; on GitHub, use the outline button
  of the rendered file.
- **Edit a diagram at its source:** a current-state diagram in `docs/architecture/` (through
  the docs workflow, never as part of a design), a proposed diagram in its `diagrams/` file.
- **Never edit between `<!-- … -->` markers.** Those lines are generated: edit the metadata
  or the source instead.
- **Before committing:** run `python -m tools.design index` (refreshes the generated blocks
  and indexes) and `python -m tools.design check`, then review `git diff`. Expect the
  one-time table re-alignment; anything else you did not intend should be undone.

## Branches and publishing

- **Explore on any branch.** New Feature works anywhere and changes nothing in Git.
- **Create a feature branch** (`git switch -c design/<short-name>`) when a design is worth
  keeping or reviewing, and before it changes anything outside `designs/`.
- **Commit only what you mean to publish.** Stage design files by name
  (`git add designs/features/<file>.md designs/index/feature-index.md`), never with a broad
  `git add .`.
- **Designs never edit `docs/architecture/`.** When a feature is built and verified, the
  current-state docs are updated through the normal docs workflow
  ([conventions.md section 5](../docs/architecture/conventions.md#5-branch-docs-workflow)),
  and the feature's `design_status` becomes `verified`.
- **Before a pull request**, run `python -m tools.design check` and
  `python -m tools.impact check --base main`.
