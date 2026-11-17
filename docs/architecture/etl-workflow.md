# ETL Workflow

How the three Python loaders in `extractors/` copy City of Orlando GIS data into
Neon. Drawn from the code as of 2026-11-17. Table layouts are in
[data-contracts.md](data-contracts.md) and [database-schema.md](database-schema.md),
and the overall picture is in [system-architecture.md](system-architecture.md).
Diagram rules are in [conventions.md](conventions.md); the diagrams on this page
are process diagrams, so the implementation-status legend does not apply.

> **Every loader can overwrite real rows in Neon.** Running one in a way that
> writes needs explicit user approval (CLAUDE.md, shared rule 2). Reading this
> page and the code is always safe.

## Loaders at a glance

| Loader | Source layer | Target table | Default behaviour | Writes when | Loads `.env` from |
|---|---|---|---|---|---|
| [load_orlando_streets.py](../../extractors/load_orlando_streets.py) | `services5.arcgis.com/.../Street_Centerline/FeatureServer/0`, requested as GeoJSON | `road_segments` | **Writes all records.** No flags and no dry run. Does not create the table. | Every run | `load_dotenv()` with no path ([:10](../../extractors/load_orlando_streets.py#L10)). Run as a script, it searches upward from the script's own folder and finds the root `.env`. It does not depend on the current directory (see F-10). |
| [load_orlando_wastewater.py](../../extractors/load_orlando_wastewater.py) | `gis.orlando.gov/.../PRR/Wastewater_Reclaim_Utilities/MapServer/12`, requested as Esri JSON | `utility_lines` | **Dry run** (T-51): fetches the ID list and prints counts. Makes no database connection. 5 records by default, or all with `--full`. `DATABASE_URL` must still be set (see T-55 follow-up). | Only with `--write` | Project root, explicitly ([:160-162](../../extractors/load_orlando_wastewater.py#L160-L162)) |
| [load_orlando_manholes.py](../../extractors/load_orlando_manholes.py) | `gis.orlando.gov/.../Test/Wastewater_Reclaim_Utilities__Labels__Max_Scale_1_1_000_/MapServer/1`, requested as GeoJSON | `manholes` | **Writes**, importing the local file `data/raw/orlando_manholes.geojson`. `--download` refreshes that file first. | Every run | Project root, explicitly ([:113](../../extractors/load_orlando_manholes.py#L113)) |

All three use upsert (`INSERT … ON CONFLICT … DO UPDATE`), so re-running a loader
updates rows instead of duplicating them. None of them ever deletes a row.

## The common pattern

Every loader follows the same idea, but the order differs: streets and wastewater download batch by batch while connected, and only manholes downloads everything first. Streets has no DDL, safety gate or count check.

```mermaid
flowchart LR
  %% diagram-type: process
  A["1. Ask ArcGIS for<br/>all OBJECTIDs"] --> B["2. Download features<br/>(manholes: all first;<br/>streets, wastewater: per batch)"]
  B --> C["3. Validate:<br/>IDs match, geometry OK"]
  C --> D{"4. Safety gate:<br/>allowed to write?"}
  D -->|"no"| E["Dry run:<br/>print counts, stop"]
  D -->|"yes, user approved"| F["5. Connect to Neon"]
  F --> G["6. DDL<br/>CREATE ... IF NOT EXISTS"]
  G --> H["7. UPSERT rows,<br/>COMMIT"]
  H --> I["8. Count check"]
```

**Why fetch IDs first?** ArcGIS services cap how many features one request
returns. Asking for the full ID list first, then requesting exact ID batches,
means the loader can prove it got every record: the set of IDs returned must
equal the set asked for. That is safer than paging with offsets, where a record
inserted mid-download can shift pages.

## Each loader in detail

### Streets → `road_segments`

```mermaid
flowchart TD
  %% diagram-type: process
  S0(["python extractors/load_orlando_streets.py<br/>WRITES: needs approval"]) --> S1["load_dotenv() at import"]
  S1 --> S2["get_all_ids(): POST returnIdsOnly"]
  S2 --> S3["Connect to Neon immediately"]
  S3 --> S4["For each batch of 200:<br/>download GeoJSON"]
  S4 --> S5{"Returned IDs ==<br/>requested IDs?"}
  S5 -->|"no"| SX["RuntimeError<br/>(earlier batches already committed)"]
  S5 -->|"yes"| S6["UPSERT each feature<br/>skip + count null geometry"]
  S6 --> S7["COMMIT this batch"]
  S7 --> S4
  S7 --> S8{"All IDs retrieved?"}
  S8 -->|"no"| SX
  S8 -->|"yes"| S9["Print summary<br/>(no database count check)"]
```

Code: IDs [:44-52](../../extractors/load_orlando_streets.py#L44-L52) ·
batch check [:150-157](../../extractors/load_orlando_streets.py#L150-L157) ·
upsert with `ST_Multi` [:87-120](../../extractors/load_orlando_streets.py#L87-L120) ·
null geometry skipped [:83-85](../../extractors/load_orlando_streets.py#L83-L85) ·
per-batch commit [:163](../../extractors/load_orlando_streets.py#L163).

### Wastewater → `utility_lines`

```mermaid
flowchart TD
  %% diagram-type: process
  W0(["python extractors/load_orlando_wastewater.py<br/>[--full] [--write]"]) --> W1["Load root .env,<br/>require DATABASE_URL"]
  W1 --> W2["get_ids(): GET returnIdsOnly<br/>User-Agent set, 4 attempts"]
  W2 --> W3["Select 5 IDs, or all with --full"]
  W3 --> W4{"--write?"}
  W4 -->|"no (default)"| WD["DRY RUN: print, return<br/>no database connection (T-51)"]
  W4 -->|"yes, user approved"| W5["Connect to Neon"]
  W5 --> W6["CREATE EXTENSION / TABLE / INDEX<br/>IF NOT EXISTS"]
  W6 --> W7["For each batch of 200:<br/>get_features + ID check"]
  W7 --> W8["UPSERT, null geometry<br/>written as NULL geom"]
  W8 --> W9["COMMIT this batch"]
  W9 --> W7
  W9 --> W10["COUNT(*) for source_system"]
  W10 --> W11{"--full and count<br/>differs from API?"}
  W11 -->|"yes"| WW["Print WARNING<br/>(stale or deleted source rows?)"]
  W11 -->|"no"| WF["Finished"]
```

Code: retries [:35-64](../../extractors/load_orlando_wastewater.py#L35-L64) ·
ID check [:86-122](../../extractors/load_orlando_wastewater.py#L86-L122) ·
Esri paths → MultiLineString [:125-139](../../extractors/load_orlando_wastewater.py#L125-L139) ·
dry-run gate [:188-193](../../extractors/load_orlando_wastewater.py#L188-L193) ·
connect [:195](../../extractors/load_orlando_wastewater.py#L195) ·
DDL [:197-226](../../extractors/load_orlando_wastewater.py#L197-L226) ·
commit [:295](../../extractors/load_orlando_wastewater.py#L295) ·
count and warning [:306-326](../../extractors/load_orlando_wastewater.py#L306-L326).

### Manholes → `manholes`

```mermaid
flowchart TD
  %% diagram-type: process
  M0(["python extractors/load_orlando_manholes.py<br/>[--download]  WRITES: needs approval"]) --> M1{"--download?"}
  M1 -->|"yes"| M2["Page through ArcGIS<br/>resultOffset, 1000 per page, no retries"]
  M2 --> M3["Check no missing or<br/>duplicate OBJECTIDs"]
  M3 --> M4[("Save data/raw/<br/>orlando_manholes.geojson")]
  M1 -->|"no"| M5
  M4 --> M5["Load root .env, read the local file"]
  M5 --> M6["Validate every feature:<br/>OBJECTID, Point, coordinate ranges<br/>raise on null or bad geometry"]
  M6 --> M7["Connect to Neon"]
  M7 --> M8["CREATE EXTENSION / TABLE / INDEX<br/>IF NOT EXISTS"]
  M8 --> M9["UPSERT in batches of 500<br/>(one transaction, no per-batch commit)"]
  M9 --> M10{"COUNT(*) for source_system<br/>== features in file?"}
  M10 -->|"no"| MR["RuntimeError, whole run<br/>ROLLED BACK"]
  M10 -->|"yes"| MC["COMMIT on leaving<br/>the connection block"]
```

Code: download [:39-107](../../extractors/load_orlando_manholes.py#L39-L107) ·
validation [:133-167](../../extractors/load_orlando_manholes.py#L133-L167) ·
DDL [:172-195](../../extractors/load_orlando_manholes.py#L172-L195) ·
upsert [:199-245](../../extractors/load_orlando_manholes.py#L199-L245) ·
count check [:247-260](../../extractors/load_orlando_manholes.py#L247-L260).

**A transaction lesson in this loader.** In psycopg 3,
`with psycopg.connect(...) as conn:` commits when the block ends normally and
rolls back if an exception escapes. The manholes loader never commits per batch,
so a failed count check undoes the whole import: all or nothing. The streets and
wastewater loaders commit after every batch, so a failure halfway leaves the
earlier batches written. Neither choice is wrong. All-or-nothing is safer;
per-batch commits avoid one huge transaction. A loader should pick one on
purpose.

## Safety gates

```mermaid
flowchart TD
  %% diagram-type: process
  Q(["Someone wants to run a script"]) --> K{"Which script?"}
  K -->|"database/test_connection.py"| RO["Read-only session:<br/>conn.read_only = True (T-50).<br/>Live run still awaits user approval."]
  K -->|"wastewater, no --write"| DRY["Dry run: no DB connection.<br/>One public ArcGIS GET."]
  K -->|"wastewater --write,<br/>streets, manholes"| AP{"Explicit user approval?<br/>(CLAUDE.md rule 2)"}
  AP -->|"no"| STOP["Do not run"]
  AP -->|"yes"| RUN["Run: upserts overwrite<br/>real rows in public"]
```

- Only the wastewater loader has a dry-run mode so far. **Streets and manholes
  write on every run.** Adding the same dry-run default is planned as **T-61**
  (P0); see the [task board](../agents/task-board.md).
- The database role is the owner *(2026-11-16 baseline)*, so the database will
  not refuse writes. The gates above are code and process gates only.

## Known inconsistencies

Each is tracked on the [task board](../agents/task-board.md). This table is a
map, not the source of truth.

| Topic | Streets | Wastewater | Manholes | Tracked in |
|---|---|---|---|---|
| Null or bad geometry | Skips and counts it ([:83-85](../../extractors/load_orlando_streets.py#L83-L85)) | Writes a row with `NULL` geom ([:131-132](../../extractors/load_orlando_wastewater.py#L131-L132)) | Raises and stops ([:142-145](../../extractors/load_orlando_manholes.py#L142-L145)) | T-55, decision D-4 |
| Dry run | None | Default (T-51) | None | T-61 |
| DDL | None. `road_segments` DDL is not in the repo. | With `--write` | Every run | T-52, T-53, D-4 |
| Transactions | Commit per batch | Commit per batch | One transaction | T-55 |
| Count check | None (compares ID sets only) | Warns with `--full` | Rolls back on mismatch. Stale rows from earlier runs also cause a mismatch ([:247-260](../../extractors/load_orlando_manholes.py#L247-L260)). | T-55 |
| Stale rows (deleted at source) | Never removed | Never removed; warning only | Never removed; causes rollback | T-52, T-56 (`last_seen_at`), D-9 |
| HTTP | POST, 3 attempts, no User-Agent | GET, 4 attempts, User-Agent | GET, no retries, no User-Agent | T-55 |
| Unique key | `source_objectid` alone | `(source_system, source_objectid)` | `(source_system, source_objectid)` | T-52, T-56 |
| Source provenance | Public ArcGIS Online item | `PRR` folder; data-use permission to be checked (docstring) | **`Test` service folder** on a label-scale service | F-11, T-54, D-6 |
| Geometry handling | `ST_Multi` wrap | Builds a MultiLineString from Esri paths | Point. No `ST_Force2D` or `ST_IsValid` gate in any loader. | T-55 |

Also open: the T-51 dry run on 2026-11-16 reported 23,464 source IDs against
23,463 stored rows *(baseline count)*. This is unexplained until T-52 checks it.
