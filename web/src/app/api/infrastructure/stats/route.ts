import { NextResponse } from "next/server";
import { pool } from "@/lib/db";

const METERS_PER_MILE = 1609.344;

// Coded-value domains published on the City of Orlando ArcGIS layers
// (Wastewater_Reclaim_Utilities MapServer: PublicVsPrivate, PipeTypeDomain).
const OWNERSHIP_LABELS: Record<string, string> = {
  "1": "Public",
  "2": "Private",
  "3": "Public, abandoned",
  "4": "Parallel",
  "5": "Preliminary",
};

const MATERIAL_LABELS: Record<string, string> = {
  PVC: "PVC",
  RCP: "Reinforced concrete",
  HDPE: "HDPE",
  LINED: "Lined",
  SLIP: "Slip lined",
  HOBO: "Hobas lined",
  ESCP: "Encapsulated concrete",
  UNK: "Unknown",
  TBD: "To be determined",
  SDR: "SDR (PVC)",
  C900: "C900 (PVC)",
  SDR26: "SDR26 (PVC)",
  SDR35: "SDR35 (PVC)",
  DR18: "DR18 (PVC)",
  PVCL: "PVC, lined",
  RCPL: "Reinforced concrete, lined",
  VCL: "Vitrified clay, lined",
  HDPEL: "HDPE, lined",
  ESCPL: "Encapsulated concrete, lined",
  CONCL: "Concrete, lined",
  CIL: "Cast iron, lined",
  DIL: "Ductile iron, lined",
  SDRL: "SDR (PVC), lined",
  C900L: "C900 (PVC), lined",
  SDR26L: "SDR26 (PVC), lined",
  SDR35L: "SDR35 (PVC), lined",
  DR18L: "DR18 (PVC), lined",
  VCP: "Vitrified clay",
  CP: "Concrete",
  CAS: "Cast iron",
  DIP: "Ductile iron",
  PCCP: "Prestressed concrete",
};

type BreakdownRow = { label: string | null; count: string; miles?: string };

function toBreakdown(
  rows: BreakdownRow[],
  labels?: Record<string, string>
) {
  return rows.map((row) => ({
    label:
      row.label === null
        ? "Not recorded"
        : labels?.[row.label] ?? row.label,
    count: Number(row.count),
    miles: row.miles === undefined ? undefined : Number(row.miles),
  }));
}

export async function GET() {
  try {
    const [
      totals,
      pipesByMaterial,
      pipesByDiameter,
      pipesByOwnership,
      manholesByOwnership,
      longestStreets,
    ] = await Promise.all([
      pool.query(
        `
        SELECT
          (SELECT COUNT(*) FROM road_segments) AS road_count,
          (SELECT COALESCE(SUM(ST_Length(geom::geography)), 0) / $1
             FROM road_segments) AS road_miles,
          (SELECT COUNT(*) FROM utility_lines) AS pipe_count,
          (SELECT COALESCE(SUM(ST_Length(geom::geography)), 0) / $1
             FROM utility_lines) AS pipe_miles,
          (SELECT COUNT(*) FROM manholes) AS manhole_count,
          GREATEST(
            (SELECT MAX(imported_at) FROM road_segments),
            (SELECT MAX(imported_at) FROM utility_lines),
            (SELECT MAX(imported_at) FROM manholes)
          ) AS last_imported
        `,
        [METERS_PER_MILE]
      ),
      pool.query(
        `
        SELECT NULLIF(TRIM(material_code), '') AS label,
               COUNT(*) AS count,
               SUM(ST_Length(geom::geography)) / $1 AS miles
        FROM utility_lines
        GROUP BY 1
        ORDER BY miles DESC NULLS LAST
        LIMIT 8
        `,
        [METERS_PER_MILE]
      ),
      pool.query(
        `
        SELECT CASE
                 WHEN diameter_raw IS NULL OR diameter_raw <= 0 THEN NULL
                 ELSE diameter_raw::text || '"'
               END AS label,
               COUNT(*) AS count,
               SUM(ST_Length(geom::geography)) / $1 AS miles
        FROM utility_lines
        GROUP BY 1
        ORDER BY miles DESC NULLS LAST
        LIMIT 8
        `,
        [METERS_PER_MILE]
      ),
      pool.query(
        `
        SELECT NULLIF(TRIM(ownership_code), '') AS label,
               COUNT(*) AS count,
               SUM(ST_Length(geom::geography)) / $1 AS miles
        FROM utility_lines
        GROUP BY 1
        ORDER BY miles DESC NULLS LAST
        LIMIT 8
        `,
        [METERS_PER_MILE]
      ),
      pool.query(`
        SELECT NULLIF(TRIM(public_private_code), '') AS label,
               COUNT(*) AS count
        FROM manholes
        GROUP BY 1
        ORDER BY count DESC
        LIMIT 8
      `),
      pool.query(
        `
        SELECT street_name AS label,
               COUNT(*) AS count,
               SUM(ST_Length(geom::geography)) / $1 AS miles
        FROM road_segments
        WHERE NULLIF(TRIM(street_name), '') IS NOT NULL
        GROUP BY 1
        ORDER BY miles DESC NULLS LAST
        LIMIT 8
        `,
        [METERS_PER_MILE]
      ),
    ]);

    const row = totals.rows[0];

    return NextResponse.json({
      totals: {
        roads: { count: Number(row.road_count), miles: Number(row.road_miles) },
        pipes: { count: Number(row.pipe_count), miles: Number(row.pipe_miles) },
        manholes: { count: Number(row.manhole_count) },
      },
      lastImported: row.last_imported,
      pipesByMaterial: toBreakdown(pipesByMaterial.rows, MATERIAL_LABELS),
      pipesByDiameter: toBreakdown(pipesByDiameter.rows),
      pipesByOwnership: toBreakdown(pipesByOwnership.rows, OWNERSHIP_LABELS),
      manholesByOwnership: toBreakdown(
        manholesByOwnership.rows,
        OWNERSHIP_LABELS
      ),
      longestStreets: toBreakdown(longestStreets.rows),
    });
  } catch (error) {
    console.error("Infrastructure stats query failed:", error);

    return NextResponse.json(
      { error: "Unable to retrieve infrastructure statistics" },
      { status: 500 }
    );
  }
}
