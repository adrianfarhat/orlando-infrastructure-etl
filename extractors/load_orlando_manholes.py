
"""Load Orlando manholes into Neon/PostGIS.

Default: Import the existing local GeoJSON file.
--download: Download fresh data from ArcGIS before importing.

Usage:
    python extractors/load_orlando_manholes.py
    python extractors/load_orlando_manholes.py --download
"""

import argparse
import json
import os
import time
from pathlib import Path

import psycopg
import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]

LAYER_URL = (
    "https://gis.orlando.gov/server/rest/services/Test/"
    "Wastewater_Reclaim_Utilities__Labels__Max_Scale_1_1_000_/"
    "MapServer/1"
)

OUTPUT_FILE = (
    PROJECT_ROOT / "data" / "raw" / "orlando_manholes.geojson"
)

SOURCE = "orlando_wastewater_manholes"
BATCH_SIZE = 500


def download_manholes():
    """Download manholes from Orlando ArcGIS."""

    all_features = []
    offset = 0

    with requests.Session() as session:
        while True:
            response = session.get(
                f"{LAYER_URL}/query",
                params={
                    "where": "1=1",
                    "outFields": "*",
                    "returnGeometry": "true",
                    "outSR": 4326,
                    "orderByFields": "OBJECTID ASC",
                    "resultOffset": offset,
                    "resultRecordCount": 1000,
                    "f": "geojson",
                },
                timeout=60,
            )

            response.raise_for_status()
            data = response.json()

            if "error" in data:
                raise RuntimeError(data["error"])

            features = data.get("features", [])

            if not features:
                break

            all_features.extend(features)
            offset += len(features)

            print(f"Downloaded {len(all_features)} manholes")

            if (
                len(features) < 1000
                and not data.get("exceededTransferLimit", False)
            ):
                break

            time.sleep(0.2)

    ids = [
        f.get("properties", {}).get("OBJECTID")
        for f in all_features
    ]

    if None in ids or len(ids) != len(set(ids)):
        raise RuntimeError(
            "Missing or duplicate OBJECTIDs in download"
        )

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            {
                "type": "FeatureCollection",
                "features": all_features,
            },
            file,
        )

    print(f"Saved {len(all_features)} manholes")


def load_manholes():
    """Import downloaded GeoJSON into Neon/PostGIS."""

    load_dotenv(PROJECT_ROOT / ".env")

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL missing from .env")

    if not OUTPUT_FILE.exists():
        raise RuntimeError(
            f"GeoJSON file not found: {OUTPUT_FILE}"
        )

    with OUTPUT_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    features = data.get("features", [])

    if not features:
        raise RuntimeError("No manhole features found")

    ids = []
    for feature in features:
        attrs = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        objectid = attrs.get("OBJECTID")

        if objectid is None:
            raise RuntimeError("Missing OBJECTID")

        if geometry.get("type") != "Point":
            raise RuntimeError(
                f"Invalid geometry for OBJECTID {objectid}"
            )

        coords = geometry.get("coordinates")

        if (
            not isinstance(coords, list)
            or len(coords) < 2
            or not all(
                isinstance(v, (int, float))
                and not isinstance(v, bool)
                for v in coords[:2]
            )
            or not (-180 <= coords[0] <= 180)
            or not (-90 <= coords[1] <= 90)
        ):
            raise RuntimeError(
                f"Invalid coordinates for OBJECTID {objectid}"
            )

        ids.append(objectid)

    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate OBJECTIDs found")

    print(f"Importing {len(features)} manholes")

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE EXTENSION IF NOT EXISTS postgis"
            )

            cur.execute("""
                CREATE TABLE IF NOT EXISTS manholes (
                    id BIGSERIAL PRIMARY KEY,
                    source_system TEXT NOT NULL,
                    source_objectid INTEGER NOT NULL,
                    structure_id TEXT,
                    public_private_code TEXT,
                    geom GEOMETRY(POINT, 4326),
                    source_properties JSONB NOT NULL,
                    imported_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW(),
                    UNIQUE (source_system, source_objectid)
                )
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS manholes_geom_idx
                ON manholes USING GIST (geom)
            """)

        loaded = 0

        for start in range(0, len(features), BATCH_SIZE):
            batch = features[start:start + BATCH_SIZE]

            with conn.cursor() as cur:
                for feature in batch:
                    attrs = feature["properties"]
                    geometry = feature["geometry"]

                    cur.execute("""
                        INSERT INTO manholes (
                            source_system,
                            source_objectid,
                            structure_id,
                            public_private_code,
                            geom,
                            source_properties
                        )
                        VALUES (
                            %s, %s, %s, %s,
                            ST_SetSRID(
                                ST_GeomFromGeoJSON(%s::text),
                                4326
                            ),
                            %s::jsonb
                        )
                        ON CONFLICT (
                            source_system, source_objectid
                        )
                        DO UPDATE SET
                            structure_id = EXCLUDED.structure_id,
                            public_private_code =
                                EXCLUDED.public_private_code,
                            geom = EXCLUDED.geom,
                            source_properties =
                                EXCLUDED.source_properties,
                            imported_at = NOW()
                    """, (
                        SOURCE,
                        attrs["OBJECTID"],
                        attrs.get("Structure1"),
                        attrs.get("PublicVsPrivate"),
                        json.dumps(geometry),
                        json.dumps(attrs),
                    ))

            loaded += len(batch)
            print(f"Loaded {loaded}/{len(features)}")

        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*)
                FROM manholes
                WHERE source_system = %s
            """, (SOURCE,))

            stored_count = cur.fetchone()[0]

        if stored_count != len(features):
            raise RuntimeError(
                f"Expected {len(features)} records, "
                f"found {stored_count}. Rolling back."
            )

        print(f"Verified {stored_count} manholes in Neon")

    print("Import committed successfully")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--download",
        action="store_true",
        help="Download fresh ArcGIS data before importing",
    )

    args = parser.parse_args()

    if args.download:
        download_manholes()

    load_manholes()


if __name__ == "__main__":
    main()
