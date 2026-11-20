"""Onboard airport lookup. The file is local; the setup page does not call a geocoder."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def _rows() -> list[dict[str, Any]]:
    path = ROOT / "data" / "airports.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def nearest_airport(lat: float, lon: float) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_d = 1e9
    for row in _rows():
        try:
            plat = float(row["lat"])
            plon = float(row["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        dlat = (plat - lat) * 60
        dlon = (plon - lon) * 60 * max(0.2, abs(__import__("math").cos(__import__("math").radians(lat))))
        dist = dlat * dlat + dlon * dlon
        if dist < best_d:
            best_d = dist
            best = row
    return best


def find_airport(code: str) -> dict[str, Any] | None:
    """Exact ICAO or IATA match. SEA and KSEA both resolve to Seattle–Tacoma."""
    text = code.strip().upper()
    if len(text) not in (3, 4):
        return None
    for row in _rows():
        icao = str(row.get("icao") or "")
        iata = str(row.get("iata") or "")
        if text == icao or (len(text) == 3 and text == iata):
            return row
    return None


def search_airports(query: str, limit: int = 8) -> list[dict[str, Any]]:
    text = query.strip().upper()
    if len(text) < 2:
        return []
    exact = find_airport(text)
    if exact:
        return [exact]
    prefix = [row for row in _rows() if str(row.get("icao", "")).startswith(text)]
    if len(prefix) >= limit:
        return prefix[:limit]
    names = [
        row
        for row in _rows()
        if text in str(row.get("name", "")).upper() or text in str(row.get("city", "")).upper()
    ]
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in prefix + names:
        icao = str(row.get("icao"))
        if icao in seen:
            continue
        seen.add(icao)
        merged.append(row)
        if len(merged) >= limit:
            break
    return merged
