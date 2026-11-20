"""Decide which newly displayed aircraft should raise an alert."""

from __future__ import annotations

from typing import Any

EMERGENCY = {"7500", "7600", "7700"}


def alert_for(aircraft: dict[str, Any], settings: dict[str, Any], watch_on: bool) -> str | None:
    squawk = str(aircraft.get("squawk") or "")
    if settings.get("emergency") and squawk in EMERGENCY:
        return "emergency"
    if settings.get("military") and aircraft.get("military"):
        return "military"
    if settings.get("watch") and watch_on:
        return "watch"
    return None


def entering_alerts(
    previous_ids: set[str],
    aircraft: list[dict[str, Any]],
    settings: dict[str, Any],
    watch_on: bool,
) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for row in aircraft:
        ident = str(row.get("id") or "")
        if not ident or ident in previous_ids:
            continue
        reason = alert_for(row, settings, watch_on)
        if reason:
            found.append({"id": ident, "callsign": str(row.get("callsign") or ident), "reason": reason})
    return found
