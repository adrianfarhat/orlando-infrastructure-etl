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

## 2026-11-22: T-97 PR A — safeguards requested before merge (for review)

1. **Blocks without a fingerprint are never overwritten** unless that is lossless. A marker made
   before U13 gives no record of what was generated, so a hand edit cannot be told from a stale
   copy. Such a block is migrated only when it is exactly what its source generates now (only
   the start marker gains the fingerprint); any other content is preserved and reported as a
   conflict (E15) for explicit reconciliation. This replaces item 5 of the PR A implementation
   choices ("keep the T-96 comparison until the first refresh") and the corresponding sentence of
   the diagram library design.
2. **Stale-lock recovery is verified, never automatic.** While a command runs it holds an
   operating-system lock on `designs/diagrams/.registry.lock` (released by the system when the
   process ends, however it ends); the file records the process ID and the computer.
   `registry unlock` removes the lock only after taking that operating-system lock itself (so no
   process holds it) on the same computer, and only with `--confirm`. A held, foreign or unreadable
   lock is always kept. No network or process-control module is used (the T-94 purity rule holds).
3. **One write guard for architecture sources.** Every file the diagram commands write passes
   a guard that refuses anything under `docs/architecture/`, including `docs/architecture/diagrams/`.
   `registry relink --title` on a document-owned standalone source updates the registry only when
   the source already has that title (technical-lead changes the file first); for an embedded
   architecture diagram it changes the registry only. Reconciliation never writes there either.

## 2026-11-22: T-97 PR B — Feature Designer diagram placement and editing (approved by the user)

Mermaid diagrams only; draw.io and M1 are not part of PR B. Built on the PR A registry, resolution
and fingerprint rules, which are unchanged. Scope, order and acceptance tests are on the T-97 card.

1. **B1 — writes.** The Feature Designer creates diagram files only by running the PR A commands
   (`python -m tools.design new diagram …`) as one-shot processes: argument arrays, no shell, the
   validated interpreter. The long-running designer interface stays read-only (Phase 1 decision 3).
2. **B2 — rendering.** A diagram block renders from its authoritative source. When the embedded
   copy differs from what the source generates (a conflict), the block says so, distinguishes the
   source from the embedded document copy, and lets the reader inspect both. A manual edit is never
   hidden and a conflicted document never looks synchronized.
3. **B3 — refresh of an open document (modified by the user).** A case-1 source change may refresh a
   clean open document automatically through the guarded editor API, as one undoable edit, and is
   never saved automatically: the document becomes dirty so the user can inspect, undo or save it.
   A document with unsaved edits is not modified automatically: a notification offers a guarded
   manual refresh. Conflicts are never overwritten. (PR B2.)
4. **B4 — closed documents** are updated only by an explicit one-click action, case-1 blocks only
   (PR B2), or by `python -m tools.design index`.
5. **B5 — default category** of Make New by section: 1 Objective other, 2 Data contract data-model,
   3 Logic process, 4 Dependencies and 5 Downstream impact system-architecture, 6 Acceptance criteria
   other. Always changeable before creating.
6. **B6 — editing an architecture diagram** opens its document at the block with a notice that
   changes go through technical-lead's documentation workflow; the Feature Designer never writes there.
7. **B7 — retired diagrams** are hidden in the library; their blocks show a placeholder with
   Remove reference (an undoable edit by the user's click).
8. **B8 — Make New** uses the existing diagram template.
9. **B9 — two PRs.** PR B1: API support, command runner, Place Diagram submenu, Add Existing, Make New,
   the Edit Diagram pencil, source-based rendering and conflict indicators. PR B2: synchronization,
   guarded refresh and reconciliation UI, explicit closed-document updates, rename hook.
10. **Insertion after creation.** If Make New creates and registers a diagram but inserting its
    reference fails (for example because the document changed), the stable ID is shown with an
    Add Existing Diagram action so it can be placed later; nothing is half-done.

## 2026-11-23: T-97 PR B2 — synchronization and reconciliation (approved by the user)

Mermaid only; the fingerprint rules (U13), source resolution, the registry lock and
compare-and-swap, and the docs/architecture/ write guard are unchanged. T-98 (the "%%" line in
generated copies) stays separate. Scope, order and acceptance tests are on the T-97 card.

1. **C1 — which documents refresh automatically.** Only a document shown in a Feature Designer
   view, with no unsaved changes, and open in no other editor (not Mark Sharp, not the text
   editor). Every other document gets a guarded "Refresh now". Only blocks whose source changed
   and whose copy was not edited are refreshed; conflicts never.
2. **C2 — after an automatic refresh** a non-modal notice offers Undo, Show changes and Save. The
   refresh is one undoable edit and is never saved automatically (decision B3).
3. **C3 — Apply to source** writes the source through the editor and saves it, refused while the
   source has unsaved changes. Added safeguards: the source and the document revisions are
   verified immediately before applying; applying the copy over changes made in the source (or
   when that cannot be established) needs an explicit confirmation; if the source is saved but
   the document update fails, this is reported as partial completion with a guarded recovery
   (update the block now, or restore the preserved original source); the original source content
   is kept for recovery until the operation completes; success is reported only when both steps
   succeeded; nothing suggests that one Ctrl+Z undoes both files.
4. **C4 — closed documents:** the direction is approved, but the detailed design (detecting
   interrupted multi-file updates, a durable transaction record or a justified alternative, safe
   resume, rollback and conflict handling, crash-injection and restart-recovery tests) needs
   approval before implementation.
5. **C5 — event storms:** more than 5 sources changed within 2 seconds means no automatic
   refresh; a summary offers a manual refresh instead.
6. **C6 — renames:** VS Code renames of feature-owned sources in approved folders, one prompt per
   batch (PR B2b).
7. **C7 — new commands** `refresh-blocks` and `registry move` (PR B2b).
8. **C8 — visibility:** a status strip that stays visible while scrolling, with counts and
   Previous / Next navigation between affected blocks.
9. **C9 — two PRs.** PR B2a: source-change detection and event storms, automatic and manual
   refresh, conflict review with Discard manual change and Apply to source, the status strip.
   PR B2b: closed documents (after the C4 design is approved), the rename hook and registry move.

## 2026-11-25: T-97 PR B2b — closed documents, transactions and renames (approved by the user)

PR B2b is split in two. **B2b-1**: closed-document updates, the transaction record and crash
recovery (authorized). **B2b-2**: registry moves, source renames and reference synchronization
(not started). The fingerprint rules, classification, generated text, the docs/architecture/
write guard and T-98 are unchanged.

1. **D1 — transaction records** live in `designs/diagrams/.transactions/`, ignored by Git with
   one narrowly scoped `.gitignore` entry, so the command line, `check`, every VS Code window and
   a restarted machine all see an interrupted update.
2. **D2 — recovery is always an explicit action.** Neither Complete nor Undo is preselected. The
   affected files, their current states and the consequences of each action are shown before
   anything is confirmed.
3. **D3 — one locking protocol for every cooperating writer.** All design-tool write paths are
   audited; every one that writes takes the registry lock and refuses to write a file held by an
   unresolved transaction. The lock is never waited for (no deadlock), and taking it again in the
   same process is allowed (no self-deadlock).
4. **D4 — Git operations.** An update or a recovery refuses to start while a Git operation is in
   progress, and the repository state is checked again immediately before files are written.
5. **D5 — folder renames:** approved for B2b-2 only.
6. **D6 — documents open in other VS Code windows.** The registry lock says nothing about
   another window's unsaved documents, so each Feature Designer window publishes the feature
   documents it has open (and whether they are unsaved) in the transaction folder, with a
   heartbeat. An update refuses any document listed by a window that may still be running. A
   window that does not run Feature Designer (another VS Code installation, Restricted Mode, or
   another editor) cannot be detected; this limitation is documented and shown in the
   confirmation.
7. **D7 — QA follow-ups from B2a:** the misplaced comment and the empty pane of an expired Show
   changes snapshot are fixed in B2b-1; the path-normalisation nit and the order of overlapping
   dialogs stay as follow-ups.
8. **D8 — retention.** A record is removed only after a successful resolution or a separate,
   explicit and informed abandonment. Dismissing a notification never removes it.
9. **Transaction requirements:**
   - each record holds the original and replacement bytes, their hashes, the source and
     registry revisions and the transaction state;
   - records, paths, checksums and manifest integrity are validated before use;
   - path traversal, symbolic-link and junction escapes and unauthorized targets are rejected;
   - recovery never overwrites a file with unexpected changes;
   - the sources and the registry are revalidated before an interrupted transaction is
     completed;
   - Complete and Undo are idempotent, also after an interruption during recovery itself;
   - durability is verified on Windows, with the process terminated during preparation,
     replacement, rollback and clean-up;
   - the remaining race between checking a file and replacing it is documented, and no
     absolute atomicity against non-cooperating programs is claimed;
   - the four protected files, the architecture documents and the unrelated `iot/` directory
     are preserved;
   - the B2a automatic and manual refreshes respect unresolved transactions.

## 2026-11-26: T-97 PR B2b-1 — pre-merge review (directed by the user)

1. **Windows that stop responding are protected (D6, made conservative).** The user asked that a
   window that may still be active is never dropped because it cannot be verified. A Feature
   Designer window record is no longer ignored because its heartbeat is older than 120 seconds:
   such a window (suspended, asleep or hung, possibly with unsaved changes) is reported as "not
   responding" and its documents are still left out of every update and recovery. An unreadable
   record blocks every update whatever its age. A record is removed only by its window, by a
   Feature Designer window on the same computer after it verified that the window's process has
   ended (at start, every minute and before listing closed documents), or by the explicit
   `transaction forget-window NAME --confirm`, which is refused while the window is responding.
2. **Wording.** Closed-document updates are described as recoverable transactions with guarded
   rollback and explicit recovery, never as an atomic or "all or none" multi-file write: a
   document changed by another program can prevent a complete rollback, and the update is then
   reported as partly done with the record kept.

## 2026-11-26: T-97 PR B2b-2 — renames, registry moves and reference updates (approved by the user)

B2b-2 is split in two. **B2b-2a**: transaction infrastructure and registry move tooling
(authorized, after the S0 documentation gate). **B2b-2b**: Feature Designer rename integration and
interface (not started). Plan: two layers. The *identity* layer (source files and
`designs/diagrams/registry.yml`) is changed by a recorded move transaction. The *generated text*
layer (block captions and links, `designs/index/diagram-index.md`) is derived from it and updated
afterwards by the existing mechanisms (B2a for open documents, `refresh-blocks` for closed ones).

1. **G1 — two layers.** A move transaction covers source files and the registry only. Reference
   updates are a separate, explicitly confirmed `refresh-blocks` transaction (closed documents) or
   the B2a refresh (open documents).
2. **G2 — observed renames adopt the registry only.** When VS Code, Git or another program has
   already renamed a source, only the registry follows. Moving the files back is a separate,
   tool-initiated move.
3. **G3 — "Not now" writes no record.** A declined adoption leaves E6 reported by `check` (and,
   in B2b-2b, by the strip) until it is resolved; the state is derived from disk by in-file ID.
4. **G4 — `diagram-index.md` is regenerated**, not journalled (it is derived).
5. **G5 — architecture sources** (`docs/architecture/diagrams/`) are excluded from B2b-2: never
   moved, adopted or prompted for; relinks there belong to M1 through technical-lead.
6. **G6 — hand-written links** to a source path are reported by the link check, never rewritten.
7. **G7 — case.** Destinations equal ignoring letter case collide on every platform; a case-only
   rename is carried out through a recorded intermediate (temporary) path.
8. **G8 — folders (with the user's clarification).** Registry operations cover registered sources
   only. A physical folder move never silently moves, overwrites, deletes or otherwise touches
   unrelated files. *Adopting* a folder rename the user already performed (only the registry
   follows) is distinct from *initiating* a folder move through the tooling (which moves only
   registered sources, file by file, and refuses when the folder holds anything else that would
   have to move with them).
9. **G9 — held paths (modified by the user).** Renaming a document or source held by an
   unresolved transaction is prevented wherever the tooling or VS Code's pre-rename mechanism
   allows it. Where prevention is unavailable, the user is warned and the resulting missing path is
   handled conservatively (reported, never written). No "relocate record" action in this PR.
10. **G10 — tool-initiated moves are command-line only** (`registry move`).
11. **G11 — two PRs:** B2b-2a (S1–S2, tooling) then B2b-2b (S3–S4, extension).
12. **G12 — formats:** `mermaid-md` only; the engine and validation are format-neutral so
    `drawio-svg` can join with the draw.io work.
13. **Additional requirements (user):**
    - *Transaction compatibility:* version 1 (B2b-1) records stay readable and recoverable after
      the upgrade; version 2 records carry explicit operation types and narrowly scoped write
      permissions; unknown versions and malformed records fail safely; recovery of both versions is
      tested.
    - *Move integrity:* stable IDs, ownership, aliases and source contents are preserved; the whole
      batch is validated before any change; occupied destinations, duplicate destinations,
      case-insensitive collisions, overlapping folder moves and ambiguous source identities are
      detected; an unrelated destination is never overwritten; intermediate paths are part of
      recovery and crash testing.
    - *Registry integrity:* exact original and replacement registry bytes and their revisions are
      recorded; recovery never overwrites unrelated registry changes; a source's identity and
      content at the destination are validated before a filesystem rename is adopted; the existing
      `registry relink` behaviour and guarantees are preserved.
    - *Recovery:* states distinguish old path, new path, temporary path, both paths, neither path
      and unexpectedly changed contents; Complete and Undo stay explicit, guarded and idempotent; a
      failed reference refresh never automatically reverses a successful identity move; unresolved
      records are kept until explicitly resolved.
    - *Concurrency:* the B2b-1 lock, Git-busy check and conservative window presence are reused;
      source, destination and temporary paths and the affected registry state are protected; B2a
      refreshes and B2b-1 transactions never consume a partially committed identity state.
    - *Architecture protection:* S0 changes to the architecture specification follow the
      technical-lead workflow and are approved before they are applied; no general exception to the
      `docs/architecture/` write guard.

## 2026-11-27: T-98 — blank lines in generated Mermaid copies (directed by the user)

Revises the placeholder of T-96 decision 3 (still in force for feature documents: a blank source
line is written as a comment line so the block has no blank line for Mark Sharp). U13 and U14 are
unchanged.

1. **Defect and cause (reproduced).** T-96 wrote each blank line as a bare `%%`. Mermaid's comment
   pre-processing (`cleanupComments`, `/^\s*%%(?!{)[^\n]+\n?/gm`, the same code in all three bundles
   tested) removes only `%%` lines with at least one character after `%%`, so a bare `%%` reaches
   the diagram grammar. Rendered with Feature Designer's Mermaid 12.3.0, Mark Sharp 1.13.0's bundled
   11.16.0 and the VS Code Markdown preview extension's 11.12.2 (bierner.markdown-mermaid 1.32.1):
   the five flowcharts with blank lines (AD-0001, AD-0010, AD-0011, AD-0012, AD-0014) draw a node
   labelled `%%`; the ER diagram AD-0003 does not render at all (parse error); the sequence diagram
   AD-0013 is unaffected. Probes: class diagrams also draw the node, ER diagrams also fail inside an
   entity block; state, mindmap, gantt and sequence diagrams are unaffected. The Feature Designer
   renders the generated copy, so it showed the defect too. No blank line of the 14 architecture
   diagrams is inside a quoted or Markdown-string label.
2. **Placeholder.** Blank (and whitespace-only) source lines are now written as `%% (blank line)`
   (`diagrams.BLANK_LINE`), at column 0. In every renderer and diagram type tested (the 7
   registered diagrams and 7 probes), the copy renders identically to the source with its blank
   lines (normalised SVG, rendering made deterministic). It has text after `%%` (removed before
   parsing), no trailing space (nothing to lose to whitespace trimming), is not `%%{` (directive
   syntax), cannot be mistaken for a `%% diagram-type:` marker, and tells a reader what it stands
   for. Three other candidates (`%% blank line`, `%%-`, `%% ---`) rendered identically too; this one
   was chosen as the most readable and the least likely to occur in a source by chance. Nothing
   else in the copy changes (indentation, line order, fence, caption).
3. **Fingerprints (U13, unchanged).** The new text is a change to what the source generates, so
   every existing copy of these 7 diagrams in a feature document moves as follows: untouched
   (`B ≡ F`) → case 1, refreshed by `index` and by the Feature Designer in documents without unsaved
   changes; edited by hand → case 3 ("both changed"; the source itself did not change, only the
   generated text), a conflict (E15) never overwritten, reconciled explicitly; a marker without a
   fingerprint (before U13) → preserved and reported (E15), as for any other difference. Copies of
   diagrams without blank lines are unchanged. No committed feature document has a diagram block,
   so `index` changes nothing in the repository.
4. **Apply to source (reverse mapping).** A `%% (blank line)` line and a bare `%%` line (the T-96
   form, still found in blocks generated before T-98) both become a blank line again. Unchanged
   ambiguity, documented: a source line that is literally a bare `%%` is copied as it is and comes
   back as a blank line; a whitespace-only source line comes back as an empty line (its spaces
   are not kept, as before T-98). New: a source that literally contains a `%% (blank line)` line is
   refused by Apply to source with an explanation (the copy itself is generated and renders the same;
   Discard manual change still works), so the new placeholder is never read back wrongly. Only an
   exact line is a placeholder; an indented or annotated comment is ordinary Mermaid content.
5. **U14 not affected.** Architecture documents (M1, later) get verbatim copies; the placeholder
   applies to feature documents only and is one constant in `render()`.
6. **Evidence and limits.** Harness, JSON results and screenshots:
   `t97-completion-evidence/t98/` (outside the repository). GitHub's renderer cannot be run locally
   and was not tested; it uses Mermaid and is expected to share `cleanupComments`. Mark Sharp's
   Mermaid was run from its own bundle, with one statement appended in memory to reach its Mermaid
   object. The real Mark Sharp 1.13.0 was also driven in the GUI suite (steps 11g, 11h): after its
   save, and after a reopen, an edit and a second save, the placeholder line is still in every
   copy, unchanged and in place, and Mark Sharp shows no `%%` node and no syntax error. One copy,
   which Mark Sharp reads as part of the list before it, is still reformatted by Mark Sharp
   (indentation dropped, blank lines added): the known behaviour behind step 11f, with the same 4
   conflicts as before T-98, reported as E15 and restored by Discard manual change.

## 2026-11-27: T-97 PR B2b-2b — Feature Designer rename integration (implementation choices)

Implements plan stages S3-S4 of the approved B2b-2 plan (C6, R2, D2, G1-G12 unchanged). Choices made
while implementing, for review:

1. **The pre-rename snapshot is its own read-only operation** (`rename-preview`). `move-plan` mode
   adopt validates the state *after* a rename (the old path must be gone), so before the rename it
   can only refuse. `rename-preview` reuses the same helpers (moves.py) and returns the registered
   sources at or under each old path, their SHA-256, the registry revision, the architecture
   notice cases (G5), held paths (G9) and warnings; nothing is refused, because VS Code cannot
   cancel a rename. The adoption itself still goes through `move-plan` mode adopt with each
   `sha256`. The snapshot waits at most 4 seconds (`waitUntil` with a timeout); without it, the
   sources are identified from disk (E6) and adopted without a checksum, which the prompt says.
2. **`registry adopt-moves --sha256 HEX`**, repeated once per `--from`/`--to` pair, binds the
   checksum taken before the rename (the JSON `move-plan` already accepted it). Feature Designer
   passes a checksum for every source of a batch or for none, never a mixture.
3. **Move the files back is a new mode of the B2b-2a engine, `restore`** (CLI `registry
   move-back --from NOW --to REGISTERED [--sha256]`; designer `move-plan` mode restore). In that
   state the registry still names the old paths, so `registry move` cannot express it. A restore
   record is version 2 with renames only (tool-initiated, the same compare-and-swap renames,
   intermediate path for case-only, rollback, Complete/Undo/Abandon) and no `registry` operation:
   it records the registry's SHA-256 (`registry_sha`) and never writes the registry; Complete is
   refused if the registry changed since it was prepared. While it is unresolved it holds the
   registry like any move record (Q1). Validation: the diagram's identity and owner in the file,
   the bytes from before the rename when given, the registered path free in any letter case,
   links, held paths, open windows (conservative presence), Git, the approved folders on both
   sides (`docs/architecture/` refused), and no ID at two unregistered paths. **The write set was
   not widened**: a file moved outside the approved `diagrams/` folders (or under
   `docs/architecture/`) is not moved back by the tooling; the prompt says so and VS Code's own
   Undo (or a manual rename) moves it back.
4. **"Nothing preselected" in a VS Code modal.** The prompt is one VS Code modal per batch.
   Because the custom dialog focuses its first button, **Not now** (which writes nothing) is
   listed first; Escape, Cancel and closing the dialog are also Not now. No writing choice is a
   default, and every writing choice needs a click.
5. **A batch is adopted as far as it can be.** Each file is checked on disk after the rename;
   one that changed, is missing, or that the tooling refuses (for example moved outside the
   approved folders) is listed with its reason and not adopted. The rest is offered as one
   adoption only when it is possible as a whole. Move the files back is all or nothing.
6. **Letter case from disk.** VS Code reports a case-only rename with the file's old letter case on
   Windows (its URIs are canonicalised), so the new path is read back from the folder after the
   rename. A path that did not change on disk was not renamed and is not prompted for. Through the
   extension API (`WorkspaceEdit.renameFile`) VS Code performs no case-only rename at all on
   Windows; the GUI tests therefore use the Explorer (F2) for case-only renames.
7. **Event storms (C5).** The file events of one rename batch count as one event. When the
   registry follows a batch of more than five sources, the following refresh is treated as a
   storm: open documents get the one summary with Refresh now instead of automatic refreshes.
8. **Moved-sources strip row (E6).** "N moved sources: registry not updated" counts the moved
   sources found (adoptable or not) and those found at several paths; missing sources (E7) are
   reported in the same row; architecture sources are never offered (G5). It is derived from disk
   by the read-only `moved` operation on start, on file and registry changes and after every
   prompt, in every Feature Designer window. A checksum taken before a rename in the same session
   is reused when that rename is adopted later from the row; nothing is persisted for Not now (G3).
9. **Warnings that cannot prevent anything** (G9 held paths, unsaved sources in another window,
   collisions, links, folders outside the approved ones, Git) are shown in the prompt; a rename
   that affects only a held document, or only architecture paths, gives a non-modal warning or
   the G5 notice instead of a prompt.
10. **Recovery wording.** Version 2 records are shown in Resolve Interrupted Update as "Registry
    move" with their kind (tool-initiated, observed, move back), per-rename and registry states,
    and Complete/Undo/Abandon labels for moves; version 1 records keep their wording. The designer
    `transactions` operation also returns `cleanup` (as `transaction status` lists it), shown as
    "Cleanup pending". An unresolved move record holds every open document in Feature Designer,
    as the design tooling already does (Q1), with its own strip wording.
11. **Test infrastructure.** The GUI harness port can be overridden (`FD_GUI_PORT`, default 9341
    unchanged) so two worktrees can run GUI tests at once; the test helper gained `rename` (a
    `WorkspaceEdit` rename, which runs the same will/did-rename participants as the Explorer) and
    `reveal`.

## 2026-11-27: T-97 M1 — implementation choices

Draft for review, recorded with the M1-0 tooling PR. Design: technical-lead's M1 execution
specification (sections 4 and 5); the open questions were decided by the main conversation under
the user's completion authorization of 2026-11-27.

1. **C1: architecture copies are reported and applied by technical-lead, never automatically.**
   U5 and diagram library 6.4 item 2 (copies refreshed automatically when the source changes) do
   not apply to `docs/architecture/`: the tooling never writes there, and the write guard
   (`ownership.guard_write`) stays exactly as strict, with no general or move-specific
   exception. When a standalone source changes, `check` and `index --check` report the copy
   (out of date, fingerprint only, or a conflict, E15); `index` only warns. technical-lead applies
   the exact text printed by `python -m tools.design architecture copy` (read only) with its own
   tools, and `check` and `architecture verify` prove the result. `reconcile` and `refresh-blocks`
   keep refusing these documents. This narrows an approved behaviour in the direction the user
   chose (the T-97 card's recorded preference).
2. **Q1: source file names** are those of diagram library 12.3 (`<owner-slug>_<category>_<name>.md`
   in `docs/architecture/diagrams/`), not `slugify(title)` names; names are never parsed for
   identity. `architecture verify` checks each extracted diagram's path against this list.
3. **Q2: feature captions** of an extracted diagram use the registry title and link to its
   standalone source (`diagrams._registered_source`, unchanged); a feature block that names the
   diagram or one of its aliases becomes case 1 once and `index` refreshes it.
4. **Q3: GitHub rendering** is checked on the pushed PR branches (rendered file view or the
   rendered-HTML API); where it is not checked it is recorded as "expected, not verified".
5. **Q4: `mermaid-embedded` stays an accepted format** after M1, for `registry extract --revert`
   and for history, with no active entries left once all four documents are done.
6. **Q5: feature-owned (proposed) diagram blocks are refused in `docs/architecture/` documents**:
   current-state documents show only document-owned diagrams. A region naming a feature-owned,
   retired, unknown or still-embedded ID is a `check` problem.
7. **Q6: new document-owned diagrams after M1** (interim process): technical-lead writes a
   document-owned source in `docs/architecture/diagrams/` and the main conversation runs
   `registry adopt`. A command that hands out the next `AD-` ID is a backlog item.
8. **Byte identity is defined on LF content**, which equals the Git blob (C8): the Windows working
   tree may be CRLF (`core.autocrlf=true`, no `.gitattributes`). Fingerprints, the snapshot, the
   V4 invariant and every comparison normalise CRLF to LF and nothing else.
9. **Counting by registry identity (U9).** `architecture.catalog()` never counts a Mermaid fence
   inside a generated region; `architecture.architecture_diagrams()` lists each diagram once
   (embedded entry, extracted entry positioned by its copy, or an unregistered raw block), and the
   architecture index, the Feature Designer library and the tests count with it, so the count is
   14 in every M1 state. A raw block whose catalog ID is an alias of an extracted entry is that
   entry's duplicate (reported, never counted). The architecture index gains one column, Source
   (`embedded` or a link to the standalone source); its rows' Diagram ID is the registered alias.
10. **Generated copy layout** (specification 3.1): start marker with the canonical ID and the U13
    fingerprint; an invisible comment line naming the ID and the source path relative to the
    document; the Mermaid lines verbatim in a fence; the end marker. No caption and no blank-line
    placeholder (U14): blank lines stay blank, neither the T-96 `%%` nor T-98's `%% (blank line)`
    (`diagrams.BLANK_LINE`, which applies to feature-document copies only); `verify` (V3) reports
    any `%%` line of a copy that its source does not have. The legend paragraph above stays
    hand-written outside the region. The renderer is separate from `diagrams.render()` and
    refuses a fence that would differ from the source's own. The printed replacement's old text
    is widened with unchanged lines above until it occurs once in the document (a raw block can
    equal the copy's Mermaid), and deleting a duplicate raw block also removes one of its
    surrounding blank lines, so the document is exactly as it would be without the block (V4).
11. **New `check` reports:** extraction pending (a source in `docs/architecture/diagrams/` whose
    ID is still registered as embedded), duplicate raw block (E2 family), not shown (U3), and the
    copy states (structure, E1, E11, Q5, embedded, E15 cases with technical-lead's fix, E14-like
    wrong source path, and a copy in an architecture document that does not own the diagram:
    each diagram is shown only in its owning document). None suggests `index` or `reconcile` as
    the fix for a copy. A proposed diagram file citing an extracted diagram whose copy is not shown
    yet gets an accurate `source_heading` message instead of "under #(no heading)".
12. **`registry extract`** (main conversation): one document per run, all its diagrams at once;
    the plan validates the whole batch (each entry an active embedded document-owned diagram, the
    path in the approved folder with exact case, a regular file and not a link (no symbolic link
    or junction on any component from the repository root down, and a resolved path that stays in
    the repository; hard links refused), not registered
    for another entry, distinct paths; front matter exactly `diagram_id`, `title`,
    `owner_document` with the registry's values and no `feature_id`; exactly one fenced block,
    the Mermaid block, byte-identical to the raw block including its fence lines; the snapshot
    readable and equal for that ID) and prints a token over the registry, document, sources and
    snapshot bytes. `--confirm TOKEN` reruns everything under the registry lock, after the
    transaction guard (Q1) and the Git-busy check (D4), and replaces the registry by
    compare-and-swap (only `format` and `path` change; `anchor` and `ordinal` are removed) after
    validating the whole plan once more, inside the lock, immediately before the replacement (a
    source, the document or the snapshot changed in between refuses it; nothing is written; the
    remaining window between that validation and the compare-and-swap is accepted: an edit made to
    a source or the document in it is caught afterwards by `check` and `architecture verify`, V3
    and V4), then
    writes the diagram index inside the lock (D3). It writes only `designs/diagrams/registry.yml`
    and `designs/index/diagram-index.md`. `--revert` is the guarded undo (same lock, guards, token
    and CAS) so the registry is never restored with Git.
13. **`architecture snapshot` and `architecture verify`**: the snapshot (JSON version 1, written
    once, whole (a temporary file, then a link that fails if the name exists), to a new file
    outside `docs/architecture/`, never overwritten) records the commit, every architecture
    document's LF text and SHA-256 and every diagram's registry fields and exact Mermaid and fence
    lines. It is refused once any diagram is extracted, without a commit, and when any
    architecture document's LF text differs from its blob at HEAD (a clean worktree). `verify`
    checks V1-V6 (V2 also compares `anchor`, `ordinal` and the heading of a still-embedded
    diagram, so a revert to the wrong heading fails; a missing owner document is a V3/V4 failure,
    never an error) and reports V7 (`check` and `index --check` are run separately).
14. **Feature Designer.** `designer_api.library()` builds the architecture groups from
    `architecture_diagrams()`; for an extracted diagram `path` and `line` are those of its
    standalone source (Edit Diagram opens it with the architecture-docs notice). No extension
    change. Unit and GUI assertions that name `docs/architecture/system-architecture.md` as the
    source of `AD-0011` must be made state-independent before M1-4 (they read the resolved
    source).
