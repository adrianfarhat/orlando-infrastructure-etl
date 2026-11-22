# Feature Design Workspace: decisions

Decisions taken after the [implementation brief](IMPLEMENTATION_BRIEF.md). The brief is kept
exactly as written; anything decided later is recorded here instead. Newest last. Task: T-94
on GitHub Project #1.

## 2026-11-20: Gate 1 (approved by the user)

1. **Location.** Proposed designs live in the top-level `designs/` folder.
   `docs/architecture/` stays the verified, implemented current state.
2. **Design status.** `design_status` (investigating, proposed, approved, implementing,
   verified, deferred) is allowed in `designs/` only. It describes the design, not the work:
   task status stays on the GitHub Project card and is never copied here.
3. **Evidence classifications.** Claims and relationships are tagged **VERIFIED** (with its
   source), **PROPOSED** or **UNKNOWN**. These tags are different from the diagram classes
   in [conventions.md section 1](../docs/architecture/conventions.md#1-implementation-status-legend)
   (see [README.md](README.md#evidence-classifications)).
4. **Change-impact tool (T-83).** `designs/**` and `tools/design/**` are registered in
   `registry/components.yml`; `designs/index/**` has the `generated` purpose. Stale-reference
   scanning stays on for `designs/`. T-83's engine is not changed.
5. **Ownership.** The main conversation maintains `designs/` (with the user's approval) and
   `tools/design/`; recorded in `CLAUDE.md`.
6. **VS Code task.** A committed "New Feature" task in `.vscode/tasks.json`, with a narrow
   `.gitignore` exception for that one file.
7. **Feature IDs.** Sequential `FD-0001`, `FD-0002`, … Identity is the ID, never the path.
   Duplicate IDs (for example two branches that both took the next number) are reported by
   `python -m tools.design check`.
8. **Nesting.** A standalone feature becomes a parent folder only with an explicit
   `--convert-parent`.
9. **Project card.** One task, T-94, covers Phases 1 and 2.
10. **New Feature and Git.** The command creates ordinary uncommitted working-tree files. It
    never stages, commits, creates a branch or pushes.
11. **Brief.** Committed unchanged as [IMPLEMENTATION_BRIEF.md](IMPLEMENTATION_BRIEF.md).

## 2026-11-20: Phase 1 implementation choices (for review at Gate 2)

1. **Canonical feature dependencies** are declared once, as the `depends_on` list in a
   feature's metadata block (feature IDs). The "Related features" table keeps the brief's
   columns; Phase 2 generates its rows from `depends_on`, including the reverse "used by"
   rows, so nothing is entered twice. In Phase 1 the check only validates the format of
   `depends_on` entries; existence, cycles and reverse links are Phase 2.
2. **Metadata** is YAML front matter, read with `ruamel.yaml`, which the repository already
   pins (`requirements.txt`). No new dependency.
3. **File names** come from the feature name, lower-cased with hyphens
   ("Pipe road intersections" → `pipe-road-intersections.md`); the title keeps the name as
   typed. Names that would collide are refused, never overwritten.
4. **Every Markdown file under `designs/features/`** is a feature specification and needs
   metadata, except files in `diagrams/` and `evidence/` folders.
5. **Converting a standalone feature** (`x.md` → `x/README.md`) rewrites the relative links
   inside that one file so they still resolve; links to it from other files are reported by
   the Phase 2 link check.
6. **Retired features** should be marked `deferred` rather than deleted: IDs come from the
   highest ID in use, so deleting the newest feature would let its ID be issued again.

## 2026-11-20: Gate 2 revisions (approved by the user)

1. **Line endings.** The index and summary freshness checks ignore CRLF versus LF, so a
   Git checkout with `core.autocrlf=true` is never reported as stale. Generated text is
   written with LF, or with the line ending the file already uses around the summary block.
   No `.gitattributes` is added.
2. **Presentation.** The feature specification reads like a professional design document,
   following the user's reference screenshot: a prominent title ("Feature Specification —
   …"), a compact summary table, an evidence legend (✅ VERIFIED, 🔷 PROPOSED, ❔ UNKNOWN),
   the six sections with bold-label prompts, a collapsible Mermaid diagram, acceptance
   checkboxes, and collapsed "Architecture references" and "Proposed diagrams" sections.
   Portable Markdown only: no custom CSS, web UI or new dependency. A coloured status pill
   is approximated with `<kbd>`, because GitHub removes inline styles.
3. **Metadata synchronisation (Option A).** The YAML metadata stays the single source of
   truth. The summary table is generated from it between `<!-- summary:start … -->` and
   `<!-- summary:end -->`: New Feature creates it, `index` refreshes it, and `check` (and
   `index --check`) report a stale table without writing. Only the lines between the two
   markers are rewritten; files whose metadata has a problem, or without exactly one
   summary block, are never touched.
4. **Data contract** keeps readable summary bullets and a source → database field-mapping
   table.
5. **Related features** rows sit between `<!-- related-features:start … -->` and
   `<!-- related-features:end -->`, ready for generation in Phase 2.
6. **The diagram template** follows the same presentation style and keeps its metadata.

## 2026-11-21: Phase 2 plan (approved by the user)

1. **One architecture index.** The architecture index and the diagram catalog are one
   generated file, [index/architecture-index.md](index/architecture-index.md), covering
   `docs/architecture/` only (`docs/agents/` is project planning, not architecture).
2. **Diagram IDs** are derived from position: `<document>/<heading anchor>`, with `~2`,
   `~3` for later diagrams under the same heading and `top` before the first heading.
   Nothing is written into `docs/architecture/`; IDs inside the documents are deferred
   (to be coordinated with T-82). Heading anchors follow GitHub's algorithm.
3. **The architecture index must be fresh**: `check` and `index --check` report it out of
   date when a heading or diagram in `docs/architecture/` changes. It records no line
   numbers, so other edits leave it up to date. The docs workflow in conventions.md
   section 5 notes the extra step.
4. **Diagram template** gains `source_diagram`, the diagram ID a proposed variant was
   copied from.
5. **Dependencies** (M2): "Depends on" and "Used by" columns in the existing feature index,
   not a separate dependency index; generated relationship rows are marked PROPOSED (no
   `evidence:` field yet); the Mermaid dependency graph is deferred.
6. **Validation** (M3): design-specific link and reference checks cover `designs/` only;
   repository-wide link checking stays with T-81. A dependency cycle is a check failure.
   D1 (backslashes in the summary's branch cell) is fixed separately; D2 (summary links for
   `architecture_refs`) is resolved by those checks.
7. **Deferred:** a `new diagram --from` command.

## 2026-11-21: M2 implementation choices (for review)

1. **Graph checks live with the graph.** `check` reports, from the `depends_on` lists, an
   ID that no feature has, a feature that depends on itself, an ID listed twice in one
   list, and each dependency cycle (once, at its lowest ID, naming every feature in the
   group, with one example path).
   Optional dependencies count towards cycles. M3 adds the link and reference checks
   only and does not repeat these.
2. **Generated rows.** "Depends on" rows keep the order of `depends_on`; "Used by" rows are
   ordered by feature ID. A self-dependency or a repeated ID gets no extra row; an
   unknown ID gets a row that says no feature has it; an ID shared by several files links
   to each of them. Features with any metadata problem add no relationships and their
   files are not rewritten. With no relationships, the template's `| — |` row is kept.
3. **Moves.** `index` updates the links after any move or rename. New Feature's
   `--convert-parent` refreshes only the Related features rows that mention the moved
   feature, never unrelated files.

## 2026-11-21: M3 implementation choices (for review)

1. **Scope.** `check` validates relative links and reference-style definitions in the
   hand-written Markdown under `designs/` (features, `diagrams/`, `evidence/` and the
   guides), including `#anchors` into any Markdown target such as `docs/architecture/`.
   Not checked: `designs/index/` and the generated summary and Related features blocks
   (their sources are checked, so each problem is reported once), `designs/templates/`
   (placeholders), web links, `#L` and other anchors into non-Markdown files, HTML links,
   and everything outside `designs/` (T-81). Mermaid syntax stays with T-82.
2. **Exact letter case.** A target must exist with the same case, as on GitHub, even on a
   case-insensitive disk.
3. **`architecture_refs`** must be repository-relative paths to Markdown documents in
   `docs/architecture/`, optionally with a heading anchor. D2: an entry that is not a valid
   reference (empty, absolute, outside `docs/architecture/`, or using `\`) is shown as plain
   text in the summary table, never as a broken link; anchors are percent-encoded.
4. **Proposed diagrams.** In files under `diagrams/` that have metadata: `source_diagram`
   must be in the diagram catalog (computed from `docs/architecture/`, as the architecture
   index is); `source_document` and `source_heading` must exist and agree with it;
   `base_commit` is checked for its format only (the tool runs no Git).
5. **D1.** The branch cell of the summary table is a code span with only `|` escaped, so no
   stray backslashes are shown.
6. **Tests.** The test workspaces copy this repository's `docs/architecture/`, the guides
   in `designs/` and the committed architecture index, so generated links resolve as they
   do here; the M1 tests that build their own `docs/architecture/` opt out.

## 2026-11-21: File names from Unicode dashes (approved by the user)

1. **Dashes separate words.** Before a feature name becomes a file name, Unicode dashes
   (Unicode category Pd: hyphen, non-breaking hyphen, figure, en and em dash, horizontal
   bar, and so on) and the minus sign U+2212 become an ordinary hyphen, so
   "Pipe–Road Intersection Analysis" gives `pipe-road-intersection-analysis.md`, not
   `piperoad-intersection-analysis.md`. Everything else is unchanged: ASCII names, accents,
   characters with no ASCII equivalent, reserved names, and the title, which keeps the
   name as typed.
2. **No renames.** File names are made only when New Feature creates a file; existing
   files keep their names. A name that now gives the same file name as an existing
   feature is refused, as before ("already exists; nothing was overwritten").
3. **Out of scope:** other Unicode punctuation (for example `’` or `·`) is still dropped.

## 2026-11-21: Formatted editing with Mark Sharp (T-95)

1. **Editor.** Feature specifications are edited in the VS Code extension Mark Sharp
   (`jonathan-yeung.mark-sharp`, 1.13.0, free tier), an opt-in custom editor; the default
   Markdown editor and the user's global VS Code settings are unchanged. The Markdown format,
   the six sections and the templates are unchanged. Rendered diagrams are viewed in VS
   Code's Markdown preview, because Mermaid rendering in Mark Sharp is a Premium feature.
2. **Tables.** Mark Sharp re-writes tables on save. Its exporter (read from the installed
   extension and ported into `tools/design/tests/marksharp_port.py`; the port reproduces a
   real Mark Sharp buffer exactly) has two modes: `alignColumns` (default; cells padded to
   the column width) and `condensed` (no spaces). On real specifications both rewrite a
   similar number of lines (12 against 10 of 147 on a filled-in example; 5 against 4 on a new
   one) and keep the generated summary and Related features blocks verbatim. The default
   `alignColumns` is kept: it is readable as source and stable on later saves.
3. **Column check.** The dependency-table check compared the header row as text, so any
   re-alignment failed `check` (`condensed` always; `alignColumns` whenever a cell was wider
   than its header). It now compares the header's cells, trimmed: names, order, count and
   case must still match exactly; only padding, which Markdown ignores, may differ. Tests
   show the old check failing and the new one passing both modes, and every real column
   mistake (renamed, reordered, missing, extra, wrong case) still rejected.
4. **Not verified without the editor's own interface:** Mark Sharp's re-serialisation of
   inline Markdown inside table cells (taken as unchanged), and its save of a file whose
   generated blocks contain blank lines. `index`, `check` and `git diff` before committing
   cover both.

## 2026-11-21: Diagram blocks (T-96)

1. **Attachment by markers only.** A feature shows a diagram through a pair of lines
   `<!-- diagram:start <ID> -->` / `<!-- diagram:end -->`, placed anywhere in the six
   sections, any number of times. There is no metadata list: the markers are the single
   declaration (approved by the user, replacing the earlier `diagrams:` proposal).
2. **Generated, never edited.** `index` writes a caption and a copy of the source Mermaid
   between the markers; `check` compares the whole block with what the source produces now
   (not a fingerprint). Files with a structural problem or an unknown ID are never rewritten.
3. **One contiguous block.** The copy writes each blank line of the source as `%%`, a Mermaid
   comment line, so the block has no blank line: 7 of the 14 architecture diagrams contain
   blank lines, and Mark Sharp keeps a block that starts with an HTML comment verbatim only
   up to the first blank line (observed on a real buffer). The diagram renders the same.
4. **Fence.** The copy's fence is at least three backticks and longer than any backtick run
   that starts a source line, so it always closes before the end marker.
5. **Sources.** Milestone 1: architecture catalog IDs (current architecture). The catalog and
   the architecture index are unchanged: copies live in `designs/`, which the catalog does
   not read, so no diagram ID is duplicated.
6. **Proposed diagrams (milestone 2).** A block may also name the `diagram_id` of a proposed
   diagram file in a `diagrams/` folder; that file, with exactly one Mermaid block, is the
   source, labelled "Proposed" and linked to the file. An ID used by two sources (two files,
   or a file and the catalog) or a file without exactly one Mermaid block is reported and
   never guessed. A template copy without a `diagram_id` is not attachable. The existing
   proposed-diagram checks (`source_diagram`, `source_document`, `source_heading`,
   `base_commit`) are unchanged.
7. **Feature index.** A "Diagrams" column lists the IDs each feature shows, derived from its
   markers (no metadata).
8. **Docs workflow (milestone 3).** conventions.md section 5 (technical-lead) now also asks,
   when the content of a Mermaid diagram in `docs/architecture/` changes, to run
   `python -m tools.design index` and commit the refreshed feature files in the same branch;
   `check` reports stale copies until then. Enforcement in CI is T-85 (its card asks for
   `python -m tools.design check` in the advisory workflow).

## 2026-11-21: T-97 Phase 1 — diagram ownership, IDs and the Feature Designer interface (approved by the user)

1. **Diagram ownership.** A diagram file with a `diagram_id` is owned by exactly one
   feature: `feature_id` (required, an existing feature) is the owner; `diagram_id` is the
   owner's ID plus `-D<n>` and unique; `title` is required. The owner comes from metadata,
   not from the folder (several standalone features share `designs/features/diagrams/`).
   `check` reports problems; nothing is fixed or renumbered automatically. Files without a
   `diagram_id` stay unchecked, as before.
2. **IDs are never reused (P1-A, Git history).** New feature and diagram IDs are one higher
   than every ID in the working tree and in the committed history of all branches,
   remote-tracking branches, tags and the stash (full history, so merged side branches
   count), read with a read-only `git log`
   (`tools/design/ids.py`, the only place the package runs a program; a test enforces
   that only `rev-parse`, `for-each-ref` and `log` are used). No ledger file. Allocation
   stops, creating nothing, when the history is incomplete or unreadable (not a Git
   repository, Git missing, a shallow clone, `git log` failing); a repository without any
   commit is complete. Documented limits: an ID created and deleted without a commit can
   be allocated again, and so can one that existed only on a branch that was squash-merged
   and deleted (its commits are no longer reachable); branches Git cannot see may allocate
   the same number, which
   `check` reports as a duplicate when they meet. Existing IDs are never renumbered.
3. **The Feature Designer interface** (`python -m tools.design designer`,
   `tools/design/designer_api.py`): one JSON request, one deterministic JSON response
   (version 1, sorted keys). Operations `library`, `insert`, `refresh` and `feature-index`
   take unsaved document text, propose edits (or the index text) and never write a file;
   each edit response carries `base` (SHA-256 and line count of the text it was computed
   from) so the editor rejects stale edits. `insert` validates the position in Python
   (inside the six sections, at a block boundary, never inside a code block, table,
   `<details>` group or generated block) and refuses an insertion that would add a
   problem. Applying the proposed edits gives exactly what `index` writes.
4. **Exit codes stay as they were** (0 success, 1 problems or a refused request, 2 usage,
   file or workspace errors); `test_exit_codes.py` pins this contract before any warning
   level is added (T-97 Q4).
5. Test workspaces are real (empty) Git repositories, since New Feature now reads the
   history; the T-94 "the package runs no program" test now allows exactly the read-only
   Git commands in `ids.py`.

## 2026-11-21: T-97 Phase 2 — Feature Designer MVP (approved by the user)

1. **Where and how it runs.** `tools/feature-designer/` (owned by the main conversation,
   registered for T-83), a VS Code custom *text* editor in development mode (P2-B): nothing
   installed. Isolated, pinned toolchain (P2-C): Node.js 26.13.0 downloaded and checked
   against nodejs.org's SHA-256, `npm ci --ignore-scripts`, VS Code 1.146.0 test build; all
   in Git-ignored folders.
2. **One model, one generator.** The Markdown document is the only model; the webview
   renders VS Code's current buffer. Edits come from `tools.design` (`designer --serve`, one
   long-running process speaking the Phase 1 JSON) and are applied as one `WorkspaceEdit`
   only to the exact text they were computed from (SHA-256 and line count, and the document
   version); otherwise they are refused as stale.
3. **Menu:** only "Insert Existing Diagram" until the other options ship (Q7).
4. **Feature index:** when a feature open in Feature Designer is saved, the index is updated
   from the saved files through the editor (and saved), unless it has unsaved changes (the
   user is told when it cannot be updated). Generated diagram blocks that
   no longer match their sources are reported in a banner, never repaired automatically
   (refresh is Phase 4).
5. **Interpreter (Q9, P2-A):** only the machine-level `featureDesigner.pythonPath` counts;
   workspace values are ignored and announced. When empty, the repository's `.venv`
   interpreter is suggested and saved only after the user confirms.
6. **Workspace trust:** VS Code does not apply the manifest's `untrustedWorkspaces` rule to
   development-mode extensions, so Feature Designer checks trust itself: in Restricted Mode it
   shows a static notice and runs no scripts and no Python.
7. **Interoperability (tested with the real Mark Sharp 1.13.0):** all editors share VS
   Code's document. Inserting while the file is open in Mark Sharp asks first; a later change
   that removes the inserted block raises a warning (Undo/Redo excluded). Mark Sharp can
   reformat generated blocks when it writes the file; authored text is unaffected, `check`
   reports the blocks and `index` restores them. Not guaranteed: text still being typed in
   Mark Sharp and not yet written to the shared document at the moment of an insertion
   (the race was tested once without loss, but Mark Sharp's internal timing is not observable).

## 2026-11-22: T-97 diagram library — visual and code-first diagrams (approved by the user)

The design is described in
[docs/architecture/diagram-library.md](../docs/architecture/diagram-library.md) (PROPOSED, not
implemented). Scope, order and acceptance tests are on the T-97 card; evidence is in
`docs/agents/task-board.md`.

1. **Direction.** Diagrams must be freely editable with a layout that stays exactly as drawn
   wherever they are shown. Mermaid cannot store positions (a proof of concept with the Mermaid
   NG editor confirmed that dragging a box draws a connector and nothing positional is saved),
   so visual diagrams use draw.io files saved as `.drawio.svg`: the editable graph and an image
   of exactly that layout in one file. A draw.io proof of concept kept positions, sizes, line
   routes and label offsets identical through save, close and reopen, and the same file
   rendered identically in VS Code's Markdown preview and Feature Designer's rendering path.
   Mermaid stays for code-first diagrams. The editor is the existing VS Code draw.io extension;
   no custom editor is built.
2. **Every diagram is its own source document** (user requirement), shown elsewhere through a
   reference by its stable ID. Reuse never copies; a reused diagram keeps one owner and one
   source. The ID is the identity; file names are descriptive and may change.
3. **V1 — code-first format.** Mermaid diagrams keep the existing `.md` diagram files (front
   matter and one Mermaid block); no `.mmd` now, but the format table reserves it. Why: no
   migration, and the existing template and checks keep working.
4. **V2 — one registry,** `designs/diagrams/registry.yml`: identity, owner, format, category,
   path, title and lifecycle, never diagram content. Why: one authoritative mapping for both
   formats; draw.io keeps the graph compressed, so IDs need a plain-text home that Git history
   can read.
5. **V3 — scoped `.gitattributes`:** `*.drawio.svg diff=drawio -merge`, plus an opt-in local diff
   helper. Why: measured in a scratch repository, two branches editing one diagram always
   conflict (the graph is one compressed line); without `-merge` Git writes conflict markers
   into the SVG and the file no longer opens; with it the conflict is still reported, the file
   stays valid and the other version is one command away. Other files merge as before.
6. **V4 — versions.** The reviewed draw.io extension version is pinned for development and
   tests; other versions get a compatibility warning in normal use, not a permanent refusal;
   nothing ever installs or upgrades the extension.
7. **V5 — installation.** draw.io is installed only in the isolated Feature Designer
   development profile until the whole workflow passes hands-on testing.
8. **V6 — PR #13** was reviewed and merged before any dependent work (no stacked branches).
9. **V7 — `designs/index/diagram-index.md`** is generated from the registry by the existing
   tooling; it is never edited by hand.
10. **V8 — ownership.** Make New Diagram defaults the owner to the open feature; another owner
    only through an explicit, validated action. Reuse never transfers ownership.
11. **R1 — online mode refused.** If `hediet.vscode-drawio.offline` is not `true`, the editor is
    not opened and the exact setting is shown. Why: online mode runs editor code from
    diagrams.net, contrary to the offline requirement.
12. **R2 — renames in VS Code** offer to update the registry, with confirmation each time.
13. **R3 — retire, never reuse.** Before a diagram is retired its references are listed and
    confirmation is required; remaining references show a clear retired-diagram message.
14. **R4 — GitHub rendering** is checked in a separate private scratch repository; nothing is
    created or pushed remotely without separate authorization.
15. **R5 — categories** are a controlled, schema-versioned list (changes only by a controlled
    schema change). The initial list approved with R5 is revised by open decision U7 to fit the
    naming convention below.
16. **R6 — PR A** starts only after PR #13's final review and merge (done: `db59478`).
17. **R7 — a diagram block shows** the rendered diagram, a caption with the title, the stable ID
    and a link to the source.
18. **Stable IDs are canonical** in documents (the T-96 marker); the image path or Mermaid copy
    between the markers is generated from the registry and never read back to find a diagram.
19. **Naming** (user requirement): `<owner-slug>_<category>_<diagram-name>.<ext>` in the owner's
    diagram folder, for example `test1_system-architecture_one-map-pan.md`.
20. **Existing diagrams** behave as if made with Make New Diagram: the 14 architecture diagrams
    join the registry (this reverses the earlier plan to keep them outside it), first in place
    and later, per approved document, as standalone source documents with identical content and
    rendering. Their former catalog IDs remain valid as aliases. No Mermaid diagram is converted
    to draw.io. Nothing is migrated before the user approves the exact scope.
21. **U1–U12 (approved by the user, 2026-11-22),** detailed in section 14 of the architecture
    document:
    - **U1** Diagrams owned by a document get `AD-nnnn` IDs from the never-reuse allocator; former
      catalog IDs stay valid as permanent aliases.
    - **U2** The 7 planning diagrams in `docs/agents/development-status.md` stay out of the library
      (project planning, not architecture).
    - **U3/U5 Single authority.** After extraction the standalone source is the only authoritative,
      editable version. Mermaid kept in an architecture page or any other document is a generated
      representation of it, tracked by the diagram ID and refreshed when the source changes; manual
      changes to generated content are detected and reported, never silently overwritten, and
      reconciled only by an explicit choice; documents with unsaved changes are never edited
      automatically. Architecture pages show the representation without a caption, so they look
      as they do today.
    - **U4** Existing references with catalog IDs keep resolving through the aliases; no automatic
      rewrite.
    - **U6** The feature template's example diagram is replaced by guidance to use Place Diagram.
    - **U7** Categories: `system-architecture`, `data-model`, `process`, `sequence`, `state`, `ui`,
      `legend`, `other` (replaces R5's `architecture`).
    - **U8 / M0** Stage M0 (register the 14 architecture diagrams in place, no document changed) is
      the first implementation migration scope; approved, not yet executed. M1 (extraction) follows
      later, one approved change per document.
    - **U9** Uniqueness comes from registry identity: each diagram is listed once; standalone
      sources are not read as documents and generated representations are never counted; missing,
      duplicate and inconsistent references are reported.
    - **U10** `owner_document` identifies the owning document independently of the file name;
      reuse never changes the owner.
    - **U11** A heading renamed between M0 and M1 is reported as a broken reference and needs an
      explicit relink; nothing is guessed.
    - **U12** Sources stay in their approved directories (document-owned:
      `docs/architecture/diagrams/`; feature-owned: a `diagrams/` folder under
      `designs/features/`); reuse across documents only through stable IDs.
22. **U13 and U14 (approved by the user, 2026-11-22).**
    - **U13 Generated-content fingerprints.** The start marker stores, inside its HTML comment
      (invisible and backward compatible; existing IDs and aliases keep resolving), a fingerprint of
      the content last generated for the block. Comparing the block and what the source would
      generate now against it gives three cases: (1) the source changed and the copy was not edited:
      the only case refreshed automatically, and only in documents without unsaved changes; (2) the
      copy was edited and the source did not change; (3) both changed. Cases 2 and 3 are reported as
      conflicts and need explicit reconciliation. Normalisation is diagram-type-aware and
      conservative: line endings always; indentation and blank lines only for diagram types on an
      allow-list where a test with the pinned Mermaid shows they make no difference. Indentation-
      sensitive types (for example mindmap) and unknown types are compared exactly; when uncertain,
      a difference is treated as meaningful.
    - **Reconciliation.** "Discard manual change" and "Apply to source" both show a diff and need
      explicit confirmation; "Apply to source" first verifies that the source has not changed since
      the preview. Architecture diagram sources change only through technical-lead's documentation
      workflow; feature-owned sources respect ownership and the existing editing safeguards. No
      reconciliation overwrites unsaved changes.
    - **U14 Verbatim architecture copies.** In architecture documents the generated copy is
      byte-for-byte the source's Mermaid lines (blank lines are not written as `%%`); feature
      documents keep the `%%` rule where Mark Sharp needs it. Tests show that all 14 architecture
      diagrams keep their exact Mermaid content and rendering through the migration.
23. **Earlier decisions changed by the approved U decisions** (recorded so the two do not
    conflict):
    - T-97 Phase 2 decision 4 ("generated diagram blocks … never repaired automatically"): replaced
      by U5. Generated blocks are refreshed automatically in documents without unsaved changes;
      manual modifications and documents with unsaved changes are never touched.
    - T-97 Phase 1 decision 1 ("owned by exactly one feature; `feature_id` required"): amended by
      U1 and U10. A diagram has exactly one owner, either a feature (`feature_id`) or a document
      (`owner_document`).
    - R7 (a block shows a caption with title, ID and source link): applies to feature documents.
      Architecture pages show the representation without a visible caption (U3), with the ID and
      source in an HTML comment.
    - The Phase 2b plan's "a saved Mermaid source writes Markdown only when the user clicks
      Refresh" is replaced by U5.
    - The Phase 2b plan's "diagram sources are never written by Feature Designer": one explicit
      exception, "Apply to source" for feature-owned Mermaid sources after a confirmed diff, a
      check that the source has not changed, and a guarded edit. Feature Designer never writes
      document-owned sources; it prepares the change for technical-lead's workflow.
    - T-96 decision 2 ("`check` compares the whole block with what the source produces now (not a
      fingerprint)"): superseded by U13. The block is compared with its recorded fingerprint and
      with the source's current output.
    - T-96 decision 3 (blank source lines written as `%%`): superseded by U14 for architecture
      documents only; it still applies to feature documents.
24. **Deferred to M1** (decided when M1 is separately authorized): any change to the restriction that
    nothing is written into `docs/architecture/` (T-94 Phase 2 decision 2, coordinated with T-82);
    applying changes to architecture sources always through technical-lead's workflow; the legend
    placement and lint rules, coordinated with T-82 without weakening those checks to fit the
    marker.
25. **U13 clarified: exact comparison (approved by the user, 2026-11-22).** Generated-content
    fingerprints compare the exact content; the only normalisation is line endings. Indentation and
    blank lines are not ignored because diagrams render the same: they matter for readability,
    maintainability and future Mermaid versions. This replaces the type allow-list described in
    item 22. A more permissive rule for Mark Sharp's reformatting of generated blocks would first
    have to be shown necessary by tests and then approved explicitly; until then such reformatting
    is reported as a conflict and reconciled explicitly.

## 2026-11-22: T-97 PR A — diagram registry implementation choices (for review)

1. **Scope.** The registry (`tools/design/registry.py`), stable IDs (`AD-` IDs for document-owned
   diagrams, read from registry lines in the Git history as well), standalone Mermaid creation
   with the `<owner>_<category>_<name>.md` naming, resolution by ID or alias, reuse by reference,
   relink, retire, adopt, U13 fingerprints with exact comparison and explicit reconciliation, the
   generated diagram index, and stage M0 (the 14 architecture diagrams registered in place as
   `AD-0001` to `AD-0014`, with their catalog IDs as aliases; no document changed). Not in PR A:
   M1 extraction and the verbatim architecture copies of U14 (used from M1), draw.io (visual
   formats are known but refused), the Feature Designer workflow (PR B), the feature template's
   example diagram (U6) and the hand-written `.drawio.svg` link check (E13).
2. **Registry authority.** A standalone source with a `diagram_id` that is not registered is a
   problem (E5) and cannot be shown, even if its front matter is valid; `registry adopt`
   registers it. Without a registry file the registry is empty, so a project without diagrams
   needs none.
3. **Commands write the generated diagram index** after a successful registry change, as New
   Feature writes the feature index.
4. **References by alias keep their generated text.** A block that names a former catalog ID is
   rendered exactly as before M0 (the caption shows the name the block uses), so M0 changes no
   existing block; tests prove all 14 architecture diagrams generate byte-identical lines.
5. **Fingerprints.** Sixteen hex digits of SHA-256 over the generated lines joined by `\n`
   (a trailing CR removed). An emptied block is regenerated (nothing to lose); an old marker
   without a fingerprint keeps the T-96 comparison until its first refresh adds one. A
   conflict never blocks the refresh of other blocks in the same file.
6. **Reconciliation on the command line** (`reconcile`): a preview prints the diff and a token
   derived from the document, the source and the action; `--confirm <token>` applies exactly that
   change and is refused if either file changed since. Apply to source writes only a
   feature-owned standalone source; document-owned and embedded diagrams are refused with a
   pointer to technical-lead's workflow. When the block uses the T-96 blank-line form, a bare
   `%%` line becomes a blank line in the source.
7. **Feature Designer compatibility** (no new workflow): its marker pattern accepts the
   fingerprint, and "Edit source" also finds a diagram by an alias.
8. **The registry lock** `designs/diagrams/.registry.lock` is listed in `.gitignore`; it exists only
   while a command runs.
