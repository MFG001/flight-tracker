"""Classify an ADS-B target without guessing.

Shape comes from the emitter category when that category names a class, then
from an optional local type-designator table. Anything else stays unknown.
Military is a separate accent: readsb dbFlags bit 0, or an optional hex-range
file the operator supplies. A callsign is never treated as evidence.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

KINDS = ("jet", "light", "rotor", "uav", "lighter", "unknown")

# DO-260B emitter categories that name a class. Other codes stay unknown.
CATEGORY_KIND = {
    "A1": "light",
    "A2": "light",
    "A3": "jet",
    "A4": "jet",
    "A5": "jet",
    "A6": "jet",
    "A7": "rotor",
    "B2": "lighter",
    "B6": "uav",
}

ROOT = Path(__file__).resolve().parent.parent
_HEX = re.compile(r"^[0-9A-F]{6}$")


def load_type_db(path: Path | None = None) -> dict[str, str]:
    file = path or (ROOT / "data" / "aircraft-types.json")
    if not file.is_file():
        return {}
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        kind = str(value).lower()
        if kind in KINDS and kind != "unknown":
            out[str(key).upper()] = kind
    return out


def load_hex_ranges(path: Path | None = None) -> list[tuple[int, int]]:
    """Optional operator file. Not shipped: the usual public compilation has no license."""
    file = path or (ROOT / "data" / "military-hex-ranges.json")
    if not file.is_file():
        return []
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = raw.get("ranges") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        return []
    spans: list[tuple[int, int]] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            continue
        try:
            start = int(str(row[0]), 16)
            end = int(str(row[1]), 16)
        except ValueError:
            continue
        if 0 <= start <= end <= 0xFFFFFF:
            spans.append((start, end))
    return spans


def hex_in_ranges(hex_id: str, ranges: list[tuple[int, int]]) -> bool:
    if not _HEX.fullmatch(hex_id):
        return False
    value = int(hex_id, 16)
    return any(start <= value <= end for start, end in ranges)


# ICAO type designators for the Maverick shapes. Category still wins when it is present.
BIZJET_TYPES = frozenset({
    "C25A", "C25B", "C25C", "C25M", "C500", "C501", "C510", "C525", "C526",
    "C550", "C551", "C560", "C56X", "C650", "C680", "C68A", "C700", "C750",
    "LJ23", "LJ24", "LJ25", "LJ28", "LJ31", "LJ35", "LJ36", "LJ40", "LJ45",
    "LJ55", "LJ60", "LJ70", "LJ75", "LJ85",
    "E50P", "E55P",
    "CL30", "CL35", "CL60",
    "GLF2", "GLF3", "GLF4", "GLF5", "GLF6", "GLEX", "GL5T", "GL7T",
    "G150", "G280", "GA5C", "GA6C", "GA7C",
    "FA10", "FA20", "FA50", "F900", "F2TH", "FA6X", "FA7X", "FA8X",
    "HDJT", "PRM1", "EA50", "BE40", "H25B", "H25C", "HA4T", "PC24",
    "E35L", "E545", "E550",
})
REGIONAL_TYPES = frozenset({
    "E135", "E145", "E45X", "E170", "E175", "E75S", "E75L", "E190", "E195", "E290", "E295",
})


def _designator(type_code: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (type_code or "").upper())


def _bizjet_type(code: str) -> bool:
    return code in BIZJET_TYPES


def _regional_type(code: str) -> bool:
    return code.startswith("CRJ") or code.startswith("ERJ") or code in REGIONAL_TYPES


def maverick_mark(category: str | None, type_code: str | None) -> str:
    """Which Maverick silhouette to draw. Military does not change this."""
    cat = (category or "").upper()
    code = _designator(type_code)
    if cat == "A1":
        return "light"
    if cat == "A2":
        return "bizjet" if _bizjet_type(code) or _regional_type(code) else "twin"
    if cat == "A3":
        return "bizjet" if _regional_type(code) else "heavy"
    if cat in {"A4", "A5"}:
        return "heavy"
    if cat == "A6":
        return "fighter"
    if cat == "A7":
        return "rotor"
    if cat == "B2":
        return "lighter"
    if cat == "B6":
        return "drone"
    if _bizjet_type(code) or _regional_type(code):
        return "bizjet"
    return "unknown"


def classify(
    category: str | None,
    db_flags: int = 0,
    hex_id: str | None = None,
    type_code: str | None = None,
    type_db: dict[str, str] | None = None,
    hex_ranges: list[tuple[int, int]] | None = None,
) -> dict[str, Any]:
    kind = CATEGORY_KIND.get((category or "").upper())
    if kind is None and type_code and type_db:
        mapped = type_db.get(type_code.upper())
        if mapped in KINDS and mapped != "unknown":
            kind = mapped
    if kind is None:
        kind = "unknown"
    military = bool(int(db_flags) & 1)
    if not military and hex_id and hex_ranges:
        military = hex_in_ranges(hex_id.upper(), hex_ranges)
    return {"kind": kind, "military": military, "mark": maverick_mark(category, type_code)}
