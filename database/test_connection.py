
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

database_url = os.environ["DATABASE_URL"]

with psycopg.connect(database_url) as conn:
    conn.read_only = True
    with conn.cursor() as cur:
        cur.execute(
            "SELECT current_database(), PostGIS_Version(), "
            "current_setting('transaction_read_only')"
        )
        database, postgis_version, read_only = cur.fetchone()

        print("Connected to:", database)
        print("PostGIS version:", postgis_version)
        print("Read-only session:", read_only)

