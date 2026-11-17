# Task Board

The main Claude Code conversation keeps this board up to date. Every task needs
an owner, scope, acceptance criteria, dependencies and verification results.

**Statuses:** `Finding` (observed, not yet planned) · `Proposed` · `Approved` ·
`In progress` · `In review` · `Done` (verified, with evidence recorded) · `Blocked`

Do not mark anything `Done` without recorded verification results.

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
| F-10 | **`DATABASE_URL` is stored in two places**: the root `.env` and `web/.env.local`. They could drift apart. The streets loader reads `.env` from the current directory, while the other loaders use the project root. | File inspection | data-gis / backend (propose) | Env change |
| F-11 | **Manholes come from an ArcGIS `Test` service folder**, and the wastewater loader notes that data-use permission must be checked. Provenance and terms of use are not documented. | `extractors/load_orlando_manholes.py:25-29`, `load_orlando_wastewater.py` docstring | data-gis / user | No |
| F-12 | **The home page `/` is still the Next.js starter template.** The Explorer is only reachable at `/operations/map`. | `web/src/app/page.tsx` | frontend | No |
| F-13 | **The project has no README.** `web/README.md` is the create-next-app default. | Repository root | technical-lead | No |
| F-14 | **Data quality: the manhole and pipe extents are identical.** The bounding boxes match to every decimal place. This is plausible if the outermost manholes sit at pipe ends, but it has not been checked. | `ST_Extent` on both tables | data-gis | No |

## Tasks

_No tasks yet. Ask technical-lead for a plan, then add tasks here using the template below._

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

_None._ The work done before this board existed (the ETL loaders, the three API
routes, and the map and dashboard) is described in `docs/architecture/` but has
not been formally verified here. See F-02 and F-07.
