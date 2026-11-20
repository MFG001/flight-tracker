/** Outer ring is the selected range. Inner rings split it evenly (2 to 6 rings). */

// 1.0.7: 50, 75 and 100 NM added; 100 is the maximum.
export const RANGE_STEPS = [2, 5, 10, 20, 30, 40, 50, 75, 100] as const;
export const MAX_RANGE_NM = RANGE_STEPS[RANGE_STEPS.length - 1];

export function snapRange(value: number): number {
  const clamped = Math.max(2, Math.min(MAX_RANGE_NM, value));
  let best: number = RANGE_STEPS[0];
  let bestGap = Infinity;
  for (const step of RANGE_STEPS) {
    const gap = Math.abs(step - clamped);
    if (gap < bestGap) {
      bestGap = gap;
      best = step;
    }
  }
  return best;
}

export const RING_COUNTS = [2, 3, 4, 5, 6] as const;

export function ringCount(value: unknown): number {
  const n = Math.round(Number(value));
  return Number.isFinite(n) ? Math.max(2, Math.min(6, n)) : 4;
}

export function ringDistances(rangeNm: number, count = 4): number[] {
  const rings = ringCount(count);
  return Array.from({ length: rings }, (_, index) => Math.round((rangeNm * (index + 1) / rings) * 100) / 100);
}

/** Which ring labels to draw so neighbours stay at least minGapPx apart. The outer label is always kept. */
export function ringLabelMask(count: number, outerRadiusPx: number, minGapPx = 26): boolean[] {
  const rings = ringCount(count);
  const gap = outerRadiusPx / rings;
  const stride = gap >= minGapPx ? 1 : Math.ceil(minGapPx / Math.max(1, gap));
  return Array.from({ length: rings }, (_, index) => (rings - 1 - index) % stride === 0);
}

export function formatRing(nm: number): string {
  if (nm >= 10) return String(Math.round(nm));
  const text = nm.toFixed(1);
  return text.endsWith(".0") ? text.slice(0, -2) : text;
}
