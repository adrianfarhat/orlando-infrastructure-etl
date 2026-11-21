# Task Board

What lives where (details in
[conventions.md § Where task information lives](../architecture/conventions.md#where-task-information-lives)):

- **Task status, scope, priority, wave, dependencies and acceptance criteria** are
  on the task cards in [GitHub Project #1](https://github.com/users/adrianfarhat/projects/1)
  (private). Every card is linked from the [Task index](#task-index).
- **This file** holds the task index (navigation only), findings, decision
  outcomes, risks and the [Evidence log](#evidence-log).

A Project card moves to Done only after its verification results are recorded
in the [Evidence log](#evidence-log).

Dependency and wave diagrams, a navigation view derived from the Project:
[development-status.md](development-status.md). Documentation conventions:
[conventions.md](../architecture/conventions.md).

## Findings (from the 2026-11-16 repository inspection and later reviews)

These are open issues, **not completed work**.

These findings come from the 2026-11-16 read-only team inspection (proposed by the technical-lead and saved with user approval) and later reviews; unless a finding says otherwise they come from code reading and none has been verified live. Saving a finding or task does not approve any action listed against it.

| ID | Finding | Evidence | Suggested owner | Approval needed |
|---|---|---|---|---|
| F-01 | **Application files are untracked in git.** The working app is not in version control. | `git status`: `?? web/`, `?? extractors/load_orlando_manholes.py`. Only one commit (`7281786`). | User / main conversation | Yes (commit) |
| F-02 | **There are no automated tests.** ETL, API and frontend have no unit, integration or regression tests, and there is no test runner. | No test files or test config. `web/package.json` has no `test` script. | integration-qa (plan); backend/frontend (implement) | Yes, if new dev dependencies are needed |
| F-03 | **The web app has full database privileges.** The API connects as `neondb_owner`, which owns the tables and can change or drop them. There is no read-only role. | `current_user` = `neondb_owner` | data-gis (propose); user (apply) | Yes (role/grant change) |
| F-04 | **The `road_segments` table definition is not in the repository.** The streets loader assumes the table exists. Its unique key (`source_objectid`) differs from the other tables, and `imported_at` can be null. | `extractors/load_orlando_streets.py` has no `CREATE TABLE`. Checked in the live database's constraint list. | data-gis | Yes (if a migration is proposed) |
| F-05 | **The features API is missing what an asset inspector needs.** It returns no feature ID, source ID or attributes (`properties` = `{layer}` only), and caps each layer at 2,000 features with no paging or zoom-based detail. | `web/src/app/api/infrastructure/features/route.ts` | technical-lead (contract) → backend → frontend | Contract change |
| F-06 | **Asset inspector, schema manager, IoT schemas and the `demo` schema do not exist.** | No related code or tables | technical-lead | Architecture/migration |
| F-07 | **The dashboard and map changes are not checked in a browser.** The `/stats` route, dashboard and layer toggles pass the type check and lint, and the API response was checked with curl, but they have not been checked by hand in a browser. | Session of 2026-11-16 | integration-qa | No |
| F-08 | **Node/npm is not on the PATH of Claude Code's shell**, so agents cannot run `npm run build`, lint or the type check normally. | `npx: command not found` | User | Environment change |
| F-09 | **Python dependencies are not declared.** There is no `requirements.txt` or lock file; packages are only installed in `.venv`. | Repository root | data-gis (propose) | Dependency file change |
| F-10 | **`DATABASE_URL` is stored in two places**: the root `.env` and `web/.env.local`. They could drift apart. (Corrected 2026-11-16: `load_dotenv()` with no path, when run as a script, searches upward from the script's own directory (`dotenv/main.py:361-375`), so the streets loader is not CWD-dependent. `database/test_connection.py` now loads the root `.env` explicitly (T-50).) | File inspection | data-gis / backend (propose) | Env change |
| F-11 | **Manholes come from an ArcGIS `Test` service folder**, and the wastewater loader notes that data-use permission must be checked. Provenance and terms of use are not documented. | `extractors/load_orlando_manholes.py:25-29`, `load_orlando_wastewater.py` docstring | data-gis / user | No |
| F-12 | **The home page `/` is still the Next.js starter template.** The Explorer is only reachable at `/operations/map`. | `web/src/app/page.tsx` | frontend | No |
| F-13 | **The project has no README.** `web/README.md` is the create-next-app default. | Repository root | technical-lead | No |
| F-14 | **Data quality: the manhole and pipe extents are identical.** The bounding boxes match to every decimal place. This is plausible if the outermost manholes sit at pipe ends, but it has not been checked. | `ST_Extent` on both tables | data-gis | No |
| F-15 | **There is no navigation index for the docs.** No diagrams of the system, ETL, schema or work status. Added on 2026-11-17: `docs/architecture/system-architecture.md`, `etl-workflow.md`, `database-schema.md` and `docs/agents/development-status.md` (technical-lead, user-approved docs workspace). The Mermaid diagrams have not been checked for rendering. | `docs/` listing | technical-lead | No |
| F-16 | **CLAUDE.md named `task-board.md` as the task record.** When found, `CLAUDE.md` line 9 (work-status link), lines 29–40 ("How work is coordinated") and rule 8 pointed task coordination at `task-board.md`. The documentation consistency PR (2026-11-18) updated them to point task coordination at Project #1. What remains for T-05 is the Git branch and pull-request workflow sections. | `CLAUDE.md` line 9, lines 29–40 and rule 8 as of the T-80 review, 2026-11-17; updated in the documentation consistency PR, 2026-11-18. | main conversation (user approval) | Yes (CLAUDE.md change) |
| F-17 | **T-82's legend check conflicts with `conventions.md`.** T-82's acceptance says "each diagram carries the legend"; `conventions.md` § 2 applies the legend to architecture diagrams only. A lint cannot tell diagram types apart without a diagram-type marker in each block. | T-82 acceptance; `docs/architecture/conventions.md` § 2. T-80 review, 2026-11-17. | technical-lead (conventions); main conversation (T-82) | No |
| F-18 | **Wave inversion: T-85 (Wave 2) depended on T-59 (Wave 3 when found).** T-59 wave history: Wave 3 when found; moved to Wave 2 on 2026-11-17 (F-18); moved to Wave 1 on 2026-11-18 because T-83 needs PyYAML (later changed to ruamel.yaml, which has a pure-Python package for Python 3.15; see T-59). | Project fields and "Depends on" of T-85 and T-59. T-80 review, 2026-11-17. | technical-lead / user | No |
| F-19 | **Path conflict for the schema baseline.** T-86 targets `database/migrations/0001_baseline.sql` "(path per D-8)", while D-8's recommendation is `database/schema/road_segments.sql`. T-86 also overlaps T-53 (the `road_segments` DDL file). Alternatives: (A) D-8's single reference file under `database/schema/`; (B) T-86's `database/migrations/0001_baseline.sql` for all 3 tables; (C) B with migrations as the only hand-written DDL and the readable schema generated by T-87, which would supersede T-53. C is the preferred direction for future consideration (technical-lead and user), **not a decision**: it does not authorize implementation, superseding T-53 or changing D-8. | T-86 acceptance; D-8 row; T-53 scope. `docs/doc-map.yml` assumes `database/migrations/**`. T-80 review, 2026-11-17. | user (D-8, T-53) | User decision |
| F-20 | **The proposed ER diagram draws computed spatial links as plain ER relationships**, with no method or parameters, against `conventions.md` § 4. | `docs/architecture/database-schema.md` § 2 (target model), for example "nearest segment" and the road/pipe overlap links. T-80 review, 2026-11-17. | technical-lead | No |
| F-21 | **Three tasks edit `CLAUDE.md` with incomplete ordering.** T-04, T-05 and T-84 all edit it; T-84 depends on T-05, but T-04 has no ordering against either. | Summary-table "Depends on" for T-04, T-05 and T-84. T-80 review, 2026-11-17. | technical-lead / user | No |

### Finding → task cross-reference

| Finding | Covered by |
|---|---|
| F-01 | → T-02 (may be stale: `git status` on 2026-11-16 showed only `.claude/settings.json` untracked) |
| F-02 | → T-70 |
| F-03 | → T-57 |
| F-04 | → T-52, T-53, T-56 |
| F-05 | → T-20, T-21, T-23 |
| F-06 | → T-60 |
| F-07 | → T-01 |
| F-08 | → T-02, T-04 (integration-qa reports Node reachable through fnm v26.13.0) |
| F-09 | → T-59 |
| F-10 | → T-55, T-58 |
| F-11 | → T-54 |
| F-12 | → T-43 |
| F-13 | Not yet planned |
| F-14 | → T-52 |
| F-15 | docs workspace added 2026-11-17 (see Evidence log) |
| F-16 | → task-coordination text in `CLAUDE.md` updated in the documentation consistency PR (2026-11-18); the Git/PR workflow sections → T-05 |
| F-17 | → T-82; docs corrected in PR #2 (conventions § 2 marker rule, T-82 acceptance); T-82 card text synchronized 2026-11-17. |
| F-18 | → T-59 wave history: Wave 2 on 2026-11-17 (PR #2; card synchronized the same day); Wave 1 on 2026-11-18 because T-83 needs PyYAML (later changed to ruamel.yaml, which has a pure-Python package for Python 3.15; see T-59) |
| F-19 | → T-86, D-8, T-53 |
| F-20 | → docs corrected in PR #2 (database-schema.md § 2 diagram and the proposed spatial-relationships table); T-88 owns the section for the built schema. |
| F-21 | → docs corrected in PR #2 (order T-05 → T-84 → T-04); T-04 card "Depends on" synchronized 2026-11-17. |

## Task index

Navigation only. Each link opens the task's card, which holds its status,
scope, priority, wave, dependencies and acceptance criteria. Titles are the
card titles as of 2026-11-18.

### Baseline and workflow

- [T-01](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-01): Baseline verification (build, live API, browser)
- [T-02](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-02): Confirm whether F-01 and F-08 are stale
- [T-03](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-03): Find the source of the 1,103 lint warnings
- [T-04](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-04): Update CLAUDE.md (Node through fnm) and the lint config if needed
- [T-05](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-05): Adopt Git branch and pull-request workflow (CLAUDE.md)

### API and backend

- [T-10](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-10): Features route: stricter input validation
- [T-11](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-11): `db.ts` hardening: lazy env check, pool error handler, timeouts
- [T-12](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-12): Safer server-side error logging in all three routes
- [T-20](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-20): `/features` contract v2 and contract nits
- [T-21](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-21): Backend: implement features contract v2
- [T-22](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-22): Frontend: handle the new 400 and truncation meaning
- [T-23](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-23): Asset inspector UI
- [T-24](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-24): `/stats` caching

### Frontend

- [T-40](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-40): Map resilience: layer failures, errors, reload guard, debounce
- [T-41](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-41): Dashboard: truncation notice, accessible status, provenance label
- [T-42](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-42): Map accessibility, dark mode and responsive fixes
- [T-43](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-43): Metadata, home page and unused-asset clean-up

### Data, ETL and database

- [T-50](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-50): `test_connection.py`: read-only session
- [T-51](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-51): Wastewater loader writes nothing by default
- [T-52](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-52): Read-only database audit
- [T-53](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-53): Commit the `road_segments` DDL as a reference file
- [T-54](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-54): Manholes source provenance check
- [T-55](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-55): Make the three loaders consistent
- [T-56](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-56): Schema migrations (`road_segments` key, `last_seen_at`, `diameter_raw`)
- [T-57](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-57): Read-only database role for `web/`
- [T-58](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-58): One place for `DATABASE_URL`
- [T-59](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-59): Declare Python dependencies (`requirements.txt`)
- [T-60](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-60): Design the `demo` schema and IoT tables (design doc only)
- [T-61](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-61): Streets and manholes loaders: dry run by default, writes only with `--write`

### Testing

- [T-70](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-70): Automated test harness plan

### Documentation and change-impact framework

- [T-80](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-80): Docs conventions and doc map
- [T-81](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-81): Links and deleted-path validator
- [T-82](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-82): Mermaid validator and diagram-conventions lint
- [T-83](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-83): Change-impact engine (MVP core)
- [T-84](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-84): PR template and CLAUDE.md docs-sync rules
- [T-85](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-85): CI impact and docs workflow (advisory)
- [T-86](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-86): Schema baseline migration from Neon (read-only)
- [T-87](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-87): Schema doc generator and freshness checks
- [T-88](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-88): Consolidate schema docs and spatial-relationships section
- [T-89](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-89): Remove live task status from Markdown
- [T-91](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-91): Dataset registry and provenance (v1.1)
- [T-92](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-92): Dataset validity checks (v1.2)
- [T-93](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-93): Framework reuse and deeper analysis (v2)
- [T-94](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-94): Feature Design Workspace

### Integration gates

- [T-90](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=T-90): Integration verification (one card per wave, Wave 0 to Wave 4)

### Decision cards

- [D-1](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=D-1): Who edits the P0 files in database/ and extractors/
- [D-2](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=D-2): /features limits
- [D-3](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=D-3): Asset inspector data
- [D-4](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=D-4): Loader policy
- [D-5](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=D-5): What / shows
- [D-6](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=D-6): ArcGIS metadata GET (T-54)
- [D-7](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=D-7): Where DATABASE_URL lives
- [D-8](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=D-8): Path of the DDL file
- [D-9](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=D-9): Schema migrations (T-56)
- [D-10](https://github.com/users/adrianfarhat/projects/1/views/1?filterQuery=D-10): Test runner

Links open Project #1 (private) filtered on the task ID. For a few IDs the filter also shows a related card whose title mentions the same ID (e.g. D-1 also shows D-10; T-50/T-51 also show the PR #1 card; T-80/T-89 also show the PR #2 card; T-54 also shows D-6; T-56 also shows D-9).

## Decisions

Decision questions, options, recommendations and live state are on the D-xx cards
(see the [Task index](#task-index)). Decision outcomes are recorded below when made.

### Decision outcomes

None recorded yet. Add one dated line per decision when the user makes it:
`D-x (YYYY-MM-DD): chosen option, by whom, any conditions.`

### Risks

- Contract v2 changes what `truncated` means, so T-22 must ship with T-21 or right after it.
- The manholes source may not be approved for use (T-54).
- T-56 and T-57 change the live database. Back up or create a Neon branch first.
- This board creates no synthetic data.

## Evidence log

Dated and append-only: add new entries at the bottom and never edit old ones
(add a correcting entry instead). Each entry records what was verified or merged,
by whom and where the details are. This is evidence, not status; live status is
in [Project #1](https://github.com/users/adrianfarhat/projects/1) (private).

- **2026-11-16 · team inspection (no task).** integration-qa: `tsc --noEmit` passes; lint 0 errors / 1,103 warnings, cause unknown (`.next/**` is already ignored). T-01 and T-03 will re-run and record. (Moved from `development-status.md`.)
- **2026-11-16 · T-50.** integration-qa code checks PASS with no Neon access; the live read-only run has not been done. Details under [T-50](#t-50-test_connectionpy-read-only-session-p0).
- **2026-11-16 · T-51.** integration-qa verification: all checks PASS with no Neon access (one user-approved public ArcGIS GET). Details under [T-51](#t-51-wastewater-loader-writes-nothing-by-default-p0).
- **2026-11-17 · PR #1.** Merged to main as merge commit 5b6aa5e, containing the T-50 code (commit 714106b) and the T-51 code (commit 3cb2440).
- **2026-11-17 · F-15.** technical-lead added the docs workspace: `docs/architecture/system-architecture.md`, `etl-workflow.md`, `database-schema.md` and `docs/agents/development-status.md` (user-approved; merged with PR #1). The Mermaid diagrams have not been checked for rendering.
- **2026-11-17 · Mermaid syntax.** All 21 Mermaid diagrams in docs/ passed `mermaid.parse()` (Mermaid 11.4.1, run by the main conversation in a temporary environment outside the repository; a negative control confirmed broken diagrams are rejected). This checks syntax only: visual rendering has not yet been reviewed.
- **2026-11-17 · Project card reconciliation.** With user approval, cards T-82, T-59 (Wave field 3 → 2), T-04, T-50, T-05 and T-90 (Wave 0–4) were updated to match this board; T-10, T-51 and T-86 differences are kept intentionally (see Board/Project card differences). Card text was compared before and after each update and read back.
- **2026-11-18 · PR #2.** Squash-merged to main as `9ad2e46` (T-80 and T-89 Done; evidence lines added to both Project cards).
- **2026-11-18 · Project card update.** With user approval, 53 existing cards updated (content changes on T-05, T-51, T-59, T-80, T-81, T-82, T-83, T-84, T-85, T-87 and T-89; a new footer on 42 others) and T-91, T-92 and T-93 created. A snapshot of all 57 cards was taken first (kept outside the repository), and every card was read back.
- **2026-11-18 · Task details moved to Project #1.** Task detail blocks were removed from this file; their verification evidence was moved word for word to "Verification details" below, and the remaining lines were obsolete copies of card text, board-derived scope lines, the summary, execution-waves, card-differences and task-template sections, and board-creation notes (documentation consistency PR).
- **2026-11-17 · T-61.** Added as P0 with user approval (streets and manholes loaders: dry run by default).
- **2026-11-18 · Correction: former sections.** Earlier entries that mention "Board/Project card differences" (and other notes that cite the former Summary, Execution waves, Decisions table or task detail sections, such as F-19 and F-21) refer to the task-board structure before the documentation consistency PR of 2026-11-18. Those sections were removed; task fields now live on the Project #1 cards.
- **2026-11-18 · PR #3.** Squash-merged to main as `c22234e` (documentation consistency: GitHub Project #1 is the source of truth for task fields). The Project's "Pull request merged" automation set the PR #3 item to Done automatically.
- **2026-11-18 · T-59.** `requirements.txt` added with exact pins for direct dependencies: psycopg[binary] 3.3.8, python-dotenv 1.2.4, requests 2.34.2, ruamel.yaml 0.19.1 (chosen over PyYAML, which has no prebuilt package for Python 3.15). integration-qa: clean install into a new Python 3.15.2 venv, `pip check` clean, imports, compile and loader `--help` PASS; the project `.venv` matches the file exactly. A fresh venv ran `database/test_connection.py` (user-approved, read-only).
- **2026-11-18 · T-50 live check.** With user approval, `database/test_connection.py` was run once from a fresh venv: connected to `neondb`, PostGIS 3.6, `Read-only session: on`, exit 0, no credentials printed, no other SQL. integration-qa confirmed every T-50 criterion against the code and the reported output; it did not observe the run itself. Completes the pending item in "Verification details" → T-50.
- **2026-11-19 · T-83 Phase 83a Stage 2.** Commit `17022c1` on branch `feat/t-83-impact-engine` added the change-impact core (`impact.yml`, `registry/components.yml`, path resolution in `tools/impact/`); 103 unittest tests pass, verified by integration-qa. The migration check against the frozen fixtures of the retired doc map (`docmap_565706f.yml`, `tracked_565706f.json`: all 50 files tracked at `565706f` plus 21 edge cases) lost 0 relationships, with 4 approved additions; details in the commit message.
- **2026-11-19 · T-83 Phase 83a Stage 3.** Commit `2d7f572` added `impact validate` (CLI, findings, safe Git listing, regex safety); 211 tests pass. Four independent read-only integration-qa rounds, final verdict "no unresolved defects"; details in the commit message.
- **2026-11-19 · T-83 Phase 83a Stage 4.** Commit `ebbf84a` retired `docs/doc-map.yml` in favour of the component registry (a frozen copy is kept as a test fixture); 216 tests pass, migration check lost 0 relationships (4 approved additions). integration-qa: no unresolved defects.
- **2026-11-19 · T-83 post-83a cleanup.** Commit `5fc4230`: `conventions.md` section 5 wording (technical-lead), start-up exit codes and `--out` folder cleanup; 228 tests pass, registry, `impact.yml` and frozen fixtures unchanged. integration-qa: no unresolved defects.
- **2026-11-19 · T-83 Phase 83b Stage 1.** Commit `c6c9f79` added change detection (origins, renames, copies, deletions, changed lines) with Git safety (hooks disabled, no lazy fetch in partial clones, a private copy of the index, Git 2.44+ for change analysis); 295 tests pass. integration-qa: no unresolved defects; details in the commit message.
- **2026-11-19 · T-83 Phase 83b Stage 2.** Commit `e80344b` added the rules engine and the informational impact report; 341 tests pass. integration-qa: no unresolved defects.
- **2026-11-19 · T-83 Phase 83b Stage 3.** Commit `0974181` added `impact check` with acknowledgements, text/JSON/Markdown reports and `--out`; 373 tests pass. integration-qa: no unresolved defects.
- **2026-11-20 · T-83 Phase 83b Stage 4.** Commit `f3ba3f9` added `impact plan --paths` (predicted impact of proposed changes); 398 tests pass. integration-qa: no unresolved defects; details in the commit message.
- **2026-11-20 · T-83 Phase 83b Stage 5.** Commit `9af86a3` (final acceptance): `config-changed` now also covers the tool's own top-level modules, found from the package location; user guide `tools/impact/README.md`; `conventions.md` section 5 (technical-lead). 409 tests pass; `impact validate` 0 ERROR, 0 WARNING; `check` against the merged T-59 change (PR #4, `565706f`) gave the expected findings; integration-qa final acceptance review: accepted, no blockers. Remaining limitations are listed under "Known limitations" in `tools/impact/README.md`.
- **2026-11-20 · T-83 Phase 83b checks on every stage.** The commit messages of `c6c9f79`, `e80344b`, `0974181`, `f3ba3f9` and `9af86a3` each record: migration check unchanged (0 relationships lost, 4 approved additions), frozen fixtures unchanged, and `impact validate` 0 ERROR, 0 WARNING.
- **2026-11-20 · PR #5 (T-83).** Merged to main as merge commit `7f0cbc8` (parents `565706f` and `dd9c3c7`). technical-lead confirmed with `git log` and `git merge-base --is-ancestor` that all T-83 stage commits (`17022c1`, `2d7f572`, `ebbf84a`, `5fc4230`, `c6c9f79`, `e80344b`, `0974181`, `f3ba3f9`, `9af86a3`) and the evidence commit `dd9c3c7` are reachable from main. The T-83 Project card was set to Done (reported by the main conversation).
- **2026-11-21 · T-94 Phase 2 M1.** The M1 commit on branch `feat/t-94-phase-2` (branched from `c5afacd`) adds the architecture index and diagram catalog as one generated file, `designs/index/architecture-index.md` (from `python -m tools.design index`; new `tools/design/markdown.py` and `tools/design/architecture.py`). It covers `docs/architecture/` only: 6 documents, 67 headings, 14 Mermaid diagrams (4 architecture, 6 process, 2 er, 1 sequence, 1 example), matching the inventory in `conventions.md` section 7. Diagram IDs are derived (`<document>/<heading anchor>`) and the tool changes nothing in `docs/architecture/`; `tools.design check` and `index --check` require a fresh index. Also in the commit: `conventions.md` section 5 step 1 bullet on regenerating the index (technical-lead), `source_diagram` in `designs/templates/diagram.md`, and updates to `designs/README.md` and `designs/DECISIONS.md`. Verification: 61 design tests and 409 T-83 tests pass; `tools.design check` and `index --check` exit 0; `tools.impact validate` and `check --base main` 0 ERROR, 0 WARNING; frozen fixtures, the brief and the T-83 engine unchanged; tests confirm all 23 existing heading links in the repository's Markdown resolve (no GitHub rendering API used). integration-qa: PASS, no defects; its one fixable risk (unpaired underscores in headings) was fixed before commit. Deferred: headings in lists, block quotes or HTML and images in headings are not indexed; fences indented 4+ spaces are counted; diagram IDs change on heading renames (stale citations to be reported by M3); an orphaned index is reported, not deleted; `tools.impact check` does not enforce index freshness (CI enforcement is a separate task, e.g. T-85); VS Code anchor compatibility reasoned, not previewed. Details in `designs/README.md` and the module docstrings.
- **2026-11-21 · T-94 Phase 2 M2.** The M2 commit on `feat/t-94-phase-2` (after M1 `f075c2d`) adds feature dependency indexing (new `tools/design/dependencies.py`): it reads each `depends_on` (Phase 1 format, optional entries and conditions kept), derives "Used by", and generates Related features rows between the `related-features` markers (ID, title, relative link, direction, all PROPOSED) plus "Depends on"/"Used by" columns in `designs/index/feature-index.md`. Only lines between markers are rewritten; relationships follow the feature ID, so `index` fixes links after a move or rename and `--convert-parent` refreshes only rows naming the moved feature. No dependency-index file, Mermaid graph or evidence field. `check` reports stale rows, unknown IDs, self-dependencies, IDs listed twice and cycles (once per group, naming every member, with an example path; never auto-resolved); `index` warns once per feature file it leaves alone (invalid metadata; missing, repeated or unclosed markers) and never repairs it. Also: template wording, `designs/README.md`, `designs/DECISIONS.md` (M2 choices), two Phase 1 test assertions updated for the new columns. Verification: 84 design and 409 T-83 tests pass; `tools.design check` and `index --check` exit 0; `tools.impact validate` and `check --base main` 0 ERROR, 0 WARNING; `docs/architecture/`, T-83, the brief and frozen fixtures unchanged. integration-qa: PASS, no defects (byte-for-byte preservation outside markers incl. CRLF/BOM, idempotent rerun, cycles cross-checked on 400 random graphs, 200 features in 0.06 s); its one risk (cycle reports naming one loop only) fixed before commit. Deferred: index cells show "(optional)" without the condition (kept in the feature's rows); link and reference checks are M3; a block takes its start-marker line ending (no false staleness); duplicate-ID files still get rows refreshed while `check` reports them.

The work done before this board existed (the ETL loaders, the three API
routes, and the map and dashboard) is described in `docs/architecture/` but has
not been formally verified here. See F-02 and F-07.

### Verification details

Verification evidence from the former task detail blocks, kept word for word.

#### T-50: `test_connection.py` read-only session (P0)
- Scope: `database/test_connection.py`.
- Acceptance: `conn.read_only = True` is set before any query; `.env` is loaded from the project root; the URL is never printed.
- Verification: code review and `py_compile` with no Neon access; one read-only Neon run only with user approval.
- Change: the main conversation applied the change with user approval, including the optional `transaction_read_only` output line.
- Verification results (integration-qa, 2026-11-16, no Neon access):
  - `read_only` is set before the first `execute`: PASS.
  - `.env` is loaded from the project root: PASS.
  - No credential printed: PASS.
  - `py_compile`: PASS.
  - Run with a dummy URL timed out and never reached Neon: PASS.
  - **Not yet verified:** one live read-only run against Neon (expect "Read-only session: on"). It needs user approval.
- Merged to main via PR #1 (merge commit 5b6aa5e, 2026-11-17); code commit 714106b.

#### T-51: Wastewater loader writes nothing by default (P0)
- Scope: `extractors/load_orlando_wastewater.py`.
- Acceptance: the default run, including `--full` without `--write`, opens no database connection and runs no DDL or upsert; writing needs an explicit `--write`; DDL handling follows D-4 once it is decided.
- Verification: code review, `py_compile`, `--help`. **No Neon run.**
- Change: the main conversation applied the base `--write` diff with user approval. The log wording also changed from "loading N" to "selected N".
- Verification results (integration-qa, 2026-11-16):
  - `py_compile` and `--help`: PASS.
  - `--write` is the only path to `psycopg.connect` (line 195), the DDL and the upserts: PASS.
  - `--write` behaviour unchanged apart from the log wording: PASS.
  - Dry run, default and `--full`, with `psycopg.connect` blocked: PASS. It reported 23,464 IDs and made no connection. One public ArcGIS GET, approved by the user.
  - D-4 DDL handling: not applicable until D-4 is decided. With `--write`, the `IF NOT EXISTS` DDL still runs; this moves to T-55.
- Merged to main via PR #1 (merge commit 5b6aa5e, 2026-11-17); code commit 3cb2440.
- Note for T-52: the source reported 23,464 IDs, while `data-contracts.md` records 23,463 `utility_lines` rows. That suggests one new source record since the last load, and it has not been checked.
