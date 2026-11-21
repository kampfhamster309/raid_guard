import { useEffect, useMemo, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { TraceHop } from "../types";
import { groupHopsByLocation, type MapPoint } from "../lib/traceroute";

interface Props {
  hops: TraceHop[];
  target: string;
  activeHop: number | null;
  onHoverHop: (hop: number | null) => void;
}

function hopRange(hops: TraceHop[]): string {
  const first = hops[0].hop;
  const last = hops[hops.length - 1].hop;
  return first === last ? `#${first}` : `#${first}–${last}`;
}

function pointLabel(p: MapPoint): string {
  const geo = p.hops[0].geo!;
  const place = [geo.city, geo.country_code].filter(Boolean).join(", ") || "Unknown";
  const orgs = [...new Set(p.hops.map((h) => (h.asn ? `AS${h.asn.number} ${h.asn.org ?? ""}`.trim() : null)).filter(Boolean))];
  return `<strong>${hopRange(p.hops)}</strong> ${escapeHtml(place)}${
    orgs.length ? `<br/><span style="opacity:.75">${orgs.map((o) => escapeHtml(o!)).join("<br/>")}</span>` : ""
  }`;
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

const COLOR_HOP = "#818cf8"; // indigo-400
const COLOR_DEST = "#f87171"; // red-400
const COLOR_ACTIVE = "#fbbf24"; // amber-400

export function TracerouteMap({ hops, target, activeHop, onHoverHop }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markersRef = useRef<{ point: MapPoint; marker: L.CircleMarker }[]>([]);
  const points = useMemo(() => groupHopsByLocation(hops), [hops]);

  // Create the map once.
  useEffect(() => {
    if (!containerRef.current) return;
    const map = L.map(containerRef.current, { worldCopyJump: true, zoomControl: true }).setView([30, 0], 2);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      className: "rg-dark-tiles",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors',
    }).addTo(map);
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Draw route + markers whenever the result changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const layer = L.layerGroup().addTo(map);
    markersRef.current = [];

    if (points.length > 1) {
      L.polyline(
        points.map((p) => [p.lat, p.lon] as L.LatLngTuple),
        { color: COLOR_HOP, weight: 2.5, opacity: 0.85, dashArray: "6 6" }
      ).addTo(layer);
    }

    points.forEach((p) => {
      const isDest = p.hops.some((h) => h.ip === target);
      const marker = L.circleMarker([p.lat, p.lon], {
        radius: isDest ? 9 : 7,
        color: "#0f172a",
        weight: 2,
        fillColor: isDest ? COLOR_DEST : COLOR_HOP,
        fillOpacity: 1,
      })
        .bindTooltip(pointLabel(p), { direction: "top", offset: [0, -8] })
        .on("mouseover", () => onHoverHop(p.hops[0].hop))
        .on("mouseout", () => onHoverHop(null))
        .addTo(layer);
      markersRef.current.push({ point: p, marker });
    });

    if (points.length === 1) {
      map.setView([points[0].lat, points[0].lon], 6);
    } else if (points.length > 1) {
      map.fitBounds(L.latLngBounds(points.map((p) => [p.lat, p.lon] as L.LatLngTuple)), { padding: [40, 40], maxZoom: 8 });
    }

    return () => {
      layer.remove();
    };
  }, [points, target, onHoverHop]);

  // Highlight the hovered hop.
  useEffect(() => {
    markersRef.current.forEach(({ point, marker }) => {
      const isDest = point.hops.some((h) => h.ip === target);
      const active = activeHop !== null && point.hops.some((h) => h.hop === activeHop);
      marker.setStyle({ fillColor: active ? COLOR_ACTIVE : isDest ? COLOR_DEST : COLOR_HOP });
      marker.setRadius(active ? 11 : isDest ? 9 : 7);
      if (active) {
        marker.bringToFront();
        marker.openTooltip();
      } else {
        marker.closeTooltip();
      }
    });
  }, [activeHop, target, points]);

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full bg-slate-800" data-testid="traceroute-map" />
      {points.length === 0 && (
        <div className="absolute inset-0 z-[500] flex items-center justify-center pointer-events-none">
          <p className="rounded bg-slate-900/90 px-3 py-2 text-xs text-slate-300">
            No hops could be geolocated.
          </p>
        </div>
      )}
    </div>
  );
}

export default TracerouteMap;
