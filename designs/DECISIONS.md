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
