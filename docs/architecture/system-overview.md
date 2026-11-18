# System Overview

Status as of 2026-11-16. Everything below was checked against the repository and
the live Neon database with read-only queries. Where something is unbuilt or
unverified, it says so.

## Components

Diagrams of the components, the read and write paths, the credential boundary,
one map pan step by step, and the target product vision are in
[system-architecture.md](system-architecture.md).
Diagram legend, authority map and documentation rules: [conventions.md](conventions.md).

Versions at the 2026-11-16 baseline: Neon PostgreSQL 18.7 + PostGIS 3.6.4,
Next.js 16.4.6, MapLibre 6.17.

## 1. ETL (`extractors/`)

Python 3 with `requests`, `psycopg` 3 and `python-dotenv`, installed in `.venv`.
There is no `requirements.txt`.

The loader table (sources, targets, default behaviour, `.env` loading), the
per-loader flowcharts, the safety gates and the known inconsistencies are in
[etl-workflow.md](etl-workflow.md). In short:

- The wastewater loader is now a **dry run by default**: no database connection
  unless `--write` is given (T-51).
- The streets loader's `load_dotenv()` finds the root `.env` by searching upward
  from the script's own folder. It is **not** dependent on the current directory
  (corrected F-10).
- The streets and manholes loaders still **write on every run** (fix planned: T-61). Every write run
  overwrites existing rows with source data (`ON CONFLICT … DO UPDATE`) and needs
  user approval; see `CLAUDE.md`.

## 2. Database (Neon)

- Single database. All application tables are in the `public` schema. No other
  schemas exist yet.
- The app and the ETL both connect as `neondb_owner`. That role is not a
  superuser, but it owns the tables and can change or drop them. There is no
  read-only role for the API yet.
- `DATABASE_URL` is stored in two files: the root `.env`, used by the ETL, and
  `web/.env.local`, used by Next.js. Both are git-ignored.

Table details, constraints and coded-value domains are in
[data-contracts.md](data-contracts.md).

## 3. API (`web/src/app/api/infrastructure/`)

- Uses the shared `pg` pool in `web/src/lib/db.ts` (max 5 connections, 10 s
  connect timeout). The pool is reused across hot reloads in development.
- With `cacheComponents: true`, `GET` handlers that query the database run at
  request time. Nothing is cached.
- All routes are read-only. Contracts are in [data-contracts.md](data-contracts.md).

## 4. Frontend (`web/src/`)

| File | Role |
|---|---|
| `app/operations/map/page.tsx` | Page shell (header) that renders `OperationsView` |
| `components/OperationsView.tsx` | Client component. Holds the current-view counts and arranges the map card above the dashboard. |
| `components/InfrastructureMap.tsx` | MapLibre map with an OpenFreeMap "liberty" basemap. Loads features for the visible area on `moveend`, cancelling older requests. Has layer toggles and reports per-layer counts to its parent. |
| `components/InfrastructureDashboard.tsx` | Fetches `/stats`. Shows total tiles, current-view counts and breakdown bar charts. |
| `app/page.tsx` | **Still the default Next.js starter page.** The Explorer is only at `/operations/map`. |

The MapLibre worker is served from `web/public/maplibre-gl-worker.mjs`.

## 5. Not built yet

- Asset inspector. The `features` API returns no asset IDs or attributes; see the
  task board.
- Schema manager interface.
- IoT schemas and data.
- `demo` schema for synthetic data.
- Automated tests of any kind.
- Deployment configuration.

## Real vs synthetic data

All current data is real City of Orlando municipal data. Synthetic demonstration
data, when it is added, goes in a separate `demo` schema and is labelled as such
in the API and UI. The rules are in `CLAUDE.md` § Data provenance and the
proposed layout is in [data-contracts.md](data-contracts.md#synthetic-demonstration-data-demo-schema).
