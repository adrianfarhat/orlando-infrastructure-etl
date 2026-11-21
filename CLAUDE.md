# Orlando Infrastructure Explorer

Python ETL pipelines load City of Orlando roadway and wastewater GIS data into a
Neon PostgreSQL/PostGIS database. A Next.js app (`web/`) serves that data through
API routes and shows it on a MapLibre map with an operations dashboard.

- Architecture: [docs/architecture/system-overview.md](docs/architecture/system-overview.md)
- Data and API contracts: [docs/architecture/data-contracts.md](docs/architecture/data-contracts.md)
- Tasks (status, scope, priority, dependencies, acceptance criteria): [GitHub Project #1](https://github.com/users/adrianfarhat/projects/1) (private)
- Findings, decision outcomes and verification evidence: [docs/agents/task-board.md](docs/agents/task-board.md)
- Next.js version notes: [web/AGENTS.md](web/AGENTS.md). This Next.js version differs
  from older releases; read `web/node_modules/next/dist/docs/` before writing Next.js code.

## Repository layout

| Path | Contents |
|---|---|
| `extractors/` | Python ETL loaders (ArcGIS REST → Neon/PostGIS) |
| `database/` | Connection test script |
| `data/raw/` | Downloaded source files (git-ignored) |
| `web/src/app/api/infrastructure/` | Next.js API routes (`summary`, `features`, `stats`) |
| `web/src/lib/db.ts` | Shared `pg` connection pool |
| `web/src/components/` | React components (map, dashboard, page wiring) |
| `web/src/app/operations/map/` | Operations map page and its styles |
| `docs/` | Architecture, contracts, task board |
| `.claude/agents/` | Project subagent definitions |
| `designs/` | Feature Design Workspace (T-94): proposed feature specifications, templates, generated index |
| `tools/design/` | New Feature, index and check commands for `designs/` |

## How work is coordinated

The **main Claude Code conversation is the coordinator.** It reads task status,
scope and dependencies from GitHub Project #1, assigns each task to one agent,
passes outputs between agents and updates the task's Project card. Subagents do
not delegate to each other.

1. **technical-lead** writes the plan: tasks with owner, scope, acceptance
   criteria and dependencies. It also reviews integration once work is done.
2. The main conversation records the tasks as cards in GitHub Project #1 (with
   user approval) and dispatches each one to its owner.
3. The owner does the work within its file ownership and reports what changed
   and how it was verified.
4. **integration-qa** verifies the result. The main conversation records the
   verification evidence in the Evidence log of `docs/agents/task-board.md` and
   updates the card's status.

## Agents and file ownership

Only the owner of a file edits it. If a task needs changes in files owned by
several agents, split it into one task per owner and run them one after another,
never at the same time.

| Agent | Responsibilities | Owns (may edit) | Edits? |
|---|---|---|---|
| **technical-lead** | Architecture, task breakdown, integration planning, architecture reviews | `docs/architecture/**`, `docs/agents/**` | Docs only. Never edits application code. |
| **data-gis** | Python ETL, PostgreSQL/PostGIS, GIS data modelling, roadway and wastewater data, source mappings, spatial queries, data quality, future IoT schemas | None for now. It proposes changes to `extractors/`, `database/` and SQL. | No. Read-only, with read-only database queries through Bash. |
| **backend** | Next.js API routes, database access, server-side logic, validation, API contracts | `web/src/app/api/**`, `web/src/lib/**` | Yes, with approval |
| **frontend** | React components, MapLibre, layer controls, asset inspector, schema manager UI, responsive design, client state | `web/src/components/**`, `web/src/app/**` except `web/src/app/api/**`, `web/public/**` | Yes, with approval |
| **integration-qa** | Type checks, builds, lint, API tests, data validation, integration and regression tests, security review | None | No. Read-only, may run non-destructive checks. |

Files with no agent owner, which only the main conversation may change and only
with the user's approval: `CLAUDE.md`, `.claude/**`, `.gitignore`,
`web/package.json`, `web/package-lock.json`, `web/next.config.ts`,
`web/tsconfig.json`, `web/eslint.config.mjs`, `.vscode/tasks.json`, all `.env*` files, and
`extractors/`/`database/` until data-gis is given edit rights.

The Feature Design Workspace (T-94) is also maintained by the main conversation with
the user's approval: `designs/**` (proposed designs; never the current-state docs in
`docs/architecture/`) and `tools/design/**` (its commands). `designs/IMPLEMENTATION_BRIEF.md`
is kept exactly as written; later decisions go in `designs/DECISIONS.md`.

## Shared rules (all agents)

1. **Never delete or overwrite infrastructure source records.** The three tables
   hold real City of Orlando data.
2. **Get explicit user approval before:**
   - running any ETL script that writes to Neon (the loaders upsert and overwrite rows);
   - running any SQL that changes data or schema (`INSERT`, `UPDATE`, `DELETE`,
     `TRUNCATE`, `DROP`, `ALTER`, `CREATE`, `GRANT`, `REVOKE`);
   - schema migrations, production deployments and major architecture changes;
   - installing or upgrading dependencies, changing settings or environment
     files, and anything that leaves this machine (git push, deploys, posting to
     external services).
3. **Never expose `DATABASE_URL` or any credential.** Do not print, log, echo,
   commit or paste it. When a script needs it, load it from the env file inside
   the script. Never pass it on the command line or include it in any output.
4. **Keep real and synthetic data apart.** See [Data provenance](#data-provenance).
5. **Communicate through the documented contracts.** Frontend ↔ backend ↔ database
   go through the API contracts in `docs/architecture/data-contracts.md`. A
   contract change is its own task: update the contract document first, then
   the backend, then the frontend.
6. **Avoid unnecessary refactoring.** Change only what the task needs.
7. **One editor per file at a time.** No concurrent edits to the same file.
8. **Every task has** an owner, scope, acceptance criteria, dependencies and
   verification results. Keep the task fields (status, scope, priority,
   dependencies, acceptance criteria) on the task's card in GitHub Project #1
   and do not copy them into Markdown. Record architectural findings, decision
   outcomes and verification evidence in `docs/agents/task-board.md`.
9. **Preserve the working application.** The operations map page
   (`/operations/map`) and the three API routes must keep working after every task.
10. **Do not claim work is complete because code exists.** Something is done only
    when it has been verified, and the verification is recorded.

### Read-only database access

Inspection queries must run in a read-only session so they cannot change data:

```python
with psycopg.connect(database_url) as conn:
    conn.read_only = True
    ...
```

The app currently connects as the database owner role (`neondb_owner`), so the
database itself will not block writes. The read-only session is the safeguard.

## Data provenance

| Kind | Where it lives | `source_system` |
|---|---|---|
| **Real municipal data** | `public` schema: `road_segments`, `utility_lines`, `manholes` | `orlando_street_centerline`, `orlando_wastewater_gravity_lines`, `orlando_wastewater_manholes` |
| **Synthetic demonstration data** | A separate `demo` schema (not yet created; creating it needs approval) | Must start with `synthetic_` |

- Never write simulated, generated or test records into the `public` infrastructure tables.
- Any API response or UI element that shows synthetic data must label it as synthetic.
- Do not mix real and synthetic rows in one result without a field that tells them apart.

## Commands

Run these from the repository root unless noted. Node/npm is not on the PATH of
Claude Code's shell on this machine yet (see the task board). Until that is
fixed, Node commands may have to be run by the user.

| Purpose | Command |
|---|---|
| Web dev server | `cd web && npm run dev` → http://localhost:3000/operations/map |
| Type check | `cd web && npx tsc --noEmit` |
| Lint | `cd web && npm run lint` |
| Production build | `cd web && npm run build` |
| Database connection test (read-only) | `.venv\Scripts\python database\test_connection.py` |
| ETL loaders (**write to Neon; need approval**) | `.venv\Scripts\python extractors\load_orlando_*.py` |
| New feature design (creates uncommitted files only) | `.venv\Scripts\python -m tools.design new feature`, or the VS Code task "New Feature" |
| Design workspace check | `.venv\Scripts\python -m tools.design check` |
