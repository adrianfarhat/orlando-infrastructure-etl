
import { NextRequest, NextResponse } from "next/server";
import { pool } from "@/lib/db";

const tables = {
  roads: "road_segments",
  pipes: "utility_lines",
  manholes: "manholes",
} as const;

type Layer = keyof typeof tables;

export async function GET(request: NextRequest) {
  try {
    const params = request.nextUrl.searchParams;

    const layer = params.get("layer");
    const bbox = params.get("bbox");

    if (!layer || !(layer in tables)) {
      return NextResponse.json(
        { error: "Invalid infrastructure layer" },
        { status: 400 }
      );
    }

    if (!bbox) {
      return NextResponse.json(
        { error: "Bounding box is required" },
        { status: 400 }
      );
    }

    const coordinates = bbox.split(",").map(Number);

    if (
      coordinates.length !== 4 ||
      coordinates.some((value) => !Number.isFinite(value))
    ) {
      return NextResponse.json(
        { error: "Invalid bounding box" },
        { status: 400 }
      );
    }

    const [west, south, east, north] = coordinates;

    if (
      west < -180 || east > 180 ||
      south < -90 || north > 90 ||
      west >= east || south >= north
    ) {
      return NextResponse.json(
        { error: "Bounding box coordinates are invalid" },
        { status: 400 }
      );
    }

    const table = tables[layer as Layer];

    const result = await pool.query(
      `
      SELECT ST_AsGeoJSON(geom)::json AS geometry
      FROM ${table}
      WHERE ST_Intersects(
        geom,
        ST_MakeEnvelope($1, $2, $3, $4, 4326)
      )
      LIMIT 2000
      `,
      [west, south, east, north]
    );

    const features = result.rows.map((row) => ({
      type: "Feature",
      geometry: row.geometry,
      properties: {
        layer,
      },
    }));

    return NextResponse.json({
      type: "FeatureCollection",
      features,
      truncated: result.rows.length === 2000,
    });
  } catch (error) {
    console.error("Infrastructure features query failed:", error);

    return NextResponse.json(
      { error: "Unable to retrieve infrastructure features" },
      { status: 500 }
    );
  }
}
