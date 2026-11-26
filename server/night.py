"""Night-dim location, solar window, and status used by the setup page and the glass."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

try:
    from solar import is_night, schedule_night, solar_hours
    from zcta import lookup_zip, normalize_zip, zip_error
except ImportError:
    from server.solar import is_night, schedule_night, solar_hours
    from server.zcta import lookup_zip, normalize_zip, zip_error


ENTER_LOCATION = "Enter a US ZIP code or exact coordinates to use sunrise/sunset."
ENTER_ZIP = "Enter your ZIP code to use sunrise/sunset."
ENTER_COORDS = "Enter latitude and longitude to use sunrise/sunset."
TZ_NOTE = "These times use this device's clock timezone, which may not match the location you entered."


def format_clock(hours: float | None) -> str | None:
    if hours is None:
        return None
    total = int(round(float(hours) * 60)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _number(value: Any) -> float | None:
    if value is None or value is False or value is True or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _valid_coords(lat: float, lon: float) -> bool:
    return -90 <= lat <= 90 and -180 <= lon <= 180


def location_kind(night: dict[str, Any]) -> str:
    kind = str(night.get("loc") or night.get("locMode") or "zip").strip().lower()
    return "ll" if kind in ("ll", "coords", "latlon", "lat/lon") else "zip"


def resolve_night_location(night: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str]:
    """Return (location, error). Location is None when sun mode cannot use it."""
    night = night or {}
    kind = location_kind(night)
    if kind == "zip":
        found = lookup_zip(night.get("zip"))
        if found:
            return ({"kind": "zip", **found}, "")
        return (None, zip_error(night.get("zip")) or ENTER_ZIP)
    lat = _number(night.get("lat"))
    lon = _number(night.get("lon"))
    if lat is None or lon is None:
        return (None, ENTER_COORDS)
    if not _valid_coords(lat, lon):
        return (None, "Latitude must be between -90 and 90, and longitude between -180 and 180.")
    lat_s = f"{lat:.4f}"
    lon_s = f"{lon:.4f}"
    label = f"{lat_s}, {lon_s}"
    return ({"kind": "ll", "zip": normalize_zip(night.get("zip")), "lat": lat, "lon": lon, "label": label}, "")


def timezone_note(lon: float, tz_hours: float) -> str:
    expected = lon / 15.0
    diff = (tz_hours - expected + 12) % 24 - 12
    return TZ_NOTE if abs(diff) >= 3 else ""


def _events_on(lat: float, lon: float, day, tz_hours: float) -> tuple[float, float] | None:
    return solar_hours(lat, lon, day, tz_hours)


def tonight_window(lat: float, lon: float, when: datetime) -> dict[str, Any]:
    """Sunset that starts the current or next night, and the sunrise that ends it."""
    local = when.astimezone() if when.tzinfo else when
    offset = local.utcoffset()
    tz_hours = 0.0 if offset is None else offset.total_seconds() / 3600
    hour = local.hour + local.minute / 60 + local.second / 3600
    today = _events_on(lat, lon, local.date(), tz_hours)
    if today is None:
        return {
            "sunrise": None,
            "sunset": None,
            "sunriseAt": None,
            "sunsetAt": None,
            "detail": "Sunrise and sunset cannot be calculated at this location on this date (for example, polar day or night).",
        }
    rise, sett = today
    if hour >= sett:
        nxt = _events_on(lat, lon, (local + timedelta(days=1)).date(), tz_hours)
        dawn = nxt[0] if nxt else rise
        dusk = sett
    elif hour < rise:
        prev = _events_on(lat, lon, (local - timedelta(days=1)).date(), tz_hours)
        dusk = prev[1] if prev else sett
        dawn = rise
    else:
        nxt = _events_on(lat, lon, (local + timedelta(days=1)).date(), tz_hours)
        dusk = sett
        dawn = nxt[0] if nxt else rise
    return {
        "sunrise": round(dawn, 4),
        "sunset": round(dusk, 4),
        "sunriseAt": format_clock(dawn),
        "sunsetAt": format_clock(dusk),
        "detail": "",
    }


def _custom_hours(night: dict[str, Any]) -> tuple[float, float]:
    try:
        from logic import hhmm_to_hours
    except ImportError:
        from server.logic import hhmm_to_hours

    def one(text_key: str, hour_key: str, fallback: float) -> float:
        raw = night.get(text_key)
        if raw is not None and str(raw).strip() != "":
            try:
                return hhmm_to_hours(str(raw))
            except ValueError:
                pass
        try:
            return float(night.get(hour_key) if night.get(hour_key) is not None else fallback)
        except (TypeError, ValueError):
            return fallback

    return one("from", "fromHour", 22), one("to", "toHour", 6)


def solar_preview(zip_code: str = "", lat: Any = None, lon: Any = None, when: datetime | None = None) -> dict[str, Any]:
    """Preview times for a candidate location without reading or writing config."""
    night: dict[str, Any]
    if str(zip_code or "").strip() and lat is None and lon is None:
        night = {"loc": "zip", "zip": zip_code}
    else:
        night = {"loc": "ll", "lat": lat, "lon": lon, "zip": zip_code}
    # If a ZIP was provided alone, prefer ZIP even when lat/lon query keys exist as empty strings.
    if str(zip_code or "").strip() and _number(lat) is None and _number(lon) is None:
        night = {"loc": "zip", "zip": zip_code}
    loc, error = resolve_night_location(night)
    if loc is None:
        return {"ok": False, "detail": error}
    moment = when or datetime.now().astimezone()
    window = tonight_window(float(loc["lat"]), float(loc["lon"]), moment)
    offset = moment.astimezone().utcoffset() if moment.tzinfo else moment.utcoffset()
    tz_hours = 0.0 if offset is None else offset.total_seconds() / 3600
    detail = window["detail"]
    return {
        "ok": not detail,
        "kind": loc["kind"],
        "zip": loc.get("zip") or "",
        "lat": loc["lat"],
        "lon": loc["lon"],
        "label": loc["label"],
        "sunrise": window["sunrise"],
        "sunset": window["sunset"],
        "sunriseAt": window["sunriseAt"],
        "sunsetAt": window["sunsetAt"],
        "tzNote": timezone_note(float(loc["lon"]), tz_hours),
        "detail": detail,
    }


def compute_night_status(cfg: dict[str, Any], when: datetime | None = None) -> dict[str, Any]:
    """Night flag, times, and location for a config snapshot. Never raises on a missing ZIP."""
    moment = when or datetime.now().astimezone()
    local = moment.astimezone() if moment.tzinfo else moment
    offset = local.utcoffset()
    tz_hours = 0.0 if offset is None else offset.total_seconds() / 3600
    hour = local.hour + local.minute / 60 + local.second / 3600
    night = cfg.get("night") if isinstance(cfg.get("night"), dict) else {}
    mode = str(night.get("mode") or "off")
    start, end = _custom_hours(night)
    brightness = int(night.get("brightness") or 25)
    loc, loc_error = resolve_night_location(night)
    status: dict[str, Any] = {
        "mode": mode,
        "night": False,
        "brightness": brightness,
        "sunrise": None,
        "sunset": None,
        "sunriseAt": None,
        "sunsetAt": None,
        "location": loc,
        "needsLocation": False,
        "usingScheduleFallback": False,
        "tzNote": "",
        "detail": "",
        "fromAt": format_clock(start),
        "toAt": format_clock(end),
    }
    if mode == "off":
        return status
    if mode == "sun":
        if loc is None:
            status["needsLocation"] = True
            status["usingScheduleFallback"] = True
            status["night"] = schedule_night(hour, start, end)
            status["detail"] = loc_error or ENTER_LOCATION
            return status
        window = tonight_window(float(loc["lat"]), float(loc["lon"]), local)
        status.update({k: window[k] for k in ("sunrise", "sunset", "sunriseAt", "sunsetAt")})
        status["tzNote"] = timezone_note(float(loc["lon"]), tz_hours)
        if window["detail"]:
            # Polar / uncomputable: keep the unit safe on the saved hours.
            status["usingScheduleFallback"] = True
            status["night"] = schedule_night(hour, start, end)
            status["detail"] = window["detail"]
            return status
        flag = is_night(float(loc["lat"]), float(loc["lon"]), local)
        status["night"] = bool(flag)
        status["detail"] = ""
        return status
    if mode == "schedule":
        status["night"] = schedule_night(hour, start, end)
    return status
