
import json
import os
import time

import psycopg
import requests
from dotenv import load_dotenv

load_dotenv()

LAYER_URL = (
    "https://services5.arcgis.com/mMuoPCaIYD4wEgDl/"
    "arcgis/rest/services/Street_Centerline/"
    "FeatureServer/0"
)

BATCH_SIZE = 200


def query_arcgis(params):
    """Request ArcGIS data, with retries."""
    for attempt in range(3):
        try:
            response = requests.post(
                f"{LAYER_URL}/query",
                data=params,
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                raise RuntimeError(data["error"])

            return data

        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def get_all_ids():
    """Get all source feature IDs."""
    data = query_arcgis({
        "where": "1=1",
        "returnIdsOnly": "true",
        "f": "json",
    })

    return sorted(data.get("objectIds") or [])


def download_batch(ids):
    """Download street features as GeoJSON."""
    data = query_arcgis({
        "objectIds": ",".join(map(str, ids)),
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": 4326,
        "f": "geojson",
    })

    if data.get("type") != "FeatureCollection":
        raise RuntimeError(
            "ArcGIS did not return GeoJSON."
        )

    return data["features"]


def load_batch(conn, features):
    """Insert or update street records."""
    loaded = 0
    missing_geometry = 0

    with conn.cursor() as cur:
        for feature in features:
            props = feature["properties"]
            geometry = feature.get("geometry")

            if not geometry:
                missing_geometry += 1
                continue

            cur.execute(
                """
                INSERT INTO road_segments (
                    source_objectid,
                    street_name,
                    geom,
                    source_properties
                )
                VALUES (
                    %s,
                    %s,
                    ST_Multi(
                        ST_SetSRID(
                            ST_GeomFromGeoJSON(%s),
                            4326
                        )
                    ),
                    %s::jsonb
                )
                ON CONFLICT (source_objectid)
                DO UPDATE SET
                    street_name = EXCLUDED.street_name,
                    geom = EXCLUDED.geom,
                    source_properties =
                        EXCLUDED.source_properties,
                    imported_at = NOW()
                """,
                (
                    props["OBJECTID"],
                    props.get("FullStreetName"),
                    json.dumps(geometry),
                    json.dumps(props),
                ),
            )

            loaded += 1

    return loaded, missing_geometry


def main():
    ids = get_all_ids()
    expected_ids = set(ids)

    print(f"ArcGIS records: {len(ids)}")

    total_loaded = 0
    total_missing = 0
    returned_ids = set()

    with psycopg.connect(
        os.environ["DATABASE_URL"]
    ) as conn:

        for start in range(0, len(ids), BATCH_SIZE):
            batch_ids = ids[start:start + BATCH_SIZE]
            features = download_batch(batch_ids)

            batch_returned_ids = [
                f["properties"]["OBJECTID"]
                for f in features
            ]

            if (
                len(batch_returned_ids) != len(batch_ids)
                or set(batch_returned_ids) != set(batch_ids)
            ):
                raise RuntimeError(
                    f"Batch mismatch at offset {start}. "
                    "Import stopped for investigation."
                )

            loaded, missing = load_batch(
                conn, features
            )

            conn.commit()

            returned_ids.update(batch_returned_ids)
            total_loaded += loaded
            total_missing += missing

            print(
                f"Processed {len(returned_ids)}"
                f"/{len(ids)} | "
                f"Loaded: {total_loaded} | "
                f"Missing geometry: {total_missing}"
            )

    if returned_ids != expected_ids:
        raise RuntimeError(
            "Some ArcGIS records were not retrieved."
        )

    print("\nIMPORT COMPLETE")
    print(f"Source records: {len(ids)}")
    print(f"Loaded: {total_loaded}")
    print(f"Missing geometry: {total_missing}")


if __name__ == "__main__":
    main()
