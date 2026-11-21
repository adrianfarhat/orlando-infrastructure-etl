# Feature Design Workspace

Start here. This folder holds **proposed designs**: features you are investigating or
planning, written before any code changes. The implemented system is described in
[docs/architecture/](../docs/architecture/), which designs never overwrite.

- [IMPLEMENTATION_BRIEF.md](IMPLEMENTATION_BRIEF.md): the governing brief, kept unchanged.
- [DECISIONS.md](DECISIONS.md): decisions taken since the brief.
- [index/feature-index.md](index/feature-index.md): every feature, generated.
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
| `python -m tools.design index` | Refresh each feature's generated summary table from its metadata, then regenerate the feature index |
| `python -m tools.design index --check` | Exit code 1 if the index or any summary table is out of date (writes nothing) |
| `python -m tools.design check` | Check every feature: IDs (including duplicates), metadata, the six sections, both dependency tables, and index freshness |

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
  becomes a hyphen. Characters with no ASCII equivalent (for example 日本語) are dropped
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
wrote elsewhere. A file whose metadata has a problem is left untouched until it is fixed.
The "Related features" rows have similar markers, for the generation planned in Phase 2.

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

  Phase 2 generates the "Related features" rows from these lists, including the reverse
  "used by" rows, so nothing is entered twice. Until then, the table shows its columns and
  this explanation.
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

- **Link** to an existing diagram in `docs/architecture/` by its document and heading, for
  example `../docs/architecture/system-architecture.md#1-current-state-the-big-picture`
  (adjust `../` to the file's depth).
- **Create** a proposed diagram from [templates/diagram.md](templates/diagram.md) in a
  `diagrams/` folder next to the feature, and link it from the feature's "Proposed
  diagrams" section.
- **Copy** an existing diagram into a proposed variant: paste its Mermaid source into a new
  diagram file and fill in `source_document`, `source_heading` and `base_commit`
  (`git rev-parse --short HEAD`), so the original can always be found. Never edit the
  original in `docs/architecture/` as part of a design.

Mermaid stays editable text. Preview it in VS Code (Markdown preview with Mermaid support)
or on GitHub.

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
