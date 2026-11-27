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
| `python -m tools.design index` | Refresh each feature's generated summary table and Related features rows from its metadata, then refresh diagram blocks (never a hand-edited one) and regenerate the feature index, the architecture index and the diagram index |
| `python -m tools.design index --check` | Exit code 1 if either index, any summary table or any Related features rows are out of date (writes nothing) |
| `python -m tools.design check` | Check every feature: IDs (including duplicates), metadata, the six sections, both dependency tables, `depends_on` (unknown IDs, self-dependencies, repeats, cycles), links and references (see below), diagram ownership, and the freshness of the generated rows and both indexes |
| `python -m tools.design new diagram --feature FD-0001 --title "Name" --category process` | Create and register a standalone Mermaid diagram owned by a feature, with the next diagram ID that was never used (see [Diagrams](#diagrams)) |
| `python -m tools.design registry adopt\|adopt-architecture\|relink\|retire …` | Change the diagram registry under its lock: register a source, register the architecture diagrams in place, move or retitle a diagram, retire one (see [Diagrams](#diagrams)) |
| `python -m tools.design resolve <ID or alias>` | Show a diagram's authoritative source (JSON); writes nothing |
| `python -m tools.design reconcile --file F --line N --discard\|--apply-to-source` | Resolve a diagram block that was edited by hand: shows the change, applies it only with `--confirm <token>` |
| `python -m tools.design registry move SOURCE [...] --to DEST [...] [--confirm TOKEN]` | Move feature-owned diagram sources (by ID, path or folder) and their registry paths as one recorded, recoverable move; shows the plan first and acts only with the `--confirm` token it prints (see [Moving diagram sources](#moving-diagram-sources)) |
| `python -m tools.design registry adopt-moves [--from OLD --to NEW ...] [--confirm TOKEN]` | Update the registry for sources already renamed by VS Code, Git or another program (without arguments: every moved source `check` reports, E6); shows the plan first |
| `python -m tools.design refresh-blocks --file F --expect SHA256 [...] --sources-token T` | Refresh the out-of-date diagram blocks of several closed feature documents as one recoverable update (not an atomic multi-file write: a failure rolls back what it wrote, an interruption leaves a record to complete or undo); refused if any changed since it was listed (used by the Feature Designer; see [Interrupted updates](#interrupted-updates-of-closed-documents)) |
| `python -m tools.design transaction status\|complete\|undo\|abandon [ID] [--confirm TOKEN]` | Show or resolve an interrupted update (E16): each action shows its effect first and acts only with the `--confirm` token it prints |
| `python -m tools.design transaction windows` / `transaction forget-window NAME [--confirm]` | List the Feature Designer window records (responding, not responding, unreadable) and the documents each protects; remove one that is not responding or unreadable, only with `--confirm` and only when that window is no longer open |
| `python -m tools.design designer` | The Feature Designer's interface (T-97): one JSON request on stdin, one JSON response on stdout; it proposes edits and never writes a file (described in `tools/design/designer_api.py`) |

Exit codes: 0 success; 1 problems found (`check`, `index --check`) or a refused Feature
Designer request; 2 a usage, file or workspace error (nothing was created or changed).

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
- **Identity is the feature ID**, not the path. Moving or renaming a file keeps its ID, and
  no command ever renumbers a feature. **IDs are never reused:** New Feature takes the number
  after every ID in the working tree *and* in the committed Git history (all branches,
  remote-tracking branches, tags and the stash, including merged side branches), so a
  deleted feature's ID stays retired. It reads the
  history with a read-only `git log` and stops, creating nothing, when the history is
  incomplete (a shallow clone: run `git fetch --unshallow`) or cannot be read. Limits: an ID
  that was created and deleted without ever being committed left no record and can be
  allocated again; an ID that existed only on a branch that was squash-merged and then
  deleted is no longer in any reachable commit, so it is not known either; and a branch Git
  cannot see yet may take the same number (see the next point). `design_status: deferred` is still better than deleting a feature.
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
  terminals), or on two clones that have not fetched each other's branches, can both take
  the same next ID. `python -m tools.design check` reports duplicate IDs, and New Feature
  refuses to run until they are fixed: give the newer file a new ID by hand (one that was
  never used). The same check catches two branches that each created the same ID, once
  they are merged.

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

Every diagram has **one authoritative source** and a **stable ID** in the diagram registry,
[diagrams/registry.yml](diagrams/registry.yml) (design:
[docs/architecture/diagram-library.md](../docs/architecture/diagram-library.md)). Documents show a
diagram by referencing its ID; nothing is ever copied by hand. The generated
[diagram index](index/diagram-index.md) lists every diagram, its owner, format and source, and
the features that show it.

- **Find** a diagram in the [diagram index](index/diagram-index.md) or the
  [architecture index](index/architecture-index.md#diagrams). The 14 architecture diagrams are
  registered in place (stage M0) with stable IDs `AD-0001` to `AD-0014`; their former catalog
  IDs (`<document>/<heading anchor>`, for example
  `system-architecture/1-current-state-the-big-picture`) stay valid as **aliases**, so existing
  references keep working. Their source is still the Mermaid block in `docs/architecture/`:
  nothing there was changed or moved.
- **Create** a standalone Mermaid diagram owned by a feature:

  ```text
  python -m tools.design new diagram --feature FD-0001 --title "One Map Pan" --category system-architecture
  ```

  It creates `<owner>_<category>_<name>.md` (here `test1_system-architecture_one-map-pan.md`) from
  [templates/diagram.md](templates/diagram.md) in the `diagrams/` folder next to the owning
  feature, with the next diagram ID that was never used (`FD-0001-D1`), and registers it, all or
  nothing: under a lock, the file is created without overwriting anything and the registry is
  replaced only if nobody changed it meanwhile; on any failure both are left as they were.
  Categories: `system-architecture`, `data-model`, `process`, `sequence`, `state`, `ui`,
  `legend`, `other` (default `other`). The file name is descriptive only; the ID is the identity.
- **Reuse** a diagram in another feature by placing a block with its ID (below). The source keeps
  its owner, name and location; reuse never copies it and never changes its owner.
- **Ownership** (T-97): a diagram is owned by exactly one feature (`feature_id`, ID
  `FD-0001-D<n>`) or one document (`owner_document`, ID `AD-<nnnn>`). The registry decides; the
  front matter must agree. Diagram numbers are never reused (working tree, registry and
  committed history) and never renumbered.
- **Rename or move** a feature-owned source with
  `python -m tools.design registry move FD-0001-D1 --to <new path>` (several at once, or a whole
  `diagrams/` folder; see [Moving diagram sources](#moving-diagram-sources)). If a source was
  already moved by hand, with Git or in VS Code, `python -m tools.design registry adopt-moves`
  updates the registry, or `python -m tools.design registry relink FD-0001-D1 --path <new path>`
  for one source (unchanged; no record). Change a title with
  `registry relink FD-0001-D1 --title "New title"` (registry and front matter). If an
  architecture heading is renamed, re-point its diagram explicitly with
  `registry relink AD-0006 --heading <anchor>`; nothing is guessed. Then run `index`.
- **Retire** a diagram with `python -m tools.design registry retire FD-0001-D1`: it lists every
  reference first and changes nothing; repeat with `--confirm`. Its ID is never issued again,
  and remaining references are reported.
- **Register** a source made outside `new diagram` (for example an interrupted command) with
  `python -m tools.design registry adopt <path> --category <category>`.
- **Look up** a diagram's authoritative source with `python -m tools.design resolve <ID or alias>`.

`check` reports, and never fixes: unknown, duplicate or colliding IDs and aliases, owners and ID
prefixes, missing, moved, copied or unregistered sources, front matter that disagrees with the
registry, retired diagrams that are still shown, sources outside their approved folders, and
architecture diagrams whose heading moved. Each message names the file and the exact command to
fix it.

- **Link** to an existing diagram in `docs/architecture/` by its document and heading, for
  example `../docs/architecture/system-architecture.md#1-current-state-the-big-picture`
  (adjust `../` to the file's depth).
- **Copy** an existing diagram into a proposed variant: create a diagram with `new diagram`,
  paste its Mermaid source and fill in `source_diagram` (its catalog ID), `source_document`,
  `source_heading` and `base_commit` (`git rev-parse --short HEAD`), so the original can always
  be found. Never edit the original in `docs/architecture/` as part of a design.

Mermaid stays editable text. Preview it in VS Code (Markdown preview with Mermaid support)
or on GitHub.

### Moving diagram sources

A move changes two things, one after the other (G1 in [DECISIONS.md](DECISIONS.md)):

1. **The identity**: the source files and their `path` in the registry. `registry move` and
   `registry adopt-moves` change these, and only these, through a recorded move (below).
   `diagram-index.md` is regenerated afterwards.
2. **The generated text**: the captions and links in the diagram blocks that show a moved
   diagram. They follow separately: Feature Designer refreshes open documents, and the move
   prints the `refresh-blocks` command for the closed ones (or use Feature Designer's Update
   closed documents). A refresh that fails or is refused never undoes the move; until it runs,
   `check` reports the stale text (E14).

```text
python -m tools.design registry move FD-0001-D1 --to designs/features/pipes/diagrams/
python -m tools.design registry move designs/features/pipes/diagrams --to designs/features/roads/diagrams
python -m tools.design registry adopt-moves
```

Each command first prints its plan (every rename, and what refuses the batch) and changes
nothing; repeat it with `--confirm <token>` to carry out exactly that plan. The token changes if
a source, the registry or a destination changes meanwhile; the command then refuses and you plan
again. Under the registry lock the whole batch is validated again before anything is written:

- only registered, active, feature-owned `mermaid-md` sources move, to a `diagrams/` folder under
  `designs/features/` (never into, out of or within `docs/architecture/`: architecture sources
  change only through technical-lead's documentation workflow);
- only `path` changes: the ID, owner, title, category, aliases and the file's bytes stay the same.
  Links inside a moved source are never rewritten; the plan warns about relative links that will
  stop resolving, and `check` reports them;
- refused, with nothing changed: an existing destination (an unrelated file is never
  overwritten), two equal destinations or destinations equal ignoring letter case, another
  diagram's registered path, a source not exactly as planned, a symbolic link or junction on
  the way, a source or destination open in a Feature Designer window (also one that has stopped
  responding), a Git operation in progress, an unresolved record, and an ID found at two or more
  unregistered paths (nothing is guessed);
- **folders**: `registry move FOLDER --to FOLDER` moves the registered sources one by one and is
  refused when the folder holds anything else (an unregistered file, a retired diagram's file, a
  subfolder); `registry adopt-moves --from OLD --to NEW` follows a folder you already renamed.
  Old folders are never deleted;
- **letter case only** (`A.md` to `a.md`): `registry move` renames through a hidden intermediate
  file in the same folder, so an interruption is recoverable; `adopt-moves` recognises a
  case-only rename made elsewhere. The registry takes the exact new case. A folder whose name
  changes only in letter case is not moved by `registry move`: rename the folder yourself, then
  run `registry adopt-moves`;
- hidden names (starting with `.`) and names Windows reserves (`con`, `nul`, `com1` …) are
  refused as destinations, because a source there would never be read.

The plan (with or without `--json`) exits with 1 when the move is possible and nothing was done
yet, and with 2 when it is refused; carrying it out exits with 0.

**What adoption can prove.** `registry adopt-moves` validates the source as it is *now* at its new
path: it holds the diagram's ID and owner, and it is a well-formed Mermaid source. Without the
SHA-256 the file had before it was renamed, it cannot prove that the bytes are unchanged by the
rename (for example a program that edited the file while moving it). Feature Designer's rename
integration (PR B2b-2b) can pass that checksum, taken just before VS Code renames the file, with
the `move-plan` request (`sha256`); the adoption is then refused if the content differs.

**After the move: secondary steps.** Once the move is verified, two things remain, and neither
can undo it:

- `diagram-index.md` is regenerated. If that fails (for example the file is locked), the command
  says so instead of claiming it was regenerated, `check` reports the index as out of date, and
  `python -m tools.design index` rewrites it.
- The move's record is removed. If that fails (for example another program has a file in the
  record's folder open), the command still succeeds (exit 0) with a warning. A record marked as
  completed holds nothing and is never carried out again; `transaction status` lists it under
  "cleanup pending", and later diagram commands retry the removal, which may stay pending until
  the cause is removed. After **Undo** (which is not marked as completed) the record stays listed
  as unresolved, and keeps the registry held, until it is removed: repeating Undo changes
  nothing more and tries again.

A genuine failure of the move itself still exits with 2 and says what was and was not done.

**Interrupted moves.** A move keeps a record in `designs/diagrams/.transactions/<id>/` (the exact
registry before and after, and every rename with the SHA-256 of the source). If it is interrupted,
`check` reports E16, and no registry change and no refresh of generated text runs until you
decide with `transaction status|complete|undo|abandon` (below). Each rename is shown at its old,
new or intermediate path, at more than one, at none, or changed. **Complete** finishes the
remaining renames and then writes the registry; **Undo** renames back and restores the registry
(for an adoption, only the registry: the files stay where they were put). Both refuse to overwrite
anything, never touch a registry that another program changed, and can be repeated. If recovery
stops on an operating-system error after everything was already in place, it says so: repeat the
same action to remove the record. A move is a recoverable transaction, not an atomic multi-file
operation. These commands have been tested on Windows only; on Linux and macOS a rename is a link
followed by an unlink, which the tests exercise only by simulation.

### Showing a diagram inside a feature (generated blocks)

To show an authoritative diagram rendered inside a feature, without copying it by hand, put
two marker lines wherever it helps the reader (any of the six sections, as many as you like,
the same diagram more than once if useful), with a blank line before and after:

```markdown
<!-- diagram:start system-architecture/4-target-state-the-product-vision-mostly-planned -->
<!-- diagram:end -->
```

The ID is either a diagram ID from the [architecture index](index/architecture-index.md#diagrams)
(current architecture) or the `diagram_id` of a proposed diagram file in a `diagrams/` folder
(made from [templates/diagram.md](templates/diagram.md), with exactly one Mermaid block). Then
run `python -m tools.design index`: it fills the lines between the markers with a caption
(✅ Current architecture or 🔷 Proposed, the title linked to the source, the ID, and a link to
the legend for architecture diagrams) and a copy of the source Mermaid, which renders on GitHub
and in VS Code's preview with the Mermaid preview extension. Blank lines of the source are written as
`%% (blank line)`, a Mermaid comment that every renderer removes, so the block stays one piece (Mark Sharp
keeps a block only up to its first blank line) and the diagram renders exactly as its source. Copies made
before T-98 used a bare `%%`, which Mermaid draws as a node or rejects; `index` refreshes such a copy unless
it was edited by hand (then `check` reports it, see below). The feature index lists each feature's diagrams in
its "Diagrams" column.

- **The source is the only place a diagram is edited.** Change a current-state diagram in
  `docs/architecture/` (through the docs workflow) or a proposed one in its `diagrams/` file,
  then run `index` again; every feature that shows it is updated.
- **Never edit between the two markers.** `check` compares each block with what its source
  produces now and fails on stale or hand-edited copies, unknown or renamed IDs (with a
  suggestion), a missing, nested or malformed marker, and a Mermaid fence that is not closed
  before the end marker. `index` never rewrites the diagram blocks of a file that has such a
  problem; it says so instead.
- Put each marker alone on its own line, below `## 1. Objective`. `check` reports markers in
  list items, quotes or sentences, and blocks above the first section. Marker examples inside
  code blocks (like the one above) are ignored. Files without markers are never changed.

**The whole workflow:**

1. **Attach:** find the diagram ID (architecture index, or a proposed file's `diagram_id`) and
   add the two marker lines where the diagram helps.
2. **Generate:** `python -m tools.design index`.
3. **View:** open the VS Code preview (`Ctrl+K V`) or the file on GitHub; the caption links to
   the source. In Mark Sharp's free tier the block is not drawn; use the preview.
4. **Edit the source** (never the block) and run `index` again; `check` reports any feature
   whose copy is out of date until you do.
5. **Commit** the source, the refreshed feature files and `designs/index/` together, after
   `python -m tools.design check` and a look at `git diff`.


**Fingerprints and hand edits.** When `index` (or the Feature Designer) generates a block, its
start marker records a fingerprint of the generated lines:
`<!-- diagram:start FD-0001-D1 sha256:0123456789abcdef -->` (invisible when rendered). With it,
the tooling tells apart:

- the source changed and the block was not edited: `index` refreshes the block;
- the block was edited by hand, or both the block and the source changed: a **conflict** (E15).
  It is reported and never overwritten, by `index` or anything else.

Comparison is exact: only line endings are ignored, so a change of indentation or blank lines
is a real change. Resolve a conflict explicitly; both actions show the exact change first and
change nothing until confirmed with the token they print:

```text
python -m tools.design reconcile --file designs/features/test1.md --line 52 --discard
python -m tools.design reconcile --file designs/features/test1.md --line 52 --apply-to-source
```

`--discard` regenerates the block from its source. `--apply-to-source` copies the block's
Mermaid into its feature-owned source (refused if the source changed since the preview) and then
regenerates the block; architecture diagrams change only through technical-lead's documentation
workflow. Mark Sharp's reformatting of a generated block is a conflict too; `--discard` restores
it.

**Blocks made before fingerprints** carry no record of what was generated, so a hand edit cannot be
told from a stale copy. `index` migrates such a block only when that loses nothing: if it is
exactly what its source generates now, only its start marker gains the fingerprint. Any other
content is preserved and reported as a conflict (E15, "generated before fingerprints"); resolve
it with `reconcile` as above.

#### Interrupted updates of closed documents

`refresh-blocks` (the Feature Designer's **Update…** for closed documents) writes several
feature documents as one update. Before changing anything it keeps, in
`designs/diagrams/.transactions/<id>/` (ignored by Git), the exact original and updated bytes of
every document, their SHA-256 hashes, the registry and source revisions they were computed from
and the state of the update, each flushed to disk. Every document is checked again just before
it is replaced; if one changed, the documents already replaced are put back. This is a
recoverable transaction, not an atomic multi-file write: partial states are possible and are
always reported. If a document this update wrote is changed by another program before the
rollback reaches it, that document is left alone, the update is reported as **partly done**, and
the record (with every original) is kept for an explicit Complete or Undo.

If the update is interrupted (the process or the computer stopped), `check` reports E16 and
nothing more is written to those documents until you decide:

```text
python -m tools.design transaction status
python -m tools.design transaction complete tx-20261125T101500Z-0a1b2c3d
python -m tools.design transaction undo tx-20261125T101500Z-0a1b2c3d
python -m tools.design transaction abandon tx-20261125T101500Z-0a1b2c3d
```

Each shows every document's current state (updated, not updated, changed since, missing) and
what it would do, and acts only when repeated with `--confirm <token>`; the token changes if
anything changes meanwhile. **Complete** writes the updated text into the documents not yet
updated (refused if the registry or a source changed since). **Undo** restores the originals of
those already updated. Both are safe to repeat, also after an interruption of their own; a
document that changed since, is missing, or is open in a Feature Designer window is never
overwritten. **Abandon** removes the record and changes no document; a damaged record can only
be abandoned, and until then no feature document is written by the design tooling.

When an update (or its Complete or Undo) is verified but its record cannot be removed (for
example another program has a file in the record's folder open), the command succeeds with a
warning instead of reporting a failure. A completed record holds nothing and is never carried out
again: `transaction status` lists it under "cleanup pending", and later commands retry the
removal, which may stay pending until the cause is removed. After Undo, the record stays listed
until it is removed; repeating Undo changes nothing more and tries again.

Every command that writes takes the registry lock (below) and leaves documents held by an
unresolved update alone. The lock is never waited for, so two commands cannot deadlock. An update
and its recovery refuse while a Git operation (merge, rebase, cherry-pick, revert, bisect) is in
progress, and check again before each document is written; `index`, `new feature` and
`reconcile` do not check for Git operations. **Limits:** a program that does not use this tooling
can still change a document in the short moment (milliseconds) between its last check and its
replacement, and that change is then replaced; Windows has no folder flush, so the record relies
on the file system's journal; open documents are known only from Feature Designer windows: a VS
Code window without it (another installation, Restricted Mode, the repository opened as a
subfolder) or another editor is not seen.

A Feature Designer window that stops responding (suspended, asleep or hung for more than two
minutes) still protects the documents it listed, because it may hold unsaved changes: its record
is never ignored because of its age. A record is removed by its window when it closes, by any
Feature Designer window on the same computer once it has verified that the window's process has
ended (at start, every minute and before listing closed documents), or explicitly with
`transaction forget-window NAME --confirm` (refused while that window is responding). An
unreadable window record blocks every update until it is replaced by its window or forgotten.

**A stale registry lock.** Diagram commands hold `designs/diagrams/.registry.lock` while they run;
a command that was killed can leave it behind, and every diagram command then refuses (E12). To
recover, run `python -m tools.design registry unlock`. It removes nothing on its own: it reports
whether the lock is still held. The running command holds an operating-system lock on the file,
which the system releases when that process ends, so the check cannot be fooled by a reused
process ID. Only when no process holds it (on this computer) does `--confirm` remove it. A lock
that is still held, was taken on another computer, or cannot be read is always kept; delete such
a file by hand only when you are sure no diagram command is running anywhere.

**Architecture sources are never written by these commands.** Every file the diagram commands
write passes one guard that refuses anything under `docs/architecture/` (including
`docs/architecture/diagrams/`): those files change only through technical-lead's documentation
workflow. `registry relink --title` on a document-owned diagram updates the registry only after
its source already has the new title.

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
  breaks `check`. Generated blocks are a different matter: a T-97 test with the real Mark
  Sharp 1.13.0 found that when Mark Sharp writes a file whose generated blocks changed while
  it was open (for example a diagram block inserted by the Feature Designer), it can
  reformat them — blank lines and Mermaid indentation inside diagram blocks, table padding
  in the Related features block. Your own text is not affected; `check` reports those
  blocks and `index` regenerates them exactly.
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

## Feature Designer (T-97, development mode)

A formatted view with a **"+"** beside each block to place a diagram without typing markers:
**Place Diagram → Add Existing Diagram…** (a searchable library: architecture diagrams by
document, feature-owned diagrams by owner) or **Make New Diagram…** (creates and registers one
standalone Mermaid source with `new diagram`, then inserts its reference). Each diagram is drawn
from its authoritative source and has an **Edit Diagram** pencil that opens that source; a copy
that differs from its source is shown as such, never hidden. When a source changes, a document
open only in Feature Designer with no unsaved changes is refreshed as one undoable, unsaved edit;
any other open document is offered **Refresh now**. **Review…** on a conflicting block offers
**Discard manual change** or **Apply to source**, with a preview and confirmation. It edits VS Code's shared document, so it works alongside the text
editor and Mark Sharp on the same file (Mark Sharp for prose, Feature Designer for
diagrams). Set it up and open it as described in `tools/feature-designer/README.md`:

```
.venv\Scripts\python tools\feature-designer\toolchain\bootstrap.py
.venv\Scripts\python tools\feature-designer\toolchain\dev.py
```

then right-click a feature → **Open With…** → **Feature Designer**. Saving a feature open in
Feature Designer also updates `designs/index/feature-index.md`, as `index` would. When the
file is also open in Mark Sharp, pause typing there before inserting (Feature Designer asks
first), and run `index` and `check` before committing (see above).

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
