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
