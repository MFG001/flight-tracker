/** Fading track history (setup: TRAILS). Pure logic, unit-tested with node. */
import type { Aircraft } from "./types";

export interface TrailPoint { t: number; lat: number; lon: number }
export interface TrailLine { id: string; points: { lat: number; lon: number; age: number }[] }

/**
 * Add the latest positions. A point is added only when the aircraft moved
 * (the feed repeats a position between updates) and at most once a second.
 * Points older than keepMs drop off; a trail survives a short feed gap.
 */
export function recordTrails(history: Map<string, TrailPoint[]>, list: Aircraft[], now: number, keepMs: number): void {
  for (const item of list) {
    if (!Number.isFinite(item.lat) || !Number.isFinite(item.lon)) continue;
    const points = history.get(item.id) ?? [];
    const last = points[points.length - 1];
    const moved = !last || last.lat !== item.lat || last.lon !== item.lon;
    if (moved && (!last || now - last.t > 1000)) points.push({ t: now, lat: item.lat, lon: item.lon });
    history.set(item.id, points);
  }
  for (const [id, points] of [...history]) {
    while (points.length && now - points[0].t > keepMs) points.shift();
    if (!points.length) history.delete(id);
  }
}

/**
 * Lines to draw: recorded points for each aircraft on the glass, joined to
 * where its icon is drawn now (age 0 = newest, 1 = about to drop off).
 */
export function trailLines(history: Map<string, TrailPoint[]>, shown: Aircraft[], now: number, keepMs: number): TrailLine[] {
  const out: TrailLine[] = [];
  const live = new Map(shown.map((item) => [item.id, item]));
  for (const [id, recorded] of history) {
    const head = live.get(id);
    if (!head) continue;
    const points = recorded
      .filter((point) => now - point.t <= keepMs)
      .map((point) => ({ lat: point.lat, lon: point.lon, age: Math.min(1, Math.max(0, (now - point.t) / keepMs)) }));
    points.push({ lat: head.lat, lon: head.lon, age: 0 });
    if (points.length > 1) out.push({ id, points });
  }
  return out;
}

/** Stroke opacity for a segment ending at a point of this age. */
export function trailAlpha(age: number): number {
  const fade = Math.max(0, 1 - age);
  return 0.12 + 0.78 * fade;
}
