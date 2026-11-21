# Orlando Feature Design Workspace — Implementation Brief for Claude

**Status:** Approved concept; **not implemented**. Execute only after T-83 is finished and its final state is committed/verified.

## Purpose

Build a **file-based, Markdown-first feature design workspace** inside the Orlando infrastructure repository. The user must be able to open one feature specification, work through six design questions, navigate to existing architecture documents and individual Mermaid diagrams, develop proposed diagrams, and understand **actual system and feature dependencies** before authorizing code changes. Do not build a web app, database, visual editor, or speculative dependency graph.

## Prerequisite: repository discovery gate (must happen before implementation)

Claude must inspect the **actual current repository**, not rely on paths or relationships in this brief as facts. Inventory:

1. Existing `docs/architecture/` and related Markdown files, their headings, Mermaid fences, and diagram rendering conventions.
2. Actual database schemas/migrations, ETL, source connectors, SQL, API routes, UI components, and available tests.
3. Final T-83 `registry/components.yml`, `impact.yml`, CLI behavior, documentation mappings, and whether T-83 has a component-to-component graph (do not assume it does).
4. Git branch/working-tree status, existing design/feature folders, and current naming conventions.
5. What VS Code Markdown preview and Mermaid support actually render; check portability to GitHub.

**Gate output:** a short audit listing verified paths, missing information, constraints, recommended conventions, and any conflicts with T-83. **Stop for user approval before modifying the repository.** This audit is part of the workspace project, not a separate initiative.

## Nonnegotiable design principles

- `docs/architecture/` describes the **verified, implemented current state**. `designs/` contains **working/proposed designs**; never silently overwrite current-state docs.
- Every claim/relationship is tagged **verified**, **proposed**, or **unknown**, with source evidence for verified claims.
- Reuse existing documents and diagrams via links first; avoid duplicating them. Proposed modifications are stored separately and cite the original file, heading/diagram ID, and Git revision when feasible.
- Support both **text-first** and **diagram-first** work. Mermaid remains editable source, not a static image.
- A feature can be one `.md` file or a folder containing subfeatures. Do not enforce a deep folder hierarchy for simple features.
- Stable feature IDs are distinct from file paths. A move/rename must not change identity or silently break references.
- Maintain **one canonical declaration per feature dependency**; derive reverse 'used by' views instead of manually maintaining both sides.
- Never infer that a dependency means an impact is certain. Distinguish direct dependency, possible downstream impact, and verified required modification.
- Use repository-relative paths, not fabricated `https://docs/...` links or external tracking parameters.

## Proposed structure (adjust only after audit)

```text
designs/
  README.md                         # start here; navigation and conventions
  templates/
    feature-spec.md                 # six-section template
    diagram.md                      # editable Mermaid starter and provenance
  features/
    road-pipe-coordination/
      README.md                     # parent feature overview (optional)
      pipe-road-intersections.md    # subfeature
      maintenance-prioritization.md # subfeature
      diagrams/
        proposed-intersections.md
      evidence/                     # only when needed
    pavement-condition.md           # simple feature, no folder needed
  index/                            # generated, if warranted
    architecture-index.md
    feature-index.md
    dependency-index.md
```

Names are **examples, not claims about existing features**. A single feature `.md` is sufficient when no supporting assets exist. Parent feature folders can nest further when justified. Use relative Markdown links resolved from the actual file location.

## Six-section feature specification (mandatory)

Each feature has a stable `feature_id`, title, lifecycle status (`investigating`, `proposed`, `approved`, `implementing`, `verified`, or `deferred`), owner/branch if relevant, and a short list of architecture references. Prefer readable YAML front matter **only if compatible with the existing repository tooling**; otherwise use a clearly delimited metadata section.

### 1. Objective
What real problem is solved? Who needs the result? What measurable or observable outcome is required? Link to evidence; do not invent use cases.

### 2. Data contract
List verified source systems, endpoints, fields, types, IDs, geometry types, coordinate systems, limits, refresh behavior, required outputs, and unknowns. Record evidence paths/URLs and any test/sample confirming claims. Distinguish source fields from normalized database fields.

### 3. Logic
Document the processing sequence, SQL and spatial operations, assumptions, expected inputs/outputs, and small testable examples. Use Mermaid flowcharts where helpful. Proposed logic must not be presented as running code.

### 4. Dependencies — TWO EXPLICIT TABLES

**System components** (reference real schema/code/docs and relationship type):

| Component | Relationship | Reference | Evidence status |
|---|---|---|---|
| Roads table *(example)* | Reads road geometries | Link to actual database schema/table | Proposed until verified |
| Pipes table *(example)* | Reads pipe geometries | Link to actual database schema/table | Proposed until verified |
| Spatial SQL *(example)* | Calculates intersections | Link to actual query or planned design | Proposed until verified |
| API *(example)* | Returns intersection results | Link to actual endpoint/code or planned design | Proposed until verified |

**Related features** (stable IDs and links to other feature specifications):

| Feature | Relationship | Reference | Evidence status |
|---|---|---|---|
| Road ingestion *(example)* | Prerequisite for this feature | Feature ID + relative Markdown link | Proposed until verified |
| Pipe ingestion *(example)* | Prerequisite for this feature | Feature ID + relative Markdown link | Proposed until verified |
| Maintenance prioritization *(example)* | Depends on this feature | **Generated reverse reference**, not duplicate manual metadata | Proposed until verified |

Relationship vocabulary should be small and clear: `depends_on` (feature prerequisite); system relationships such as `reads_from`, `writes_to`, `calls`, `exposes`, and `renders` **only when supported by evidence**. Do not conflate `related_to` with `depends_on`. Optional/conditional dependencies must be labeled. Detect broken links, missing feature IDs, duplicate IDs, and dependency cycles; report cycles for review rather than automatically resolving them.

### 5. Downstream impact
List **confirmed affected** contracts, schemas, queries, ETL, endpoints, UI, tests, diagrams and documentation separately from **potentially affected** or **unknown** items. Link evidence. A dependency edge is a reason to investigate, not proof of necessary modification.

### 6. Acceptance criteria
List verifiable expected results, correctness checks, edge cases, API limits/pagination where relevant, performance expectations, tests and explicit evidence required for acceptance. Unknown benchmarks should be marked unknown, not fabricated.

## Phase 1 — folders and templates

1. Create the minimal `designs/` structure and a concise `README.md` describing where to begin and how feature hierarchy works.
2. Create the six-section `feature-spec.md` with both dependency tables, status/evidence markers, optional Mermaid blocks, and links to architecture references.
3. Create a `diagram.md` template with a Mermaid code fence, diagram title/ID, source document + heading/ID, base Git commit, and `proposed` status.
4. Implement a **New Feature command** as part of Phase 1 (not optional): a lightweight repository-local script or VS Code task, without an unnecessary framework. It must prompt for a feature name and optional parent feature/folder, then create a `.md` specification prepopulated with the complete six-section template, both dependency tables, architecture-reference placeholders, and proposed-diagram links/slots. Assign a unique stable `feature_id` independent of filename/path, and make the feature discoverable in the workspace index (regenerate an index or use a deterministic discovery mechanism). Support standalone features, nested subfeatures, and paths with spaces safely. Validate names and destinations, avoid overwriting existing files, and report errors clearly. Do **not** create a Git branch or commit automatically. Document the exact command and a VS Code task shortcut if practical. Creating a blank `.md` manually does not auto-populate unless a separate editor-specific mechanism is installed; the supported workflow is **New Feature**.
5. Add **one clearly labeled illustrative feature** only if needed to demonstrate navigation; do not represent it as an existing implementation.
6. Document how to create a feature branch, when to branch, and how to keep proposed design separate from verified architecture. Do not auto-create branches or commits without approval.

**Phase 1 acceptance:** user can invoke **New Feature**, supply a name and optional parent, and receive a correctly named, fully populated Markdown feature specification with a unique stable ID and discoverable index entry; the command must not overwrite files or silently change Git state. User can fill all six sections, open linked current-state docs, and preview a proposed Mermaid diagram in VS Code. Verify both standalone and nested creation, duplicate-name handling, and repeatable index generation.

## Phase 2 — architecture and diagram navigation

1. Generate an **architecture index** from the actual `docs/architecture/` tree, with direct links to each document and stable headings/diagram anchors where supported.
2. Catalog individual Mermaid diagrams using deterministic IDs. Where existing diagrams have no stable ID, propose a minimally invasive naming convention and seek approval before editing current docs.
3. In a feature file, provide a simple **Architecture references** section and collapsible `<details><summary>…</summary>…</details>` groups when the chosen Markdown renderer supports them. Links must remain usable without the collapse UI.
4. Provide a simple, documented workflow for **link existing diagram**, **create proposed diagram**, and **copy an existing diagram into a proposed variant**, preserving source path and base revision. Start with templates and links; a VS Code task/script is optional only if it demonstrably reduces repetitive work.
5. Generate a **feature index** and **dependency index** from stable IDs and canonical dependency declarations; integrate them with the Phase 1 New Feature command without requiring manual registration. Display both 'depends on' and generated 'used by' links. Preserve readable output even without Mermaid support.
6. Optionally generate a Mermaid feature dependency graph from verified metadata; mark proposed edges and avoid presenting a graph as verified when it isn't.
7. Validate links, IDs, references, and generated-index freshness; make generation deterministic and idempotent. Do not add an unnecessary runtime dependency or broad framework.

**Phase 2 acceptance:** opening one feature spec provides navigation to relevant existing architecture documents/individual diagrams, links to related features, a place for proposed diagrams, and generated reverse dependency navigation without manual double entry. Indexes regenerate after additions/renames. Broken links and unknown dependencies are surfaced.

## T-83 integration — design now, implement later only if justified

**T-83 is a documentation-impact engine, not necessarily a full runtime/system dependency graph.** Its component registry and path-to-document relationships may be reusable; inspect the final implementation first. Do not modify T-83 or overload `impact.yml` to pretend it understands table-level, SQL-level, or feature-to-feature dependencies.

Potential future integration:

1. Link diagram nodes to stable component IDs where evidence exists.
2. Build a separately validated system relationship layer if T-83 lacks it.
3. Use T-83 change findings as **documentation-review signals**.
4. Traverse independently verified feature/system edges to highlight **potentially affected** diagrams/features, not automatically assert broken functionality.
5. Show a distinction between `changed`, `directly referenced`, `potentially downstream`, and `unverified`.

**Do not implement dependency highlighting, editor integration, or an interactive UI in Phases 1–2.** Reserve extension points and document what evidence would be required.

## Implementation protocol and approval gates

- **Gate 0:** Complete T-83; ensure its current code/docs are stable and committed.
- **Gate 1:** Claude performs read-only repository audit and presents findings + adjusted plan. User approves.
- **Gate 2:** Implement Phase 1 only. Run Markdown/link/preview checks. Show example. User approves.
- **Gate 3:** Implement Phase 2. Verify indexes, stable IDs, relative links, diagram anchors, nested features, reverse dependencies, broken-link/cycle handling, deterministic output. User approves.
- **Gate 4:** Decide later whether deeper T-83 integration is warranted, based on actual use.

At each gate, report files created/modified, tests run/results, known limitations, and any architectural choices requiring approval. Do not push, merge, or change existing T-83 internals without explicit approval. Keep generated indexes clearly marked as generated; don't manually edit generated outputs.

## Out of scope

Custom web app, live visual drag-and-drop editing, real-time code dependency inference, automatic SQL generation, automatic correctness guarantees, automatic rewriting of `docs/architecture/`, speculative GIS data mappings, and automatic code changes triggered by diagrams.

## First instruction to Claude (after T-83)

> Read this implementation brief. **Do not implement yet.** First inspect the actual repository and completed T-83 implementation. Produce the Gate 1 audit: verified architecture document and Mermaid inventory, component/relationship capabilities, existing folder conventions, Markdown rendering constraints, proposed exact file layout, risks, and any decisions requiring my approval. Explicitly distinguish verified facts from proposals. After I approve the audit, implement Phase 1; stop again before Phase 2.
