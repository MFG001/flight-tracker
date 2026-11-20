/** Web Mercator helpers. Distances used on the scope are nautical miles. */

export const NM_TO_M = 1852;
const EARTH_CIRC = 40075016.68557849;

export interface ZoomChoice {
  z: number;
  pxPerWorldPx: number;
}

export function project(lat: number, lon: number): { x: number; y: number } {
  const clamped = Math.max(-85.05112878, Math.min(85.05112878, lat));
  const s = Math.sin((clamped * Math.PI) / 180);
  return {
    x: (lon + 180) / 360,
    y: 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI),
  };
}

export function metersPerPixel(lat: number, z: number): number {
  return (EARTH_CIRC * Math.cos((lat * Math.PI) / 180)) / (256 * 2 ** z);
}

export function chooseZoom(lat: number, screenPxPerMeter: number, minZ: number, maxZ: number): ZoomChoice {
  const cos = Math.max(0.01, Math.cos((lat * Math.PI) / 180));
  const targetMpp = 1 / Math.max(1e-9, screenPxPerMeter);
  const zFloat = Math.log2((EARTH_CIRC / 256) * cos / targetMpp);
  let z = Number.isFinite(zFloat) ? Math.round(zFloat) : minZ;
  z = Math.max(minZ, Math.min(maxZ, z));
  return { z, pxPerWorldPx: screenPxPerMeter * metersPerPixel(lat, z) };
}

export function haversineNm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const radius = 3440.065;
  const p1 = (lat1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const dp = ((lat2 - lat1) * Math.PI) / 180;
  const dl = ((lon2 - lon1) * Math.PI) / 180;
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * radius * Math.asin(Math.min(1, Math.sqrt(a)));
}

export function bearingDeg(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const p1 = (lat1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const dl = ((lon2 - lon1) * Math.PI) / 180;
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return (Math.atan2(y, x) * 180) / Math.PI;
}

export function wrap360(deg: number): number {
  return ((deg % 360) + 360) % 360;
}

export function offsetNm(lat: number, lon: number, northNm: number, eastNm: number): { lat: number; lon: number } {
  const dlat = northNm / 60;
  const dlon = eastNm / (60 * Math.max(0.01, Math.cos((lat * Math.PI) / 180)));
  return { lat: lat + dlat, lon: lon + dlon };
}
