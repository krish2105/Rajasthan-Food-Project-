import type { Centre } from "@/lib/report";

/** Shared projection and colour scale for both the 3D and flat maps, so the
 *  two views cannot drift apart on where a centre sits or how it is coloured. */

const MAP_SCALE = 14;

export function project(centres: Centre[]) {
  const withCoords = centres.filter(
    (c): c is Centre & { latitude: number; longitude: number } =>
      c.latitude !== null && c.longitude !== null,
  );
  if (!withCoords.length) return [];
  const lats = withCoords.map((c) => c.latitude);
  const lons = withCoords.map((c) => c.longitude);
  const midLat = (Math.min(...lats) + Math.max(...lats)) / 2;
  const midLon = (Math.min(...lons) + Math.max(...lons)) / 2;
  return withCoords.map((centre) => ({
    centre,
    // Equirectangular about the cohort's own centroid. Over a two-district
    // span the distortion is irrelevant, and a real projection would be
    // precision the data does not justify.
    x: (centre.longitude - midLon) * MAP_SCALE * Math.cos((midLat * Math.PI) / 180),
    z: -(centre.latitude - midLat) * MAP_SCALE,
  }));
}

export function severityColor(rate: number | null): string {
  if (rate === null) return "#6d7c93";
  if (rate >= 0.4) return "#E0524F";
  if (rate >= 0.25) return "#E3A13C";
  return "#47B98A";
}
