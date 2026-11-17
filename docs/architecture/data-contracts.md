# Data Contracts

These are the agreed interfaces between the database, the API and the frontend.
Change a contract here first, in its own task, before changing any code (see
`CLAUDE.md`). Baseline verified on 2026-11-16 against the live Neon database
(read-only) and the current source.

Entity diagrams and a SQL learning guide are in [database-schema.md](database-schema.md).

## Database tables (`public` schema, real municipal data)

All geometry is EPSG:4326, 2D. Each `geom` column has a GiST index. The baseline
had no null, empty or invalid geometries.

### `road_segments`: 14,943 rows, `MULTILINESTRING`

| Column | Type | Notes |
|---|---|---|
| `id` | bigint, primary key | Serial |
| `source_objectid` | integer, not null, **unique** | ArcGIS `OBJECTID` |
| `source_system` | text, not null | Default is `'orlando_street_centerline'` |
| `street_name` | text | From `FullStreetName` |
| `geom` | geometry(MultiLineString, 4326) | |
| `source_properties` | jsonb | Full source attributes, for example `RouteType`, `Speed`, `OneWayDir`, zip codes |
| `imported_at` | timestamptz | Default `now()`, **nullable** |

The table definition is **not in the repository**. The unique key is
`source_objectid` alone, unlike the other two tables. See the task board.

### `utility_lines`: 23,463 rows, `MULTILINESTRING`

| Column | Type | Notes |
|---|---|---|
| `id` | bigint, primary key | |
| `source_system` | text, not null | `'orlando_wastewater_gravity_lines'` |
| `source_objectid` | integer, not null | Unique together with `source_system` |
| `utility_type` | text, not null | Currently always `'wastewater'` |
| `asset_subtype` | text, not null | Currently always `'gravity_line'` |
| `source_asset_id` | text | From `LineSegmentID` |
| `diameter_raw` | smallint | From `Diameter`; inches according to the city layer |
| `material_code` | text | From `PipeTypeDomain` (coded; see domains below) |
| `ownership_code` | text | From `PublicVsPrivate` (coded) |
| `geom` | geometry(MultiLineString, 4326) | |
| `source_properties` | jsonb, not null | |
| `imported_at` | timestamptz, not null | Default `now()` |

### `manholes`: 24,101 rows, `POINT`

| Column | Type | Notes |
|---|---|---|
| `id` | bigint, primary key | |
| `source_system` | text, not null | `'orlando_wastewater_manholes'` |
| `source_objectid` | integer, not null | Unique together with `source_system` |
| `structure_id` | text | From `Structure1` |
| `public_private_code` | text | From `PublicVsPrivate` (coded) |
| `geom` | geometry(Point, 4326) | |
| `source_properties` | jsonb, not null | |
| `imported_at` | timestamptz, not null | Default `now()` |

### Coded-value domains

These come from the City of Orlando ArcGIS layer metadata (`?f=json`) for
`Wastewater_Reclaim_Utilities`. The `stats` route turns codes into labels on the
server.

**`PublicVsPrivate`** (`ownership_code`, `public_private_code`):
`1` Public · `2` Private · `3` Public, abandoned/unusable · `4` Parallel · `5` Preliminary

**`PipeTypeDomain`** (`material_code`), the most common values:
`PVC` PolyVinyl Chloride · `VCP` Vitrified Clay · `VCL` Vitrified Clay – Lined ·
`SDR26` SDR26 (PVC) · `CP` Concrete · `DIP` Ductile Iron · `LINED` Lined ·
`RCPL` Reinforced Concrete – Lined. The full list is `MATERIAL_LABELS` in
`web/src/app/api/infrastructure/stats/route.ts`.

## API contracts

Base path: `/api/infrastructure`. All routes are `GET`, return JSON, and are
read-only. Errors use the form `{ "error": "<message>" }`, with `400` for invalid
input and `500` for server or database failure. Server error details are logged
on the server only, never returned.

### `GET /summary`

Returns the total number of each asset type.

```json
{
  "status": "connected",
  "infrastructure": { "roads": 14943, "pipes": 23463, "manholes": 24101 }
}
```

### `GET /features?layer=<layer>&bbox=<west,south,east,north>`

Returns the features inside a bounding box, for the map.

| Parameter | Rule |
|---|---|
| `layer` | Required. One of `roads`, `pipes`, `manholes`. The route maps these to table names through an allowlist. |
| `bbox` | Required. Four finite numbers in EPSG:4326, with west < east, south < north, and within ±180 / ±90 |

Response (GeoJSON FeatureCollection):

```json
{
  "type": "FeatureCollection",
  "features": [
    { "type": "Feature", "geometry": { "...": "GeoJSON" }, "properties": { "layer": "pipes" } }
  ],
  "truncated": false
}
```

- At most **2,000 features** per request, in no particular order. `truncated` is
  `true` when the limit is reached.
- `properties` contains **only** `layer`: no `id`, source ID or attributes. An
  asset inspector cannot be built on this contract (task-board finding F-05).

### `GET /stats`

Returns the dashboard aggregates. Lengths are computed geodesically
(`ST_Length(geom::geography)`) in miles.

```json
{
  "totals": {
    "roads": { "count": 14943, "miles": 1400.34 },
    "pipes": { "count": 23463, "miles": 891.03 },
    "manholes": { "count": 24101 }
  },
  "lastImported": "2026-11-11T05:40:09.337Z",
  "pipesByMaterial":     [ { "label": "PVC", "count": 12180, "miles": 419.89 } ],
  "pipesByDiameter":     [ { "label": "8\"", "count": 18148, "miles": 683.87 } ],
  "pipesByOwnership":    [ { "label": "Public", "count": 15682, "miles": 645.70 } ],
  "manholesByOwnership": [ { "label": "Public", "count": 15517 } ],
  "longestStreets":      [ { "label": "BOGGY CREEK RD", "count": 52, "miles": 9.51 } ]
}
```

- Each breakdown list has at most 8 entries, sorted by `miles` (or by `count` for
  manholes) from highest to lowest.
- A null or blank code is labelled `"Not recorded"`.
- `longestStreets` includes railway and express-lane centerlines because they
  are in the source data.
- The frontend must treat a missing list as empty.

## Synthetic demonstration data (`demo` schema)

**Status: proposed. Not created.** Creating it is a schema migration and needs user approval.

- Simulated data lives only in a separate `demo` schema. It is never written to
  the `public` infrastructure tables.
- Demo tables use the same column layout as their `public` equivalents, so the
  same queries work. Their `source_system` values must start with `synthetic_`,
  for example `synthetic_iot_sensor`.
- An API route that serves demo data must either be a separate route or include
  `"synthetic": true` on every record. The UI must label demo data visibly.
- Future IoT schemas, such as sensors and readings, should start out in `demo`
  until a real data source exists.
