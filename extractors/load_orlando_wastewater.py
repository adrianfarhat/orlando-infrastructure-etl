
"""Load Orlando wastewater gravity lines into Neon/PostGIS.

Test:
    python extractors/load_orlando_wastewater.py            (dry run, no database access)
    python extractors/load_orlando_wastewater.py --write    (writes 5 records)

Full extraction (after verifying data-use permission):
    python extractors/load_orlando_wastewater.py --full --write

Requires:
    pip install requests "psycopg[binary]" python-dotenv
"""

import argparse
import json
import os
import time
from pathlib import Path

import psycopg
import requests
from dotenv import load_dotenv


BASE_URL = (
    "https://gis.orlando.gov/server/rest/services/PRR/"
    "Wastewater_Reclaim_Utilities/MapServer/12/query"
)

SOURCE = "orlando_wastewater_gravity_lines"
BATCH_SIZE = 200


def fetch(session, params):
    """Request JSON from the ArcGIS API."""

    for attempt in range(4):
        try:
            response = session.get(
                BASE_URL,
                params={"f": "json", **params},
                timeout=60,
            )

            response.raise_for_status()
            data = response.json()

            if "error" in data:
                raise RuntimeError(
                    f"ArcGIS error: {data['error']}"
                )

            return data

        except (requests.RequestException, ValueError) as exc:
            if attempt == 3:
                raise RuntimeError(
                    f"Request failed: {exc}"
                ) from exc

            time.sleep(2 ** attempt)

    raise RuntimeError("Request failed")


def get_ids(session):
    """Get all available wastewater pipe OBJECTIDs."""

    data = fetch(
        session,
        {
            "where": "1=1",
            "returnIdsOnly": "true",
        },
    )

    ids = data.get("objectIds")

    if not isinstance(ids, list):
        raise RuntimeError("No objectIds array returned")

    return sorted(set(ids))


def get_features(session, ids):
    """Retrieve pipe records for a batch of IDs."""

    data = fetch(
        session,
        {
            "objectIds": ",".join(map(str, ids)),
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": 4326,
        },
    )

    features = data.get("features")

    if not isinstance(features, list):
        raise RuntimeError("No features array returned")

    if data.get("exceededTransferLimit"):
        raise RuntimeError(
            "Batch exceeded transfer limit; lower BATCH_SIZE"
        )

    returned_ids = [
        feature.get("attributes", {}).get("OBJECTID")
        for feature in features
    ]

    if (
        len(returned_ids) != len(set(returned_ids))
        or set(returned_ids) != set(ids)
    ):
        raise RuntimeError(
            "Returned feature IDs do not match requested IDs"
        )

    return features


def geojson_multiline(feature):
    """Convert ArcGIS polyline paths into GeoJSON."""

    geometry = feature.get("geometry") or {}
    paths = geometry.get("paths")

    if not paths:
        return None

    return json.dumps(
        {
            "type": "MultiLineString",
            "coordinates": paths,
        }
    )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--full",
        action="store_true",
        help="Load all records (verify permitted use first)",
    )

    parser.add_argument(
        "--write",
        action="store_true",
        help="Write to the database (default: dry run, no database connection)",
    )

    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent

    load_dotenv(project_root / ".env")

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise SystemExit(
            "DATABASE_URL is missing from the project .env file"
        )

    with requests.Session() as session:

        session.headers.update(
            {"User-Agent": "Orlando-Infrastructure-ETL/1.0"}
        )

        ids = get_ids(session)

        selected = ids if args.full else ids[:5]

        mode = "full" if args.full else "test"

        print(
            f"API reports {len(ids)} IDs; "
            f"selected {len(selected)} ({mode} mode)"
        )

        if not args.write:
            print(
                "Dry run: no database connection made. "
                "Re-run with --write to load these records."
            )
            return

        with psycopg.connect(database_url) as conn:

            # Create the database table.
            with conn.cursor() as cur:

                cur.execute(
                    "CREATE EXTENSION IF NOT EXISTS postgis"
                )

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS utility_lines (
                        id BIGSERIAL PRIMARY KEY,
                        source_system TEXT NOT NULL,
                        source_objectid INTEGER NOT NULL,
                        utility_type TEXT NOT NULL,
                        asset_subtype TEXT NOT NULL,
                        source_asset_id TEXT,
                        diameter_raw SMALLINT,
                        material_code TEXT,
                        ownership_code TEXT,
                        geom GEOMETRY(MULTILINESTRING, 4326),
                        source_properties JSONB NOT NULL,
                        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        UNIQUE (source_system, source_objectid)
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS utility_lines_geom_idx
                    ON utility_lines USING GIST (geom)
                """)

            loaded = 0

            # Download and load records in batches.
            for start in range(0, len(selected), BATCH_SIZE):

                batch_ids = selected[start:start + BATCH_SIZE]

                features = get_features(session, batch_ids)

                with conn.cursor() as cur:

                    for feature in features:

                        attrs = feature["attributes"]

                        geometry = geojson_multiline(feature)

                        cur.execute("""
                            INSERT INTO utility_lines (
                                source_system,
                                source_objectid,
                                utility_type,
                                asset_subtype,
                                source_asset_id,
                                diameter_raw,
                                material_code,
                                ownership_code,
                                geom,
                                source_properties
                            )
                            VALUES (
                                %s,
                                %s,
                                'wastewater',
                                'gravity_line',
                                %s,
                                %s,
                                %s,
                                %s,
                                ST_SetSRID(
                                    ST_GeomFromGeoJSON(%s::text),
                                    4326
                                ),
                                %s::jsonb
                            )
                            ON CONFLICT (
                                source_system,
                                source_objectid
                            )
                            DO UPDATE SET
                                source_asset_id = EXCLUDED.source_asset_id,
                                diameter_raw = EXCLUDED.diameter_raw,
                                material_code = EXCLUDED.material_code,
                                ownership_code = EXCLUDED.ownership_code,
                                geom = EXCLUDED.geom,
                                source_properties = EXCLUDED.source_properties,
                                imported_at = NOW()
                        """, (
                            SOURCE,
                            attrs["OBJECTID"],
                            attrs.get("LineSegmentID"),
                            attrs.get("Diameter"),
                            attrs.get("PipeTypeDomain"),
                            attrs.get("PublicVsPrivate"),
                            geometry,
                            json.dumps(attrs),
                        ))

                conn.commit()

                loaded += len(features)

                print(
                    f"Loaded {loaded}/{len(selected)} records"
                )

                time.sleep(0.25)

            # Verify the number of stored records.
            with conn.cursor() as cur:

                cur.execute("""
                    SELECT COUNT(*)
                    FROM utility_lines
                    WHERE source_system = %s
                """, (SOURCE,))

                stored_count = cur.fetchone()[0]

            print(
                f"Finished. {stored_count} records "
                f"currently stored for {SOURCE}."
            )

            if args.full and stored_count != len(ids):
                print(
                    "WARNING: Database count differs from "
                    "current API IDs. Check for stale or "
                    "deleted source records."
                )


if __name__ == "__main__":
    main()
