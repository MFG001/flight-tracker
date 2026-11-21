"""Range-ring distances. The outer ring is always the selected range; inner rings split it evenly."""

from __future__ import annotations

# 1.0.8: steps are 10, 20, 30, 40, 50, 75, 100 NM (2 and 5 removed; 100 is the maximum).
RANGES = (10, 20, 30, 40, 50, 75, 100)
MIN_RANGE_NM = RANGES[0]
MAX_RANGE_NM = RANGES[-1]


def snap_range(value: float) -> int:
    """Nearest selectable step. Values below 10 (including a saved 2 or 5) become 10."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return MIN_RANGE_NM
    if v != v:  # NaN
        return MIN_RANGE_NM
    v = min(MAX_RANGE_NM, max(MIN_RANGE_NM, v))
    return min(RANGES, key=lambda item: (abs(item - v), item))


AUTO_RINGS = 0


def rings_for_range(range_nm: float) -> int:
    """Ring count that divides the selected range into even, easy-to-read labels.

    30 NM → 10/20/30, 50 NM → 10/20/30/40/50, 75 NM → 25/50/75; otherwise 4.
    """
    step = snap_range(range_nm)
    return {30: 3, 50: 5, 75: 3}.get(step, 4)


def resolve_rings(value: object, range_nm: float) -> int:
    """0 / 'auto' / missing → rings_for_range; 2–6 stays a fixed count."""
    if value in (0, "0", "auto", None, ""):
        return rings_for_range(range_nm)
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return rings_for_range(range_nm)
    return n if n in (2, 3, 4, 5, 6) else rings_for_range(range_nm)


def ring_distances(range_nm: float, count: int | None = None) -> list[float]:
    """Evenly spaced rings; the last distance is always the selected range."""
    if count is None:
        rings = rings_for_range(range_nm)
    else:
        rings = max(2, min(6, int(count)))
    return [round(range_nm * step / rings, 2) for step in range(1, rings + 1)]
