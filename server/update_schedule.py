"""Update prompt and "install later" schedule (1.0.7 prototype).

When a newer signed release is found, the round screen asks UPDATE NOW or
LATER. LATER (or no answer within 5 minutes) books the install for the next
"Install later at" time from the Software card. With auto-update on, the
install is booked for that time without asking.

The schedule lives in ``update-schedule.json`` next to config.json:

    {"version": "1.0.7", "atEpoch": 1795240800, "label": "2:00 AM",
     "state": "pending" | "cancelled" | "attempted", "source": "later" |
     "timeout" | "auto", "quietUntil": <epoch>}

Only one version is tracked at a time. The prompt shows again for a version
only after ``quietUntil`` (the next background check) once a schedule for it
was cancelled or attempted, so the screen never nags.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, time as dtime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None  # type: ignore[assignment]
    ZoneInfoNotFoundError = Exception  # type: ignore[assignment,misc]

DEFAULT_LATER_AT = "02:00"
# The default "Install later at" time is Eastern, whatever the Pi clock zone is
# (Raspberry Pi OS often runs on UTC).
DEFAULT_LATER_TZ = "America/New_York"
ZONE_SHORT = {
    "America/New_York": "ET", "America/Detroit": "ET", "America/Chicago": "CT",
    "America/Denver": "MT", "America/Phoenix": "MST", "America/Los_Angeles": "PT",
    "America/Anchorage": "AKT", "Pacific/Honolulu": "HT", "UTC": "UTC", "Etc/UTC": "UTC",
}
CHECK_EVERY_SEC = 6 * 3600
FIRST_CHECK_AFTER_SEC = 90
PROMPT_TIMEOUT_SEC = 300
# In-process background checks (boot+90s and every 6 h) may show the
# on-glass prompt, so they only run during waking hours in laterTz.
# The systemd timer does the daily 09:00 check. Manual CHECK NOW is always allowed.
PROMPT_CHECK_START_HOUR = 9
PROMPT_CHECK_END_HOUR = 21
HHMM = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")


def valid_later_at(value: Any) -> str | None:
    text = str(value or "").strip()
    if re.fullmatch(r"([01][0-9]|2[0-3])[0-5][0-9]", text):
        text = f"{text[:2]}:{text[2:]}"
    return text if HHMM.fullmatch(text) else None


def valid_tz(name: Any) -> str | None:
    text = str(name or "").strip()
    if not text or ZoneInfo is None:
        return None
    try:
        ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None
    return text


def zone(name: Any) -> tzinfo:
    """The schedule's zone; falls back to the default, then to UTC if tzdata is missing."""
    for candidate in (valid_tz(name), valid_tz(DEFAULT_LATER_TZ)):
        if candidate:
            return ZoneInfo(candidate)  # type: ignore[misc]
    return timezone.utc


def zone_short(name: Any, when: datetime | None = None) -> str:
    key = valid_tz(name) or DEFAULT_LATER_TZ
    if key in ZONE_SHORT:
        return ZONE_SHORT[key]
    return (when or datetime.now(zone(key))).astimezone(zone(key)).tzname() or key



def prompt_check_open(now: datetime | None = None, zone_name: str = DEFAULT_LATER_TZ) -> bool:
    """True when a background check may show the Update available prompt."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    hour = current.astimezone(zone(zone_name)).hour
    return PROMPT_CHECK_START_HOUR <= hour < PROMPT_CHECK_END_HOUR


def next_occurrence(later_at: str, now: datetime, tz: tzinfo | None = None) -> datetime:
    """The next HH:MM wall-clock time in ``tz`` strictly after ``now``.

    ``now`` may be naive (taken as the system's local time) or aware; the
    answer is aware, in ``tz``. Built from the calendar date so DST days are
    right (02:00 on the spring-forward day does not exist in New York and
    resolves to 03:00 EDT, the moment the clocks jump).
    """
    tz = tz or zone(DEFAULT_LATER_TZ)
    hhmm = valid_later_at(later_at) or DEFAULT_LATER_AT
    hour, minute = int(hhmm[:2]), int(hhmm[3:])
    current = (now if now.tzinfo else now.astimezone()).astimezone(tz)
    day = current.date()
    for _ in range(3):
        at = datetime.combine(day, dtime(hour, minute), tzinfo=tz)
        # Normalise through UTC: turns a skipped wall time into a real instant.
        at = at.astimezone(timezone.utc).astimezone(tz)
        if at > current:
            return at
        day += timedelta(days=1)
    return at


def time_label(hhmm: str, clock_format: str = "24h", zone_name: str = "") -> str:
    """'2:00 AM ET' for 12-hour clocks, '02:00 ET' otherwise."""
    hhmm = valid_later_at(hhmm) or DEFAULT_LATER_AT
    hour, minute = int(hhmm[:2]), int(hhmm[3:])
    if clock_format == "12h":
        suffix = "AM" if hour < 12 else "PM"
        text = f"{(hour % 12) or 12}:{minute:02d} {suffix}"
    else:
        text = f"{hour:02d}:{minute:02d}"
    return f"{text} {zone_short(zone_name)}" if zone_name else text


def day_label(at: datetime, now: datetime) -> str:
    current = (now if now.tzinfo else now.astimezone()).astimezone(at.tzinfo)
    return "today" if at.date() == current.date() else "tomorrow"


def _path(config_path: Path) -> Path:
    return config_path.with_name("update-schedule.json")


def read_schedule(config_path: Path) -> dict[str, Any]:
    path = _path(config_path)
    if not path.is_file():
        return {}
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


def write_schedule(config_path: Path, body: dict[str, Any]) -> None:
    path = _path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def clear_schedule(config_path: Path) -> None:
    try:
        _path(config_path).unlink()
    except FileNotFoundError:
        pass


def summary_line(notes: str, limit: int = 90) -> str:
    """First sentence of the release notes, cut at a word boundary."""
    text = " ".join(str(notes or "").split())
    if not text:
        return ""
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    if len(first) <= limit:
        return first
    cut = first[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "…"


def prompt_visible(
    *,
    available: bool,
    latest: str,
    token_set: bool,
    auto: bool,
    installing: bool,
    schedule: dict[str, Any],
    now_epoch: float,
) -> bool:
    """Should the round screen ask UPDATE NOW / LATER for ``latest``?"""
    if not available or not latest or not token_set or auto or installing:
        return False
    if schedule.get("version") != latest:
        return True
    if schedule.get("state") == "pending":
        return False
    return now_epoch >= float(schedule.get("quietUntil") or 0)


def booking(version: str, later_at: str, clock_format: str, source: str, now: datetime, zone_name: str = DEFAULT_LATER_TZ) -> dict[str, Any]:
    at = next_occurrence(later_at, now, zone(zone_name))
    return {
        "version": version,
        "atEpoch": at.timestamp(),
        "atLocal": at.isoformat(timespec="minutes"),
        "zone": valid_tz(zone_name) or DEFAULT_LATER_TZ,
        "label": time_label(later_at, clock_format, zone_name or DEFAULT_LATER_TZ),
        "day": day_label(at, now),
        "state": "pending",
        "source": source,
        "bookedEpoch": time.time(),
    }
