
"use client";

import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

maplibregl.setWorkerUrl("/maplibre-gl-worker.mjs");

export type LayerName = "roads" | "pipes" | "manholes";

export type ViewportCounts = Record<
  LayerName,
  { count: number; truncated: boolean }
>;

type InfrastructureMapProps = {
  /** Called after each viewport load with per-layer feature counts. */
  onViewportChange?: (counts: ViewportCounts) => void;
};

export const layers: {
  name: LayerName;
  label: string;
  color: string;
  type: "line" | "circle";
}[] = [
  { name: "roads", label: "Roads", color: "#ef4444", type: "line" },
  { name: "pipes", label: "Wastewater pipes", color: "#2563eb", type: "line" },
  { name: "manholes", label: "Manholes", color: "#f59e0b", type: "circle" },
];

export default function InfrastructureMap({
  onViewportChange,
}: InfrastructureMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const onViewportChangeRef = useRef(onViewportChange);
  const [mapReady, setMapReady] = useState(false);
  const [visible, setVisible] = useState<Record<LayerName, boolean>>({
    roads: true,
    pipes: true,
    manholes: true,
  });

  useEffect(() => {
    onViewportChangeRef.current = onViewportChange;
  }, [onViewportChange]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: "https://tiles.openfreemap.org/styles/liberty",
      center: [-81.3792, 28.5383],
      zoom: 13,
    });

    map.addControl(
      new maplibregl.NavigationControl(),
      "top-right"
    );

    let requestController: AbortController | null = null;
    let requestSequence = 0;

    async function loadInfrastructure() {
      if (!map.isStyleLoaded()) return;

      requestController?.abort();
      const controller = new AbortController();
      requestController = controller;
      const sequence = ++requestSequence;

      const bounds = map.getBounds();

      const bbox = [
        bounds.getWest(),
        bounds.getSouth(),
        bounds.getEast(),
        bounds.getNorth(),
      ].join(",");

      const counts = {} as ViewportCounts;

      await Promise.all(
        layers.map(async (layer) => {
          try {
            const response = await fetch(
              `/api/infrastructure/features?layer=${layer.name}&bbox=${bbox}`,
              { signal: controller.signal }
            );

            if (!response.ok) {
              throw new Error(
                `${layer.name}: HTTP ${response.status}`
              );
            }

            const geojson = await response.json();

            if (controller.signal.aborted ||
                sequence !== requestSequence) {
              return;
            }

            const source = map.getSource(
              layer.name
            ) as maplibregl.GeoJSONSource | undefined;

            if (source) {
              source.setData(geojson);
            }

            counts[layer.name] = {
              count: geojson.features?.length ?? 0,
              truncated: Boolean(geojson.truncated),
            };
          } catch (error) {
            if (!controller.signal.aborted) {
              console.error(
                `Failed to load ${layer.name}`,
                error
              );
            }
          }
        })
      );

      if (
        !controller.signal.aborted &&
        sequence === requestSequence &&
        layers.every((layer) => counts[layer.name])
      ) {
        onViewportChangeRef.current?.(counts);
      }
    }

    map.on("load", () => {
      layers.forEach((layer) => {
        map.addSource(layer.name, {
          type: "geojson",
          data: {
            type: "FeatureCollection",
            features: [],
          },
        });

        if (layer.type === "line") {
          map.addLayer({
            id: layer.name,
            type: "line",
            source: layer.name,
            paint: {
              "line-color": layer.color,
              "line-width":
                layer.name === "roads" ? 3 : 2,
              "line-opacity": 0.85,
            },
          });
        
        } else {
          map.addLayer({
            id: layer.name,
            type: "circle",
            source: layer.name,
            paint: {
              "circle-color": layer.color,

              // Make manholes smaller when zoomed out
              "circle-radius": [
                "interpolate",
                ["linear"],
                ["zoom"],
                10, 0.5,
                12, 1,
                14, 2,
                16, 3,
                18, 5,
                20, 7,
              ],

              // Reduce visibility at lower zoom levels
              "circle-opacity": [
                "interpolate",
                ["linear"],
                ["zoom"],
                10, 0.15,
                12, 0.35,
                14, 0.65,
                16, 0.9,
              ],

              // Remove outlines so circles don't clutter the map
              "circle-stroke-width": 0,
            },
          });
        }

      });

      setMapReady(true);
      loadInfrastructure();
      map.on("moveend", loadInfrastructure);
    });

    mapRef.current = map;

    return () => {
      requestController?.abort();
      map.remove();
      mapRef.current = null;
      setMapReady(false);
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    layers.forEach((layer) => {
      if (map.getLayer(layer.name)) {
        map.setLayoutProperty(
          layer.name,
          "visibility",
          visible[layer.name] ? "visible" : "none"
        );
      }
    });
  }, [visible, mapReady]);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <div
        ref={containerRef}
        style={{ position: "absolute", inset: 0 }}
      />

      <fieldset
        style={{
          position: "absolute",
          top: 12,
          left: 12,
          padding: "10px 12px",
          border: "1px solid rgba(0, 0, 0, 0.12)",
          borderRadius: 8,
          background: "rgba(255, 255, 255, 0.94)",
          color: "#171717",
          fontSize: 13,
          display: "grid",
          gap: 6,
          boxShadow: "0 1px 4px rgba(0, 0, 0, 0.12)",
        }}
      >
        <legend
          style={{
            float: "left",
            fontWeight: 600,
            marginBottom: 2,
          }}
        >
          Layers
        </legend>
        {layers.map((layer) => (
          <label
            key={layer.name}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              cursor: "pointer",
            }}
          >
            <input
              type="checkbox"
              checked={visible[layer.name]}
              onChange={(event) =>
                setVisible((current) => ({
                  ...current,
                  [layer.name]: event.target.checked,
                }))
              }
            />
            <span
              aria-hidden
              style={{
                width: layer.type === "line" ? 16 : 10,
                height: layer.type === "line" ? 3 : 10,
                borderRadius: layer.type === "line" ? 2 : "50%",
                background: layer.color,
              }}
            />
            {layer.label}
          </label>
        ))}
      </fieldset>
    </div>
  );
}
