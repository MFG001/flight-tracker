/** Outer ring is the selected range. Inner rings split it evenly (2 to 6 rings). */

// 1.0.8: steps are 10, 20, 30, 40, 50, 75, 100 NM (2 and 5 removed; 100 is the maximum).
export const RANGE_STEPS = [10, 20, 30, 40, 50, 75, 100] as const;
export const MIN_RANGE_NM = RANGE_STEPS[0];
export const MAX_RANGE_NM = RANGE_STEPS[RANGE_STEPS.length - 1];

export function snapRange(value: number): number {
  const clamped = Math.max(MIN_RANGE_NM, Math.min(MAX_RANGE_NM, Number.isFinite(value) ? value : MIN_RANGE_NM));
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

/** 0 on the config means auto: pick a count so labels stay round for this range. */
export const AUTO_RINGS = 0;
export const RING_COUNTS = [2, 3, 4, 5, 6] as const;

/** Ring count that divides the selected range into even, easy-to-read labels.
 *  30 NM → 10/20/30, 50 NM → 10/20/30/40/50, 75 NM → 25/50/75; otherwise 4. */
export function ringsForRange(rangeNm: number): number {
  switch (snapRange(rangeNm)) {
    case 30: return 3;
    case 50: return 5;
    case 75: return 3;
    default: return 4;
  }
}

/** 0 / "auto" / missing → ringsForRange; 2–6 stays a fixed count. */
export function resolveRings(value: unknown, rangeNm: number): number {
  if (value === 0 || value === "0" || value === "auto" || value == null || value === "") {
    return ringsForRange(rangeNm);
  }
  const n = Math.round(Number(value));
  if (Number.isFinite(n) && n >= 2 && n <= 6) return n;
  return ringsForRange(rangeNm);
}

/** Clamp a stored ring preference: 0 (auto) or 2–6. */
export function ringCount(value: unknown): number {
  if (value === 0 || value === "0" || value === "auto" || value == null || value === "") return AUTO_RINGS;
  const n = Math.round(Number(value));
  return Number.isFinite(n) && n >= 2 && n <= 6 ? n : AUTO_RINGS;
}

export function ringDistances(rangeNm: number, count = 4): number[] {
  const rings = Math.max(2, Math.min(6, Math.round(Number(count)) || 4));
  return Array.from({ length: rings }, (_, index) => Math.round((rangeNm * (index + 1) / rings) * 100) / 100);
}

/** Which ring labels to draw so neighbours stay at least minGapPx apart. The outer label is always kept. */
export function ringLabelMask(count: number, outerRadiusPx: number, minGapPx = 26): boolean[] {
  const rings = Math.max(2, Math.min(6, Math.round(Number(count)) || 4));
  const gap = outerRadiusPx / rings;
  const stride = gap >= minGapPx ? 1 : Math.ceil(minGapPx / Math.max(1, gap));
  return Array.from({ length: rings }, (_, index) => (rings - 1 - index) % stride === 0);
}

export function formatRing(nm: number): string {
  if (nm >= 10) return String(Math.round(nm));
  const text = nm.toFixed(1);
  return text.endsWith(".0") ? text.slice(0, -2) : text;
}
