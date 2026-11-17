# Task Board

The main Claude Code conversation keeps this board up to date. Every task needs
an owner, scope, acceptance criteria, dependencies and verification results.

**Statuses:** `Finding` (observed, not yet planned) · `Proposed` · `Approved` ·
`In progress` · `In review` · `Done` (verified, with evidence recorded) · `Blocked`

Do not mark anything `Done` without recorded verification results.

Dashboard view (status counts, wave diagrams, blockers):
[development-status.md](development-status.md). This board is the source of truth.

## Findings (from the 2026-11-16 repository inspection)

These are open issues, **not completed work**.

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
| F-15 | **There is no navigation index for the docs.** No diagrams of the system, ETL, schema or work status. **Done on 2026-11-17:** added `docs/architecture/system-architecture.md`, `etl-workflow.md`, `database-schema.md` and `docs/agents/development-status.md` (technical-lead, user-approved docs workspace). The Mermaid diagrams have not been checked for rendering. | `docs/` listing | technical-lead | No |

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
| F-15 | Done (docs workspace, 2026-11-17) |

## Tasks

The technical-lead proposed this board on 2026-11-16 from the read-only team
inspection (integration-qa checks plus backend, frontend and data-gis code
reviews). It was saved with user approval. Every finding behind it comes from
code reading unless it was run, and **none has been verified live**. All tasks
are `Not started` (saved to the board but not yet dispatched). Approval to save
the board does **not** approve any task's own approvals listed below.

Approved by user 2026-11-17: T-61 added as P0. Task status is moving to GitHub
Project 1 (private draft items); the restructure of this board is pending.

**Priorities:** P0 safety or rule violation · P1 correctness or reliability ·
P2 quality · P3 later or optional.

### Summary

| ID | Title | Pri | Owner | Depends on | Approval needed | Status |
|---|---|---|---|---|---|---|
| T-01 | Baseline verification (build, live API, browser) | P1 | integration-qa | none | User starts dev server if needed | Not started |
| T-02 | Confirm whether F-01 and F-08 are stale | P3 | integration-qa | none | none | Not started |
| T-03 | Find the source of the 1,103 lint warnings | P2 | integration-qa | none | none | Not started |
| T-04 | Update CLAUDE.md (Node through fnm) and the lint config if needed | P3 | main conversation (user approval) | T-02, T-03 | Config / CLAUDE.md | Not started |
| T-10 | Features route: own-key layer allowlist, strict bbox parsing | P1 | backend | T-01 | none (brings code in line with the current contract) | Not started |
| T-11 | `db.ts` hardening: lazy env check, pool error handler, timeouts | P1 | backend | T-01 | none | Not started |
| T-12 | Safer server-side error logging in all three routes | P2 | backend | T-10 | none | Not started |
| T-20 | `/features` contract v2 and contract nits | P1 | technical-lead | D-2, D-3 | **Contract change** | Not started |
| T-21 | Backend: implement features contract v2 | P1 | backend | T-20, T-10, T-12 | Covered by T-20 | Not started |
| T-22 | Frontend: handle the new 400 and truncation meaning | P1 | frontend | T-21, T-40 | none | Not started |
| T-23 | Asset inspector UI | P2 | frontend | T-21, T-22, D-3 | User decision D-3 | Not started |
| T-24 | `/stats` caching | P3 | backend | T-21 | none (check against the Next 16 docs) | Not started |
| T-40 | Map resilience: layer failures, errors, reload guard, debounce | P1 | frontend | T-01 | none | Not started |
| T-41 | Dashboard: truncation notice, accessible status, provenance label | P2 | frontend | T-01 | none | Not started |
| T-42 | Map accessibility, dark mode and responsive fixes | P2 | frontend | T-40, T-41 | none | Not started |
| T-43 | Metadata, home page and unused-asset clean-up | P3 | frontend | D-5 | User decision D-5 | Not started |
| T-50 | `test_connection.py`: read-only session | **P0** | main conversation (user approval); data-gis proposes | D-1 | Code change to an unowned file | In progress |
| T-51 | Wastewater loader: no writes or DDL by default | **P0** | main conversation (user approval); data-gis proposes | D-1 | Code change to an unowned file | Done |
| T-52 | Read-only database audit | P1 | data-gis | none | Read-only DB session (confirm) | Not started |
| T-53 | Commit the `road_segments` DDL as a reference file | P2 | main conversation (user approval) | T-52, D-8 | File add only, no DB change | Not started |
| T-54 | Manholes source provenance check | P2 | data-gis, then technical-lead (docs) | D-6 | External read-only GET | Not started |
| T-55 | Make the three loaders consistent | P2 | main conversation (user approval); data-gis proposes | T-51, T-52, T-61, D-4 | Code change; **no ETL run** | Not started |
| T-56 | Schema migrations (`road_segments` key, `last_seen_at`, `diameter_raw`) | P3 | data-gis proposes; user applies | T-52, D-9 | **Migration** | Not started |
| T-57 | Read-only database role for `web/` | P1 | data-gis proposes SQL; user applies; main conversation updates env | T-52 | **GRANT/CREATE ROLE + env change** | Not started |
| T-58 | One place for `DATABASE_URL` | P3 | main conversation (user approval) | T-57, D-7 | Env change | Not started |
| T-59 | Declare Python dependencies (`requirements.txt`) | P2 | main conversation (user approval); data-gis proposes | none | Dependency file | Not started |
| T-60 | Design the `demo` schema and IoT tables (design doc only) | P3 | technical-lead | T-52 | **Architecture**; any build later is a migration | Not started |
| T-61 | Streets and manholes loaders: dry run by default, writes only with `--write` | **P0** | main conversation (user approval); data-gis proposes | D-1 | Code change to unowned files | Not started |
| T-70 | Automated test harness plan | P2 | integration-qa (plan); backend/frontend implement later | T-01, D-10 | Dependency, if a runner is added | Not started |
| T-90 | Integration verification at the end of each wave | P0 | integration-qa | All tasks in the wave | none | Not started |

### Task details

Every task: **Status:** Not started · **Verification results:** pending.

#### T-01: Baseline verification
- Scope: read-only checks: `npm run build`, dev server, curl of the 3 routes, browser check of `/operations/map`.
- Acceptance: build result recorded; response shapes of all 3 routes compared with `data-contracts.md`; current behaviour recorded for a set of invalid `layer` and `bbox` inputs; map loads and layer toggles work.
- Verification: results recorded here as the regression baseline; closes F-07 if they pass.

#### T-02: Confirm F-01 and F-08
- Scope: `git ls-files web`, `node --version` through fnm.
- Acceptance: F-01 and F-08 marked stale or confirmed, with evidence.
- Verification: command output recorded.

#### T-03: Lint warning source
- Scope: `npx eslint --format json`, grouped by path. No config edits.
- Acceptance: the paths behind the 1,103 warnings are named. `.next/**` is already ignored (`web/eslint.config.mjs:11`), so `.next` is not the cause.
- Verification: report recorded.

#### T-04: CLAUDE.md and lint config
- Scope: `CLAUDE.md` (Commands note), `web/eslint.config.mjs`.
- Acceptance: the Node note matches T-02; ignore entries added only for the paths T-03 names.
- Verification: integration-qa re-runs lint.

#### T-10: Features route input validation
- Scope: `web/src/app/api/infrastructure/features/route.ts` (lines 20 and 34).
- Acceptance: only the documented layer names are accepted, and any malformed `layer` or `bbox` value returns a 400 JSON error; valid calls behave as in T-01.
- Verification: curl test matrix, `tsc`, lint.

#### T-11: `db.ts` hardening
- Scope: `web/src/lib/db.ts`.
- Acceptance: a missing `DATABASE_URL` returns a JSON 500 at request time instead of failing at import; `pool.on('error')` logs only the message and code; `idleTimeoutMillis` and `statement_timeout` are set.
- Verification: `tsc`, build, all 3 routes return 200; the missing-env case is checked by code review only (no env edits).

#### T-12: Error logging
- Scope: the `console.error` calls in the 3 `route.ts` files.
- Acceptance: logs contain only the error message and `code`; response bodies are unchanged.
- Verification: code review and regression curl.

#### T-20: Contract v2 (features) and nits
- Scope: `docs/architecture/data-contracts.md`.
- Acceptance: the contract defines `truncated` as "more rows exist" (fetch 2001 rows, return 2000); a stable sort order; the bbox cap and its new 400 case (D-2); `id`, `source_system`, `source_objectid` and the attribute shape (D-3); stats rounding; labels copied exactly from `MATERIAL_LABELS`.
- Verification: backend and frontend confirm the contract is enough to build on.

#### T-21: Backend features v2
- Scope: `features/route.ts`; `stats/route.ts` only if D-2 changes rounding.
- Acceptance: exactly 2,000 matches give `truncated: false` and 2,001 or more give `true`; an oversized bbox returns 400; the order is the same on every call; the response matches T-20.
- Verification: contract test matrix against the dev server.

#### T-22: Frontend contract adaptation
- Scope: `InfrastructureMap.tsx`, `InfrastructureDashboard.tsx`.
- Acceptance: a 400 shows a "zoom in" message, never endless loading; the truncation notice uses the v2 meaning.
- Verification: browser check zoomed fully out and zoomed in.

#### T-23: Asset inspector
- Scope: a new component under `web/src/components/` and its wiring.
- Acceptance: clicking a feature shows its `id`, source ID and the D-3 attributes, labelled as real City of Orlando GIS data; the panel can be dismissed with the keyboard.
- Verification: browser check on all 3 layers.

#### T-24: `/stats` caching
- Scope: `stats/route.ts`.
- Acceptance: caching follows the Next 16 docs (cite them); the staleness limit is agreed with the user; the cached body is identical to the uncached one.
- Verification: compare responses and timings.

#### T-40: Map resilience
- Scope: `InfrastructureMap.tsx`.
- Acceptance: a failed layer still calls `onViewportChange` and its error shows in the UI; `map.on('error')` is handled and a style failure is visible; the `isStyleLoaded` guard (line 69) defers the reload instead of dropping it; `moveend` is debounced and the bbox rounded.
- Verification: browser check with one layer's request blocked in devtools, plus a rapid-pan test.

#### T-41: Dashboard UX
- Scope: `InfrastructureDashboard.tsx`, `operations.module.css`.
- Acceptance: an explicit "first 2,000 shown, zoom in" notice; `aria-live` on counts; `role=status` and `role=alert`; bar values visible without hovering; a real-data provenance label.
- Verification: browser check plus an axe spot check.

#### T-42: Map accessibility, dark mode, responsive
- Scope: `InfrastructureMap.tsx` (lines 240–254), `operations.module.css` (lines 147, 208).
- Acceptance: the map has an `aria-label`; layer control styles moved to a CSS module with dark-mode support; `.error` meets AA contrast; no overflow at 320 px; the control does not cover the map at 360 px.
- Verification: check at 320, 360, 768 and 1280 px in light and dark mode.

#### T-43: Clean-up
- Scope: `web/src/app/layout.tsx`, `web/src/app/page.tsx`, `web/public/*.svg`.
- Acceptance: real page metadata; `/` behaves as D-5 decides; starter SVGs removed only after a grep shows they are unused.
- Verification: build and a browser check of `/` and `/operations/map`.

#### T-50: `test_connection.py` read-only session (P0)
- Scope: `database/test_connection.py`.
- Acceptance: `conn.read_only = True` is set before any query; `.env` is loaded from the project root; the URL is never printed.
- Verification: code review and `py_compile` with no Neon access; one read-only Neon run only with user approval.
- **Status: In progress.** The main conversation applied the change with user approval, including the optional `transaction_read_only` output line.
- Verification results (integration-qa, 2026-11-16, no Neon access):
  - `read_only` is set before the first `execute`: PASS.
  - `.env` is loaded from the project root: PASS.
  - No credential printed: PASS.
  - `py_compile`: PASS.
  - Run with a dummy URL timed out and never reached Neon: PASS.
  - **Remaining:** one live read-only run against Neon (expect "Read-only session: on"). Awaiting user approval.

#### T-51: Wastewater loader writes nothing by default (P0)
- Scope: `extractors/load_orlando_wastewater.py`.
- Acceptance: the default run, including `--full` without `--write`, opens no database connection and runs no DDL or upsert; writing needs an explicit `--write`; DDL handling follows D-4 once it is decided.
- Verification: code review, `py_compile`, `--help`. **No Neon run.**
- **Status: Done.** The main conversation applied the base `--write` diff with user approval. The log wording also changed from "loading N" to "selected N".
- Verification results (integration-qa, 2026-11-16):
  - `py_compile` and `--help`: PASS.
  - `--write` is the only path to `psycopg.connect` (line 195), the DDL and the upserts: PASS.
  - `--write` behaviour unchanged apart from the log wording: PASS.
  - Dry run, default and `--full`, with `psycopg.connect` blocked: PASS. It reported 23,464 IDs and made no connection. One public ArcGIS GET, approved by the user.
  - D-4 DDL handling: not applicable while D-4 is pending. With `--write`, the `IF NOT EXISTS` DDL still runs; this moves to T-55.
- Note for T-52: the source reported 23,464 IDs, while `data-contracts.md` records 23,463 `utility_lines` rows. That suggests one new source record since the last load, and it has not been checked.

#### T-52: Read-only database audit
- Scope: read-only psycopg session (`conn.read_only = True`).
- Acceptance: report covering DDL, constraints and indexes for all 3 tables; `ST_IsValid`, Z and SRID checks; distinct `diameter_raw` values; code column types; manhole count per `source_system` against the source (stale rows); the F-14 extents check.
- Verification: technical-lead reviews against `data-contracts.md`.

#### T-53: `road_segments` DDL file
- Scope: a new file under `database/` (path set by D-8).
- Acceptance: exactly matches the DDL captured in T-52; header says "reference only, not run automatically".
- Verification: diff against the T-52 output.

#### T-54: Manholes source provenance
- Scope: read-only ArcGIS `?f=json` GET; technical-lead updates the docs.
- Acceptance: service owner, folder, domains, any production equivalent and terms-of-use status recorded.
- Verification: technical-lead reviews; closes or escalates F-11.

#### T-55: Loader consistency
- Scope: the 3 loaders, edited one after another.
- Acceptance: `.env` loaded from the project root; one shared User-Agent and retry policy; null-geometry handling per D-4; the manholes count check covers only the rows from this run (lines 248–260); `ST_Force2D` and an `ST_IsValid` gate.
- Non-blocking follow-ups from T-51:
  - The wastewater loader still requires `DATABASE_URL` for a dry run, although it never uses it (check at lines 164–169). Consider requiring it only with `--write`.
  - The docstring says "`--write` (writes 5 records)", which is true only without `--full`. Consider clearer wording.
  - The wastewater DDL handling, which waits on D-4: option (a) existence check, or option (b) `--init`.
- Verification: code review and dry runs only. **No ETL write run.**

#### T-56: Schema migrations
- Scope: migration SQL proposals; the user applies them.
- Acceptance: each migration has forward and rollback SQL, an impact check based on T-52 data, and a Neon-branch rehearsal; no source records are deleted or overwritten.
- Verification: re-run the T-52 queries and the API regression after the user applies them.

#### T-57: Read-only role for `web/`
- Scope: role and grant SQL (user applies it); then `web/.env.local` (main conversation, with approval).
- Acceptance: the app's `current_user` is the new role; an `INSERT` fails with a permission error; all routes return 200.
- Verification: privilege check and API regression; closes F-03.

#### T-58: One place for `DATABASE_URL`
- Scope: env files, per D-7.
- Acceptance: the layout matches D-7, with no unintended duplicate.
- Verification: integration-qa checks without printing any value.

#### T-59: `requirements.txt`
- Scope: new `requirements.txt` at the repository root.
- Acceptance: versions pinned from the imports actually used; a fresh venv runs `test_connection.py`.
- Verification: integration-qa does a clean install.

#### T-60: `demo` schema and IoT design
- Scope: a design doc under `docs/architecture/`.
- Acceptance: covers schema isolation, the `synthetic_` prefix and synthetic labelling in the API and UI; every build step is marked as needing approval.
- Verification: user review.

#### T-61: Streets and manholes loaders write nothing by default (P0)
- Scope: `extractors/load_orlando_streets.py`, then `extractors/load_orlando_manholes.py`, edited one after the other, never at the same time.
- Why (technical-lead read, 2026-11-17): neither loader has a `--write` gate, so every run writes to Neon.
  - Streets: no CLI flags; `psycopg.connect` at line 137; upsert with `ON CONFLICT (source_objectid)` at line 106.
  - Manholes: `psycopg.connect` at line 171; `CREATE EXTENSION`/`CREATE TABLE`/`CREATE INDEX IF NOT EXISTS` at lines 174–196; upsert with `ON CONFLICT` at line 224; the only flag is `--download` (line 271).
- Acceptance:
  - Without `--write`, neither loader opens a database connection or runs DDL or an upsert.
  - Manholes `--download` without `--write` writes only the local `data/raw/` file, nothing to the database.
  - With `--write`, behaviour is unchanged.
  - DDL handling follows D-4 once it is decided (moves to T-55, as for T-51).
- Verification: integration-qa runs `py_compile` and `--help` for both, then a dry run of each with `psycopg.connect` blocked. **No Neon run.** A streets dry run makes public ArcGIS GETs; confirm with the user first, as for T-51.
- Approval needed: code change to unowned files.

#### T-70: Test harness plan
- Scope: a plan document.
- Acceptance: names the test runner, its dependencies and the first suite (T-10/T-21 contract tests, ETL dry runs).
- Verification: user approves any dependencies.

#### T-90: Integration verification per wave
- Scope: read-only checks.
- Acceptance: `tsc`, lint and build pass; the contract test matrix passes; the `/operations/map` regression passes; no credentials appear in any output; `development-status.md` matches the summary table.
- Verification: results recorded before any task in the wave is marked `Done`.

### Execution waves

| Wave | Tasks |
|---|---|
| 0: Safety and baseline | T-50, then T-51, then T-61 (main conversation; T-61 edits the streets loader, then the manholes loader); T-01, T-02, T-03 (integration-qa) at the same time |
| 1: Fixes with no contract change | Backend T-10 then T-12, with T-11 alongside; frontend T-40, then T-41, then T-42; data-gis T-52; technical-lead T-20; then T-90 |
| 2: Contract v2 | T-21, then T-22; T-53, T-54, T-57 (user applies); then T-90 |
| 3: Features and hygiene | T-23, T-24, T-55, T-59, T-04, T-43, T-70; then T-90 |
| 4: Approval or architecture work | T-56, T-58, T-60; then T-90 |

Never run two tasks at the same time on `InfrastructureMap.tsx`,
`features/route.ts` or the same loader.

## Decisions

Status of every decision: **PENDING — user will review individually.** The
recommendations are the technical-lead's and are not decisions.

| ID | Question | Options | Recommendation | Status |
|---|---|---|---|---|
| D-1 | Who edits the P0 files in `database/` and `extractors/` | (a) main conversation with user approval; (b) give data-gis edit rights (CLAUDE.md change) | (a) now; decide (b) later | PENDING — user will review individually |
| D-2 | `/features` limits | Bbox cap: (a) maximum span in degrees (for example 0.25°), (b) minimum zoom sent by the client, (c) no cap, rely on `statement_timeout`. Order: `ORDER BY id`, yes or no. Stats miles: (a) the API rounds to 2 decimals, (b) the UI rounds | Cap (a); `ORDER BY id` yes; round in the UI (b) and fix the contract example | PENDING — user will review individually |
| D-3 | Asset inspector data | (a) attributes in every `/features` feature; (b) `/features` returns only `id` and `source_objectid`, plus a new `/features/{layer}/{id}` for details. Also: which attributes to show for each layer | (b), which keeps map payloads small | PENDING — user will review individually |
| D-4 | Loader policy | Null geometry: (a) skip and count, (b) write NULL, (c) fail the run. DDL: (a) never, (b) only behind `--init` | Skip and count; DDL behind `--init` | PENDING — user will review individually |
| D-5 | What `/` shows | (a) redirect to `/operations/map`; (b) landing page with a link; (c) leave as is | (a) | PENDING — user will review individually |
| D-6 | ArcGIS metadata GET (T-54) | (a) allow it; (b) the user fetches it | (a) public read-only GET, sends no credentials | PENDING — user will review individually |
| D-7 | Where `DATABASE_URL` lives | (a) one shared file; (b) root `.env` holds the owner credential for ETL, `web/.env.local` holds the read-only role | (b), after T-57 | PENDING — user will review individually |
| D-8 | Path of the DDL file | for example `database/schema/road_segments.sql` | That path | PENDING — user will review individually |
| D-9 | Schema migrations (T-56) | (a) now, rehearsed on a Neon branch; (b) defer | (b); rehearse the `diameter_raw` change only if T-52 finds fractional values | PENDING — user will review individually |
| D-10 | Test runner | (a) Vitest plus contract tests; (b) curl or Node script, no new dependencies | (b) now, (a) later | PENDING — user will review individually |

### Risks

- Contract v2 changes what `truncated` means, so T-22 must ship with T-21 or right after it.
- The manholes source may not be approved for use (T-54).
- T-56 and T-57 change the live database. Back up or create a Neon branch first.
- This board creates no synthetic data.

## Task template

```
### T-<number>: <title>
- Status: Proposed
- Owner: <agent>
- Scope: <files/areas>
- Depends on: <IDs or none>
- Related findings: <F-xx>
- Acceptance criteria:
  - [ ] <criterion>
- Approval needed: <none | migration | ETL write | dependency | deployment | architecture>
- Verification results: <command → result, by whom, date>
```

## Completed

- **T-51** Wastewater loader writes nothing by default. Done on 2026-11-16; the verification results are recorded under T-51 above.

The work done before this board existed (the ETL loaders, the three API
routes, and the map and dashboard) is described in `docs/architecture/` but has
not been formally verified here. See F-02 and F-07.
