/**
 * Which aircraft are on the scope right now (1.0.3). Pure logic, unit-tested with node.
 *
 * The same list decides standby (#idle) and is handed to radar.draw, so the
 * screen only wakes for an aircraft that will be painted inside the outer ring.
 * 1.0.2 woke on every aircraft the server sent; adsb.fi is asked for
 * 1.25 x range + 2 NM (27 NM at 20 NM) and a local receiver sends everything it
 * hears, so traffic outside the ring woke the screen and was then clipped.
 */
import type { Aircraft } from "./types";

/** Keep a hair inside the ring so the radar's own pixel clip never drops a listed aircraft. */
export const SCOPE_EDGE = 0.985;

export interface ScopeView {
  centerLat: number;
  centerLon: number;
  rangeNm: number;
  watchOnly: boolean;
  inBand: (item: Aircraft) => boolean;
  place?: (item: Aircraft) => Aircraft;
}

export function distanceNm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const p1 = (lat1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const dp = ((lat2 - lat1) * Math.PI) / 180;
  const dl = ((lon2 - lon1) * Math.PI) / 180;
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * 3440.065 * Math.asin(Math.min(1, Math.sqrt(a)));
}

function finiteOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function validPosition(item: Aircraft): boolean {
  const lat = finiteOrNull(item.lat);
  const lon = finiteOrNull(item.lon);
  return lat != null && lon != null && Math.abs(lat) <= 90 && Math.abs(lon) <= 180;
}

/** Past the ring out to this many ranges, an aircraft gets a small edge tick (not a wake). */
export const TICK_REACH = 1.45;

/**
 * Aircraft that will genuinely draw inside the scope, already dead-reckoned.
 * Pass `beyond` to collect traffic just outside the ring for the edge ticks.
 */
export function scopeAircraft(list: Aircraft[], view: ScopeView, beyond?: Aircraft[]): Aircraft[] {
  const out: Aircraft[] = [];
  const range = Number.isFinite(view.rangeNm) && view.rangeNm > 0 ? view.rangeNm : 0;
  if (!range || !Number.isFinite(view.centerLat) || !Number.isFinite(view.centerLon)) return out;
  for (const raw of list) {
    if (!raw || !validPosition(raw)) continue;
    if (view.watchOnly && raw.watched === false) continue;
    if (!view.inBand(raw)) continue;
    // Missing or junk track / speed must never turn into NaN in the canvas.
    const clean: Aircraft = { ...raw, track: finiteOrNull(raw.track), gsKt: finiteOrNull(raw.gsKt) };
    let item = view.place ? view.place(clean) : clean;
    if (!validPosition(item)) item = clean;
    const dist = distanceNm(view.centerLat, view.centerLon, item.lat, item.lon);
    if (dist > range * SCOPE_EDGE) {
      if (beyond && dist > range && dist < range * TICK_REACH) beyond.push(item);
      continue;
    }
    out.push(item);
  }
  return out;
}
