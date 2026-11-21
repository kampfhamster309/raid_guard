import type { TraceHop } from "../types";

/** Consecutive hops at the same coordinates collapse into one map point. */
export interface MapPoint {
  lat: number;
  lon: number;
  hops: TraceHop[];
}

export function groupHopsByLocation(hops: TraceHop[]): MapPoint[] {
  const points: MapPoint[] = [];
  for (const hop of hops) {
    if (!hop.geo) continue;
    const last = points[points.length - 1];
    if (last && last.lat === hop.geo.lat && last.lon === hop.geo.lon) {
      last.hops.push(hop);
    } else {
      points.push({ lat: hop.geo.lat, lon: hop.geo.lon, hops: [hop] });
    }
  }
  return points;
}

