
import { NextResponse } from "next/server";
import { pool } from "@/lib/db";

export async function GET() {
  try {
    const result = await pool.query(`
      SELECT
        (SELECT COUNT(*) FROM road_segments) AS roads,
        (SELECT COUNT(*) FROM utility_lines) AS pipes,
        (SELECT COUNT(*) FROM manholes) AS manholes
    `);

    const row = result.rows[0];

    return NextResponse.json({
      status: "connected",
      infrastructure: {
        roads: Number(row.roads),
        pipes: Number(row.pipes),
        manholes: Number(row.manholes),
      },
    });
  } catch (error) {
    console.error("Infrastructure summary query failed:", error);

    return NextResponse.json(
      { error: "Unable to retrieve infrastructure summary" },
      { status: 500 }
    );
  }
}
