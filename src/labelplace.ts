/** Sticky placement of on-map aircraft summary labels.

The old first-fit walk (five slots, drop if none are free) flipped sides
when two aircraft were close and their distance-sort order changed, and it
hid labels once the five preferred slots were taken. This module keeps a
label where it was until that slot is clearly unusable, tries many more
offsets (including a second ring, with a leader line when the box is not
beside the icon), and only hides a label when nothing fits inside the
safe circle. Placement order is selected, then emergency, then nearest,
then a stable id tie-break.
*/

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface LabelMemory {
  ox: number;
  oy: number;
  hidden: boolean;
}

export interface PlaceItem {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  selected?: boolean;
  emergency?: boolean;
  distNm?: number;
}

export interface PlaceResult {
  id: string;
  box: Box;
  ox: number;
  oy: number;
  leader: boolean;
}

export interface PlaceOptions {
  cx: number;
  cy: number;
  radius: number;
  obstacles?: Box[];
  memory?: Map<string, LabelMemory>;
}

/** Offsets of the box's top-left from the aircraft icon. */
export function labelOffsets(w: number, h: number): { ox: number; oy: number }[] {
  const left = -w - 10;
  const mid = -w / 2;
  const right = 14;
  return [
    { ox: right, oy: -16 },
    { ox: left, oy: -16 },
    { ox: right, oy: 8 },
    { ox: left, oy: 8 },
    { ox: mid, oy: -h - 6 },
    { ox: mid, oy: h - 2 },
    { ox: right, oy: -h - 10 },
    { ox: left, oy: -h - 10 },
    { ox: right, oy: h - 2 },
    { ox: left, oy: h - 2 },
    { ox: right + w + 8, oy: -16 },
    { ox: left - w - 8, oy: -16 },
    { ox: mid, oy: -2 * h - 12 },
    { ox: mid, oy: 2 * h - 2 },
    { ox: right + w + 8, oy: 8 },
    { ox: left - w - 8, oy: 8 },
    { ox: right, oy: -2 * h - 12 },
    { ox: left, oy: -2 * h - 12 },
    { ox: right + 2 * (w + 8), oy: -16 },
    { ox: left - 2 * (w + 8), oy: -16 },
    { ox: right + w + 8, oy: -h - 10 },
    { ox: left - w - 8, oy: -h - 10 },
    { ox: mid + w + 18, oy: -2 * h - 12 },
    { ox: mid - w - 18, oy: -2 * h - 12 },
  ];
}

export function boxOverlaps(a: Box, b: Box, gap = 0): boolean {
  return !(a.x + a.w + gap <= b.x || b.x + b.w + gap <= a.x || a.y + a.h + gap <= b.y || b.y + b.h + gap <= a.y);
}

export function boxInside(box: Box, cx: number, cy: number, radius: number): boolean {
  const corners: [number, number][] = [
    [box.x, box.y],
    [box.x + box.w, box.y],
    [box.x, box.y + box.h],
    [box.x + box.w, box.y + box.h],
  ];
  return corners.every(([x, y]) => Math.hypot(x - cx, y - cy) <= radius);
}

export function needsLeader(x: number, y: number, box: Box): boolean {
  const px = Math.max(box.x, Math.min(x, box.x + box.w));
  const py = Math.max(box.y, Math.min(y, box.y + box.h));
  return Math.hypot(x - px, y - py) > 12;
}

export function leaderAnchor(x: number, y: number, box: Box): { x: number; y: number } {
  return {
    x: Math.max(box.x, Math.min(x, box.x + box.w)),
    y: Math.max(box.y, Math.min(y, box.y + box.h)),
  };
}

function fits(box: Box, placed: Box[], cx: number, cy: number, radius: number, gap: number): boolean {
  return boxInside(box, cx, cy, radius) && !placed.some((other) => boxOverlaps(box, other, gap));
}

function rank(item: PlaceItem): number {
  if (item.selected) return 0;
  if (item.emergency) return 1;
  return 2;
}

/** The five-slot first-fit used through 1.0.7, exported so tests can show the bounce. */
export function placeLabelsFirstFit(items: PlaceItem[], opts: PlaceOptions): PlaceResult[] {
  const { cx, cy, radius, obstacles = [] } = opts;
  const placed: Box[] = [...obstacles];
  const ordered = [...items].sort((a, b) => (a.distNm ?? 0) - (b.distNm ?? 0) || a.id.localeCompare(b.id));
  const out: PlaceResult[] = [];
  for (const item of ordered) {
    const slots = labelOffsets(item.w, item.h).slice(0, 5);
    let chosen: { ox: number; oy: number } | null = null;
    for (const slot of slots) {
      const box = { x: item.x + slot.ox, y: item.y + slot.oy, w: item.w, h: item.h };
      if (fits(box, placed, cx, cy, radius, 0)) {
        chosen = slot;
        break;
      }
    }
    if (!chosen) continue;
    const box = { x: item.x + chosen.ox, y: item.y + chosen.oy, w: item.w, h: item.h };
    placed.push(box);
    out.push({ id: item.id, box, ox: chosen.ox, oy: chosen.oy, leader: false });
  }
  return out;
}

export function placeLabels(items: PlaceItem[], opts: PlaceOptions): PlaceResult[] {
  const { cx, cy, radius, obstacles = [], memory } = opts;
  const placed: Box[] = [...obstacles];
  const ordered = [...items].sort((a, b) => rank(a) - rank(b) || (a.distNm ?? 0) - (b.distNm ?? 0) || a.id.localeCompare(b.id));
  const out: PlaceResult[] = [];

  for (const item of ordered) {
    const slots = labelOffsets(item.w, item.h);
    const prev = memory?.get(item.id);
    let chosen: { ox: number; oy: number } | null = null;

    if (prev && !prev.hidden) {
      const kept = { x: item.x + prev.ox, y: item.y + prev.oy, w: item.w, h: item.h };
      if (fits(kept, placed, cx, cy, radius, 0)) chosen = { ox: prev.ox, oy: prev.oy };
    }

    if (!chosen) {
      const scored = slots
        .map((slot, index) => ({
          slot,
          d: prev ? Math.hypot(slot.ox - prev.ox, slot.oy - prev.oy) : index,
        }))
        .sort((a, b) => a.d - b.d || a.slot.oy - b.slot.oy || a.slot.ox - b.slot.ox);
      for (const row of scored) {
        const box = { x: item.x + row.slot.ox, y: item.y + row.slot.oy, w: item.w, h: item.h };
        if (fits(box, placed, cx, cy, radius, 1)) {
          chosen = row.slot;
          break;
        }
      }
    }

    if (!chosen && (item.selected || item.emergency)) {
      // Last resort for a selected or emergency target: any candidate, even
      // if it clips the circle, as long as it does not cover another box.
      for (const slot of slots) {
        const box = { x: item.x + slot.ox, y: item.y + slot.oy, w: item.w, h: item.h };
        if (!placed.some((other) => boxOverlaps(box, other, 0))) {
          chosen = slot;
          break;
        }
      }
    }

    if (!chosen) {
      memory?.set(item.id, { ox: prev?.ox ?? 0, oy: prev?.oy ?? 0, hidden: true });
      continue;
    }

    const box = { x: item.x + chosen.ox, y: item.y + chosen.oy, w: item.w, h: item.h };
    placed.push(box);
    memory?.set(item.id, { ox: chosen.ox, oy: chosen.oy, hidden: false });
    out.push({ id: item.id, box, ox: chosen.ox, oy: chosen.oy, leader: needsLeader(item.x, item.y, box) });
  }

  if (memory) {
    const live = new Set(items.map((item) => item.id));
    for (const id of [...memory.keys()]) {
      if (!live.has(id)) memory.delete(id);
    }
  }
  return out;
}
