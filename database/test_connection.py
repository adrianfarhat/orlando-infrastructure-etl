
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()

database_url = os.environ["DATABASE_URL"]

with psycopg.connect(database_url) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT current_database(), PostGIS_Version()"
        )
        database, postgis_version = cur.fetchone()

        print("Connected to:", database)
        print("PostGIS version:", postgis_version)

