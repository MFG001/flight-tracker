"""Watch-list matching.

Supported identifiers: registration / tail number (N123AB, C-GABC, G-EZAB),
callsign / flight number as broadcast (AAL100, N123AB), and the 24-bit ICAO
hex address (A1B2C3). US N-numbers resolve to hex offline; other tails need a
registration field or a local table. A list can be typed with commas, spaces,
semicolons, or new lines between entries, in any letter case.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    from nnumber import n_number_to_hex, normalize_token
except ImportError:
    from server.nnumber import n_number_to_hex, normalize_token

ROOT = Path(__file__).resolve().parent.parent
_HEX = re.compile(r"^[0-9A-F]{6}$")
_TAIL = re.compile(r"^[A-Z0-9]{2,7}$")


def canonical_watch(value: str) -> str | None:
    text = normalize_token(value)
    if _HEX.fullmatch(text) or _TAIL.fullmatch(text):
        return text
    return None


WATCH_LIMIT = 40
WATCH_EXAMPLE = "N123AB, AAL100, A1B2C3"
_SEPARATORS = re.compile(r"[\s,;]+")


def parse_watch_text(text: str) -> tuple[list[str], list[str]]:
    """Split typed text into (accepted, rejected) watch entries.

    Commas, semicolons, spaces, tabs, and new lines all separate entries.
    Entries are upper-cased and trimmed; duplicates keep their first place.
    A dash inside an entry (C-GABC) is allowed and removed.
    """
    accepted: list[str] = []
    rejected: list[str] = []
    for raw in _SEPARATORS.split(str(text or "")):
        if not raw:
            continue
        token = canonical_watch(raw)
        if token is None:
            if raw not in rejected:
                rejected.append(raw)
            continue
        if token not in accepted:
            accepted.append(token)
    return accepted[:WATCH_LIMIT], rejected


def load_registration_db(path: Path | None = None) -> dict[str, str]:
    file = path or (ROOT / "data" / "registrations.json")
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
        token = canonical_watch(str(key))
        hex_id = normalize_token(str(value))
        if token and _HEX.fullmatch(hex_id):
            out[token] = hex_id
    return out


def watched_hexes(tails: list[str], registry: dict[str, str] | None = None) -> set[str]:
    found: set[str] = set()
    table = registry or {}
    for tail in tails:
        token = canonical_watch(tail) or ""
        if _HEX.fullmatch(token):
            found.add(token)
            continue
        converted = n_number_to_hex(token)
        if converted:
            found.add(converted)
        mapped = table.get(token)
        if mapped:
            found.add(mapped)
    return found


def is_watched(aircraft: dict[str, Any], tails: list[str], registry: dict[str, str] | None = None) -> bool:
    tokens = {canonical_watch(tail) for tail in tails}
    tokens.discard(None)
    hex_id = normalize_token(str(aircraft.get("hex") or ""))
    registration = canonical_watch(str(aircraft.get("registration") or "")) or ""
    if registration and registration in tokens:
        return True
    callsign = canonical_watch(str(aircraft.get("callsign") or aircraft.get("flight") or "")) or ""
    if callsign and callsign in tokens:
        return True
    if hex_id and _HEX.fullmatch(hex_id) and hex_id in tokens:
        return True
    return bool(hex_id) and hex_id in watched_hexes([t for t in tokens if t], registry)


def filter_aircraft(rows: list[dict[str, Any]], watch: dict[str, Any] | None, registry: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Mark watched aircraft (``watched: True``); with "show only watched" on, drop the rest.

    The flag lets the display raise a "Watched Tail Numbers" alert even when
    every aircraft is shown (1.0.2 only alerted with the filter on).
    """
    if not isinstance(watch, dict):
        return rows
    tails = [str(item) for item in watch.get("tails") or [] if item] if isinstance(watch.get("tails"), list) else []
    if not tails:
        return [] if watch.get("enabled") else rows
    marked = [dict(row, watched=is_watched(row, tails, registry)) for row in rows]
    if not watch.get("enabled"):
        return marked
    return [row for row in marked if row["watched"]]
