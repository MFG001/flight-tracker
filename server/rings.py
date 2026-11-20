"""Range-ring distances. The outer ring is the selected range; the inner rings split it evenly (2 to 6 rings)."""

from __future__ import annotations

# 1.0.7: 50, 75 and 100 NM added; 100 is the maximum.
RANGES = (2, 5, 10, 20, 30, 40, 50, 75, 100)
MAX_RANGE_NM = RANGES[-1]


def snap_range(value: float) -> int:
    return min(RANGES, key=lambda item: (abs(item - value), item))


def ring_distances(range_nm: float, count: int = 4) -> list[float]:
    rings = max(2, min(6, int(count)))
    return [round(range_nm * step / rings, 2) for step in range(1, rings + 1)]
