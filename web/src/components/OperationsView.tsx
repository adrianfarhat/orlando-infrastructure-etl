"use client";

import { useState } from "react";
import styles from "@/app/operations/map/operations.module.css";
import InfrastructureMap, {
  type ViewportCounts,
} from "@/components/InfrastructureMap";
import InfrastructureDashboard from "@/components/InfrastructureDashboard";

export default function OperationsView() {
  const [viewport, setViewport] = useState<ViewportCounts | null>(null);

  return (
    <div className={styles.content}>
      <section className={styles.card} aria-labelledby="map-title">
        <header className={styles.cardHeader}>
          <h2 id="map-title">Infrastructure Map</h2>
          <span>Roads, wastewater pipes and manholes · Orlando, FL</span>
        </header>
        <div className={styles.mapFrame}>
          <InfrastructureMap onViewportChange={setViewport} />
        </div>
      </section>

      <InfrastructureDashboard viewport={viewport} />
    </div>
  );
}
