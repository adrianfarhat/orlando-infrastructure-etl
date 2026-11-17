"use client";

import { useEffect, useState } from "react";
import styles from "@/app/operations/map/operations.module.css";
import {
  layers,
  type LayerName,
  type ViewportCounts,
} from "@/components/InfrastructureMap";

type BreakdownItem = { label: string; count: number; miles?: number };

type InfrastructureStats = {
  totals: {
    roads: { count: number; miles: number };
    pipes: { count: number; miles: number };
    manholes: { count: number };
  };
  lastImported: string | null;
  pipesByMaterial: BreakdownItem[];
  pipesByDiameter: BreakdownItem[];
  pipesByOwnership: BreakdownItem[];
  manholesByOwnership: BreakdownItem[];
  longestStreets: BreakdownItem[];
};

const integer = new Intl.NumberFormat("en-US");
const oneDecimal = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

const layerColor = Object.fromEntries(
  layers.map((layer) => [layer.name, layer.color])
) as Record<LayerName, string>;

function formatMiles(miles: number) {
  return `${oneDecimal.format(miles)} mi`;
}

function StatTile({
  label,
  layer,
  value,
  sub,
}: {
  label: string;
  layer?: LayerName;
  value: string;
  sub?: string;
}) {
  return (
    <div className={`${styles.card} ${styles.tile}`}>
      <span className={styles.tileLabel}>
        {layer && (
          <span
            aria-hidden
            className={styles.swatch}
            style={{ background: layerColor[layer] }}
          />
        )}
        {label}
      </span>
      <span className={styles.tileValue}>{value}</span>
      {sub && <span className={styles.tileSub}>{sub}</span>}
    </div>
  );
}

function BreakdownPanel({
  title,
  subtitle,
  items,
  measure,
}: {
  title: string;
  subtitle: string;
  /** May be missing if the API response is from an older route version. */
  items: BreakdownItem[] | undefined;
  measure: "miles" | "count";
}) {
  items = items ?? [];
  const valueOf = (item: BreakdownItem) =>
    measure === "miles" ? item.miles ?? 0 : item.count;
  const max = Math.max(...items.map(valueOf), 0);

  return (
    <section className={styles.card}>
      <header className={styles.cardHeader}>
        <h3 className={styles.sectionTitle} style={{ margin: 0, fontSize: 15 }}>
          {title}
        </h3>
        <span>{subtitle}</span>
      </header>
      <div className={styles.panelBody}>
        {items.length === 0 ? (
          <p className={styles.message} style={{ padding: 0 }}>
            No data
          </p>
        ) : (
          <ul className={styles.bars}>
            {items.map((item) => {
              const value = valueOf(item);
              const tooltip = [
                item.label,
                item.miles !== undefined
                  ? formatMiles(item.miles)
                  : undefined,
                `${integer.format(item.count)} features`,
              ]
                .filter(Boolean)
                .join(" · ");

              return (
                <li key={item.label} className={styles.barRow} title={tooltip}>
                  <span className={styles.barLabel}>{item.label}</span>
                  <span className={styles.barTrack}>
                    <span
                      className={styles.barFill}
                      style={{
                        display: "block",
                        width: max > 0 ? `${(value / max) * 100}%` : 0,
                      }}
                    />
                  </span>
                  <span className={styles.barValue}>
                    {measure === "miles"
                      ? formatMiles(value)
                      : integer.format(value)}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}

export default function InfrastructureDashboard({
  viewport,
}: {
  viewport: ViewportCounts | null;
}) {
  const [stats, setStats] = useState<InfrastructureStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    fetch("/api/infrastructure/stats", {
      signal: controller.signal,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        setStats(await response.json());
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          console.error("Failed to load infrastructure stats", err);
          setError("Unable to load infrastructure statistics.");
        }
      });

    return () => controller.abort();
  }, []);

  return (
    <section aria-labelledby="dashboard-title" style={{ display: "grid", gap: 16 }}>
      <h2 id="dashboard-title" className={styles.sectionTitle} style={{ margin: 0 }}>
        Infrastructure Dashboard
      </h2>

      <div className={styles.card}>
        <header className={styles.cardHeader}>
          <h2>In current map view</h2>
          <span>Updates as you pan and zoom</span>
        </header>
        <div className={styles.viewport}>
          {viewport ? (
            layers.map((layer) => (
              <span key={layer.name} className={styles.tileLabel}>
                <span
                  aria-hidden
                  className={styles.swatch}
                  style={{ background: layer.color }}
                />
                {layer.label}:{" "}
                <strong>
                  {integer.format(viewport[layer.name].count)}
                  {viewport[layer.name].truncated && "+"}
                </strong>
              </span>
            ))
          ) : (
            <span>Loading map…</span>
          )}
        </div>
      </div>

      {error && <p className={`${styles.message} ${styles.error}`}>{error}</p>}
      {!stats && !error && <p className={styles.message}>Loading statistics…</p>}

      {stats && (
        <>
          <div className={styles.tiles}>
            <StatTile
              label="Road segments"
              layer="roads"
              value={integer.format(stats.totals.roads.count)}
              sub={`${formatMiles(stats.totals.roads.miles)} of roadway`}
            />
            <StatTile
              label="Wastewater pipes"
              layer="pipes"
              value={integer.format(stats.totals.pipes.count)}
              sub={`${formatMiles(stats.totals.pipes.miles)} of pipe`}
            />
            <StatTile
              label="Manholes"
              layer="manholes"
              value={integer.format(stats.totals.manholes.count)}
              sub={
                stats.totals.pipes.miles > 0
                  ? `${oneDecimal.format(
                      stats.totals.manholes.count / stats.totals.pipes.miles
                    )} per mile of pipe`
                  : undefined
              }
            />
            <StatTile
              label="Last data import"
              value={
                stats.lastImported
                  ? new Date(stats.lastImported).toLocaleDateString("en-US", {
                      month: "short",
                      day: "numeric",
                      year: "numeric",
                    })
                  : "—"
              }
              sub={
                stats.lastImported
                  ? new Date(stats.lastImported).toLocaleTimeString("en-US", {
                      hour: "numeric",
                      minute: "2-digit",
                    })
                  : undefined
              }
            />
          </div>

          <div className={styles.panels}>
            <BreakdownPanel
              title="Pipe length by material"
              subtitle="Top 8, miles"
              items={stats.pipesByMaterial}
              measure="miles"
            />
            <BreakdownPanel
              title="Pipe length by diameter"
              subtitle="Top 8, miles"
              items={stats.pipesByDiameter}
              measure="miles"
            />
            <BreakdownPanel
              title="Pipe length by ownership"
              subtitle="Miles"
              items={stats.pipesByOwnership}
              measure="miles"
            />
            <BreakdownPanel
              title="Manholes by ownership"
              subtitle="Count"
              items={stats.manholesByOwnership}
              measure="count"
            />
            <BreakdownPanel
              title="Longest streets"
              subtitle="Top 8, miles of segments"
              items={stats.longestStreets}
              measure="miles"
            />
          </div>
        </>
      )}
    </section>
  );
}
