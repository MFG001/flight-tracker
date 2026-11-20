"""Pure helpers for feeds, motion, config, and the optional encoder."""

from __future__ import annotations

import math
import re
import urllib.parse
from copy import deepcopy
from typing import Any

# 1.0.7: signed releases come anonymously from this public repo (no token).
PUBLIC_REPO = "MFG001/flight-tracker"
PUBLIC_MANIFEST_URL = f"https://github.com/{PUBLIC_REPO}/releases/latest/download/manifest.json"

NM_PER_DEG_LAT = 60.0
LEG_SECONDS = 240.0

try:
    from classify import classify, load_hex_ranges, load_type_db
    from rings import MAX_RANGE_NM, snap_range
except ImportError:
    from server.classify import classify, load_hex_ranges, load_type_db
    from server.rings import MAX_RANGE_NM, snap_range

BACKGROUNDS = ("dark", "light", "satellite", "sectional", "scope")
UNITS = ("aviation", "imperial", "metric")
BANDS = ("all", "low", "mid", "high", "upper")
# Other names for the top band ("> 35,000 ft").
BAND_ALIASES = {"vhigh": "upper"}
BRIGHTNESS_MIN = 20
FEED_MODES = ("adsbfi", "demo", "local", "remote")
ORIENTATIONS = ("north", "track")
KEYS = ("MAP", "TFC", "WX", "MNU", "NAV", "HDG", "ALT", "BRT")

# One detent of a typical mechanical encoder is four quadrature edges.
QUADRATURE = (0, 1, -1, 0, -1, 0, 0, 1, 1, 0, 0, -1, 0, -1, 1, 0)

# Seconds per sweep revolution. 1.0.2 halves the old 4 s base rate to 8 s and
# allows up to 16 s.
SWEEP_DEFAULT_SEC = 8
SWEEP_MIN_SEC = 3
SWEEP_MAX_SEC = 16
CONFIG_SCHEMA = 3

DEFAULT_CONFIG: dict[str, Any] = {
    "schema": CONFIG_SCHEMA,
    "home": {"name": "KJFK", "lat": 40.6399, "lon": -73.7787},
    "rangeNm": 20.0,
    # Range rings drawn inside the outer (range) ring, outer ring included.
    "rings": 4,
    # Radar-screen text: clock on/off, clock style, and whether status text
    # fades out while aircraft are on the glass.
    "showClock": True,
    "clockFormat": "24h",
    "minimalText": True,
    "units": "aviation",
    "feed": {
        "mode": "adsbfi",
        "localPath": "/run/readsb/aircraft.json",
        "remoteUrl": "",
        "host": "",
        "port": 8080,
        "fallbackDemo": True,
    },
    "background": "dark",
    "weather": {"enabled": True, "opacity": 0.6, "animate": True},
    "metar": True,
    "metarStation": "KJFK",
    "orientation": "north",
    "facingDeg": 0.0,
    "altitudeBand": "all",
    "brightness": 100,
    "sweep": {"enabled": False, "periodSec": 8},
    "watch": {"enabled": False, "tails": []},
    "alerts": {"watch": False, "military": False, "emergency": False, "chime": False},
    "trails": {"enabled": False, "minutes": 5},
    "night": {"mode": "off", "fromHour": 22, "toHour": 6, "from": "2200", "to": "0600", "brightness": 25},
    "icons": "maverick",
    "updates": {
        "url": PUBLIC_MANIFEST_URL,
        "repo": PUBLIC_REPO,
        "channel": "stable",
        "auto": False,
        "laterAt": "02:00",
        "laterTz": "America/New_York",
    },
    "gpio": {
        "enabled": False,
        "pins": {
            "MAP": 5,
            "TFC": 6,
            "WX": 16,
            "MNU": 17,
            "NAV": 22,
            "HDG": 23,
            "ALT": 24,
            "BRT": 25,
        },
        "encoder": {"clk": 12, "dt": 13, "sw": 20},
    },
    "fan": {"gpioControl": False, "gpio": 14, "onTempC": 60},
    # Panel rotation for the desktop and kiosk (wlr-randr/kanshi transform).
    # 270 turns the Waveshare 4inch DSI LCD (C) 90 degrees clockwise, which is
    # what the first Pi 4 unit needed.
    "display": {
        "rotation": 270,
        "output": "DSI-1",
        "touchDevice": "10-0014 Goodix Capacitive TouchScreen",
        "touchMatrix": False,
    },
    "wifi": {"country": "US"},
}

ROTATIONS = (0, 90, 180, 270)
RING_COUNTS = (2, 3, 4, 5, 6)
CLOCK_FORMATS = ("24h", "12h", "utc")
HHMM_RE = re.compile(r"^([01]\d|2[0-3])[0-5]\d$")


def hhmm_to_hours(text: str) -> float:
    """'2230' -> 22.5. Raises ValueError for anything but 4-digit 24-hour time."""
    if not isinstance(text, str) or not HHMM_RE.fullmatch(text.strip()):
        raise ValueError("Time must be 4 digits, 24-hour, like 2230")
    value = text.strip()
    return int(value[:2]) + int(value[2:]) / 60


def hours_to_hhmm(hours: float) -> str:
    total = int(round(float(hours) * 60)) % (24 * 60)
    return f"{total // 60:02d}{total % 60:02d}"

OUTPUT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def move_nm(lat: float, lon: float, track_deg: float, nm: float) -> tuple[float, float]:
    if nm == 0:
        return lat, lon
    rad = math.radians(track_deg % 360)
    dlat = (nm / NM_PER_DEG_LAT) * math.cos(rad)
    denom = NM_PER_DEG_LAT * max(0.01, math.cos(math.radians(lat)))
    dlon = (nm / denom) * math.sin(rad)
    return lat + dlat, lon + dlon


def position_at(spec: dict[str, Any], elapsed: float) -> tuple[float, float, float]:
    """Fly a straight leg, then the reciprocal, and repeat. Elapsed 0 is the sample fix."""
    lat = float(spec["lat"])
    lon = float(spec["lon"])
    track = float(spec.get("track") or 0) % 360
    gs = spec.get("gs") or 0
    try:
        gs = float(gs)
    except (TypeError, ValueError):
        gs = 0.0
    if gs <= 0 or spec.get("alt_baro") == "ground":
        return lat, lon, track
    cycle = LEG_SECONDS * 2
    t = elapsed % cycle
    if t <= LEG_SECONDS:
        lat2, lon2 = move_nm(lat, lon, track, gs * (t / 3600.0))
        return lat2, lon2, track
    lat2, lon2 = move_nm(lat, lon, track, gs * (LEG_SECONDS / 3600.0))
    back = (track + 180.0) % 360
    lat3, lon3 = move_nm(lat2, lon2, back, gs * ((t - LEG_SECONDS) / 3600.0))
    return lat3, lon3, back


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def _text(value: Any, limit: int = 12) -> str:
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:limit]


_TYPE_CACHE: dict[str, str] | None = None
_HEX_CACHE: list[tuple[int, int]] | None = None


def _type_table() -> dict[str, str]:
    global _TYPE_CACHE
    if _TYPE_CACHE is None:
        _TYPE_CACHE = load_type_db()
    return _TYPE_CACHE


def _hex_table() -> list[tuple[int, int]]:
    global _HEX_CACHE
    if _HEX_CACHE is None:
        _HEX_CACHE = load_hex_ranges()
    return _HEX_CACHE


_EMERGENCY_SQUAWKS = {"7500", "7600", "7700"}
_EMERGENCY_NONE = {"", "none", "0", "false", "null"}


def is_emergency(squawk: str | None, flag: Any) -> bool:
    """7500, 7600, 7700, or a readsb ADS-B emergency value other than none."""
    if (squawk or "") in _EMERGENCY_SQUAWKS:
        return True
    if flag is None or flag is False:
        return False
    if isinstance(flag, (int, float)) and int(flag) == 0:
        return False
    return str(flag).strip().lower() not in _EMERGENCY_NONE


def normalize_aircraft(raw: Any) -> list[dict[str, Any]]:
    """Accept a readsb/dump1090 aircraft.json document or a bare list."""
    rows: Any
    if isinstance(raw, dict):
        rows = raw.get("aircraft", [])
    elif isinstance(raw, list):
        rows = raw
    else:
        return []
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        lat = _number(row.get("lat"))
        lon = _number(row.get("lon"))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        alt_raw = row.get("alt_baro", row.get("altitude"))
        ground = alt_raw == "ground"
        alt = None if ground else _number(alt_raw)
        if alt is None and not ground:
            alt = _number(row.get("alt_geom"))
        track = _number(row.get("track"))
        if track is None:
            track = _number(row.get("true_heading"))
        if track is None:
            track = _number(row.get("mag_heading"))
        if track is None:
            track = _number(row.get("nav_heading"))
        if track is not None:
            track = track % 360
        gs = _number(row.get("gs"))
        vs = _number(row.get("baro_rate"))
        if vs is None:
            vs = _number(row.get("geom_rate"))
        hex_id = _text(row.get("hex") or row.get("icao"), 8).upper().lstrip("~")
        callsign = _text(row.get("flight") or row.get("callsign"), 8).upper()
        if not callsign:
            callsign = hex_id or "----"
        ident = hex_id or callsign
        seen = _number(row.get("seen_pos"))
        if seen is None:
            seen = _number(row.get("seen"))
        squawk = _text(row.get("squawk"), 4)
        emergency = is_emergency(squawk, row.get("emergency"))
        category = _text(row.get("category"), 3).upper()
        registration = _text(row.get("r") or row.get("registration"), 10).upper()
        type_code = _text(row.get("t") or row.get("type"), 8).upper()
        flags = row.get("dbFlags", 0)
        try:
            db_flags = int(flags)
        except (TypeError, ValueError):
            db_flags = 0
        kind = classify(category or None, db_flags, hex_id or None, type_code or None, _type_table(), _hex_table())
        out.append(
            {
                "id": ident,
                "hex": hex_id or None,
                "callsign": callsign,
                "registration": registration or None,
                "typeCode": type_code or None,
                "lat": lat,
                "lon": lon,
                "altFt": 0 if ground else alt,
                "ground": ground,
                "gsKt": gs,
                "track": track,
                "vsFpm": vs,
                "squawk": squawk or None,
                "emergency": emergency,
                "category": category or None,
                "kind": kind["kind"],
                "mark": kind["mark"],
                "military": kind["military"],
                "seenSec": seen,
            }
        )
    return out


def demo_document(sample: list[dict[str, Any]], elapsed: float) -> dict[str, Any]:
    aircraft = []
    for spec in sample:
        lat, lon, track = position_at(spec, elapsed)
        row = dict(spec)
        row["lat"] = lat
        row["lon"] = lon
        row["track"] = track
        row["seen_pos"] = 0.4
        aircraft.append(row)
    return {"now": elapsed, "messages": 100 + int(elapsed * 8), "aircraft": aircraft}


def valid_tile(z: int, x: int, y: int, min_z: int, max_z: int) -> bool:
    if z < min_z or z > max_z or z < 0 or z > 22:
        return False
    span = 2**z
    return 0 <= x < span and 0 <= y < span


def valid_frame_id(frame: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9]{4,64}", frame))


def valid_feed_url(url: str) -> bool:
    if url == "":
        return True
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    if parsed.username or parsed.password:
        return False
    return True


def resolved_feed_url(feed: dict[str, Any]) -> str:
    """Prefer an explicit JSON URL, otherwise host and port on the readsb path."""
    url = str(feed.get("remoteUrl") or "").strip()
    if url:
        return url
    host = str(feed.get("host") or "").strip()
    if not host:
        return ""
    try:
        port = int(feed.get("port") or 80)
    except (TypeError, ValueError):
        port = 80
    return f"http://{host}:{port}/data/aircraft.json"


def backlight_value(percent: float) -> int:
    """Map a 0–100 setting to the Waveshare terminal range.

    The 4inch DSI LCD (C) wiki says ``echo N | sudo tee
    /sys/class/backlight/*/brightness`` where N is 0 (darkest) through
    255 (brightest). It does not define a curve, so this is linear.
    """
    clamped = max(0.0, min(100.0, percent))
    return int(round(clamped / 100.0 * 255))


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _pin(value: Any) -> int | None:
    try:
        pin = int(value)
    except (TypeError, ValueError):
        return None
    if 2 <= pin <= 27:
        return pin
    return None


def sanitize_config(payload: Any) -> tuple[dict[str, Any], list[str]]:
    """Return a config object and a list of human-readable errors."""
    if not isinstance(payload, dict):
        return deepcopy(DEFAULT_CONFIG), ["Configuration must be a JSON object."]
    cfg = deepcopy(DEFAULT_CONFIG)
    errors: list[str] = []
    # Keep the migration level so a save does not make old steps run again.
    schema = payload.get("schema")
    if isinstance(schema, int) and not isinstance(schema, bool) and 0 <= schema <= 1000:
        cfg["schema"] = schema

    home = payload.get("home", {})
    if not isinstance(home, dict):
        errors.append("Home must be an object.")
    else:
        name = _text(home.get("name", cfg["home"]["name"]), 12) or "HOME"
        lat = _number(home.get("lat"))
        lon = _number(home.get("lon"))
        if lat is None or not -90 <= lat <= 90:
            errors.append("Home latitude must be between -90 and 90.")
        else:
            cfg["home"]["lat"] = lat
        if lon is None or not -180 <= lon <= 180:
            errors.append("Home longitude must be between -180 and 180.")
        else:
            cfg["home"]["lon"] = lon
        cfg["home"]["name"] = name

    rng = _number(payload.get("rangeNm"))
    if rng is None:
        errors.append("Range must be a number of nautical miles.")
    else:
        cfg["rangeNm"] = snap_range(_clamp(rng, 2, MAX_RANGE_NM))

    rings = payload.get("rings", cfg["rings"])
    try:
        ring_count = int(rings)
    except (TypeError, ValueError):
        ring_count = -1
    if ring_count in RING_COUNTS and not isinstance(rings, bool):
        cfg["rings"] = ring_count
    else:
        errors.append("Number of range rings must be 2 to 6.")

    cfg["showClock"] = bool(payload.get("showClock", True))
    cfg["minimalText"] = bool(payload.get("minimalText", True))
    clock_format = payload.get("clockFormat", cfg["clockFormat"])
    if clock_format in CLOCK_FORMATS:
        cfg["clockFormat"] = clock_format
    else:
        errors.append("Clock format must be 24h, 12h, or utc.")

    units = payload.get("units", cfg["units"])
    if units not in UNITS:
        errors.append("Units must be aviation, imperial, or metric.")
    else:
        cfg["units"] = units

    feed = payload.get("feed", {})
    if not isinstance(feed, dict):
        errors.append("Feed must be an object.")
    else:
        mode = feed.get("mode", cfg["feed"]["mode"])
        if mode not in FEED_MODES:
            errors.append("Feed mode must be adsbfi, demo, local, or remote.")
        else:
            cfg["feed"]["mode"] = mode
        local_path = feed.get("localPath", cfg["feed"]["localPath"])
        if not isinstance(local_path, str) or not local_path.startswith("/") or len(local_path) > 240:
            errors.append("Local feed path must be an absolute path.")
        else:
            cfg["feed"]["localPath"] = local_path
        remote = feed.get("remoteUrl", "")
        if not isinstance(remote, str) or len(remote) > 400 or not valid_feed_url(remote.strip()):
            errors.append("Remote feed URL must be http or https.")
        else:
            cfg["feed"]["remoteUrl"] = remote.strip()
        cfg["feed"]["fallbackDemo"] = bool(feed.get("fallbackDemo", True))
        host = feed.get("host", "")
        if not isinstance(host, str) or len(host) > 253 or any(ch.isspace() for ch in host):
            errors.append("Feed host must be a hostname or IP address.")
        else:
            cfg["feed"]["host"] = host.strip()
        try:
            port = int(feed.get("port", cfg["feed"]["port"]))
        except (TypeError, ValueError):
            port = 0
        if not 1 <= port <= 65535:
            errors.append("Feed port must be between 1 and 65535.")
        else:
            cfg["feed"]["port"] = port

    background = payload.get("background", cfg["background"])
    if background not in BACKGROUNDS:
        errors.append("Unknown background.")
    else:
        cfg["background"] = background

    weather = payload.get("weather", {})
    if not isinstance(weather, dict):
        errors.append("Weather must be an object.")
    else:
        cfg["weather"]["enabled"] = bool(weather.get("enabled", True))
        opacity = _number(weather.get("opacity", cfg["weather"]["opacity"]))
        if opacity is None:
            errors.append("Weather opacity must be a number.")
        else:
            cfg["weather"]["opacity"] = round(_clamp(opacity, 0.1, 1.0) * 10) / 10
        cfg["weather"]["animate"] = bool(weather.get("animate", True))

    cfg["metar"] = bool(payload.get("metar", True))
    station = str(payload.get("metarStation", "") or "").strip().upper()
    if station and not re.fullmatch(r"[A-Z0-9]{3,4}", station):
        errors.append("METAR station must be a 3 or 4 character code.")
    else:
        cfg["metarStation"] = station

    orientation = payload.get("orientation", cfg["orientation"])
    if orientation not in ORIENTATIONS:
        errors.append("Orientation must be north or track.")
    else:
        cfg["orientation"] = orientation

    facing = _number(payload.get("facingDeg", 0))
    if facing is None:
        errors.append("Facing must be a number of degrees.")
    else:
        cfg["facingDeg"] = facing % 360

    band = payload.get("altitudeBand", "all")
    band = BAND_ALIASES.get(band, band) if isinstance(band, str) else band
    if band not in BANDS:
        errors.append("Unknown altitude filter.")
    else:
        cfg["altitudeBand"] = band

    bright = _number(payload.get("brightness", 100))
    if bright is None:
        errors.append("Brightness must be a number.")
    else:
        # Daytime brightness, set on the setup page (1.0.3; it was the BRT key).
        # 20% floor so the glass can never be turned fully dark by mistake.
        cfg["brightness"] = int(round(_clamp(bright, BRIGHTNESS_MIN, 100)))

    sweep = payload.get("sweep", {})
    if not isinstance(sweep, dict):
        errors.append("Sweep settings must be an object.")
    else:
        cfg["sweep"]["enabled"] = bool(sweep.get("enabled", False))
        period = _number(sweep.get("periodSec", SWEEP_DEFAULT_SEC))
        if period is None:
            errors.append("Sweep speed must be a number of seconds.")
        else:
            cfg["sweep"]["periodSec"] = _clamp(period, SWEEP_MIN_SEC, SWEEP_MAX_SEC)

    gpio = payload.get("gpio", {})
    if not isinstance(gpio, dict):
        errors.append("GPIO settings must be an object.")
    else:
        cfg["gpio"]["enabled"] = bool(gpio.get("enabled", False))
        pins_in = gpio.get("pins", {})
        enc_in = gpio.get("encoder", {})
        used: dict[int, str] = {}
        if not isinstance(pins_in, dict) or not isinstance(enc_in, dict):
            errors.append("GPIO pins must be objects.")
        else:
            for key in KEYS:
                pin = _pin(pins_in.get(key, cfg["gpio"]["pins"][key]))
                if pin is None:
                    errors.append(f"GPIO pin for {key} must be a BCM number from 2 to 27.")
                    continue
                if pin in used:
                    errors.append(f"GPIO {pin} is used for both {used[pin]} and {key}.")
                used[pin] = key
                cfg["gpio"]["pins"][key] = pin
            for name in ("clk", "dt", "sw"):
                pin = _pin(enc_in.get(name, cfg["gpio"]["encoder"][name]))
                if pin is None:
                    errors.append(f"Encoder {name} must be a BCM number from 2 to 27.")
                    continue
                if pin in used:
                    errors.append(f"GPIO {pin} is used for both {used[pin]} and encoder {name}.")
                used[pin] = f"encoder {name}"
                cfg["gpio"]["encoder"][name] = pin

    fan = payload.get("fan", {})
    if isinstance(fan, dict):
        cfg["fan"]["gpioControl"] = bool(fan.get("gpioControl", False))
        pin = _pin(fan.get("gpio", cfg["fan"]["gpio"]))
        if pin is None:
            errors.append("Fan GPIO must be a BCM number from 2 to 27.")
        else:
            cfg["fan"]["gpio"] = pin
        temp = _number(fan.get("onTempC", cfg["fan"]["onTempC"]))
        if temp is None:
            errors.append("Fan temperature must be a number.")
        else:
            cfg["fan"]["onTempC"] = int(round(_clamp(temp, 40, 85)))
    else:
        errors.append("Fan settings must be an object.")

    updates = payload.get("updates", {})
    if not isinstance(updates, dict):
        errors.append("Update settings must be an object.")
    else:
        url = str(updates.get("url") or cfg["updates"]["url"]).strip()
        repo = str(updates.get("repo") or "").strip()
        # 1.0.7: the old private releases repo moves to the public, tokenless one.
        if "/flight-tracker-updates/" in url or url.rstrip("/").endswith("/flight-tracker-updates"):
            url, repo = PUBLIC_MANIFEST_URL, PUBLIC_REPO
        if url == PUBLIC_MANIFEST_URL and not repo:
            repo = PUBLIC_REPO
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            errors.append("Update URL must be HTTPS and must not contain credentials.")
        else:
            cfg["updates"]["url"] = url
        if repo and not re.fullmatch(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}", repo):
            errors.append("Update repo must look like OWNER/NAME.")
        else:
            cfg["updates"]["repo"] = repo
        channel = str(updates.get("channel") or "stable")
        if channel != "stable":
            errors.append("Update channel must be stable.")
        cfg["updates"]["channel"] = "stable"
        cfg["updates"]["auto"] = bool(updates.get("auto", False))
        # 1.0.7: "Install later at" on the Software card (local HH:MM).
        later = str(updates.get("laterAt", cfg["updates"].get("laterAt", "02:00")) or "02:00").strip()
        if re.fullmatch(r"([01][0-9]|2[0-3])[0-5][0-9]", later):
            later = f"{later[:2]}:{later[2:]}"
        if re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", later):
            cfg["updates"]["laterAt"] = later
        else:
            errors.append("Install later at must be a time like 02:00.")
        # The zone the Later time is in (Eastern by default), not the Pi clock zone.
        zone_name = str(updates.get("laterTz", cfg["updates"].get("laterTz", "America/New_York")) or "America/New_York").strip()
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(zone_name)
            cfg["updates"]["laterTz"] = zone_name
        except Exception:  # unknown zone or no tzdata
            errors.append("Install later time zone must be a name like America/New_York.")

    watch = payload.get("watch", {})
    if not isinstance(watch, dict):
        errors.append("Watch list must be an object.")
    else:
        try:
            from watchlist import canonical_watch
        except ImportError:
            from server.watchlist import canonical_watch
        cfg["watch"]["enabled"] = bool(watch.get("enabled", False))
        try:
            from watchlist import parse_watch_text
        except ImportError:
            from server.watchlist import parse_watch_text
        tails_in = watch.get("tails", [])
        tails: list[str] = []
        if isinstance(tails_in, str):
            tails, _ = parse_watch_text(tails_in)
        elif isinstance(tails_in, list):
            # Each list item may itself hold several entries ("N1, N2").
            for item in tails_in:
                for token in parse_watch_text(str(item))[0]:
                    if token not in tails:
                        tails.append(token)
            tails = tails[:40]
        cfg["watch"]["tails"] = tails

    alerts = payload.get("alerts", {})
    if isinstance(alerts, dict):
        for key in ("watch", "military", "emergency", "chime"):
            cfg["alerts"][key] = bool(alerts.get(key, False))
    else:
        errors.append("Alert settings must be an object.")

    trails = payload.get("trails", {})
    if isinstance(trails, dict):
        cfg["trails"]["enabled"] = bool(trails.get("enabled", False))
        minutes = _number(trails.get("minutes", 5))
        if minutes is None:
            errors.append("Trail length must be a number of minutes.")
        else:
            cfg["trails"]["minutes"] = int(round(_clamp(minutes, 1, 10)))
    else:
        errors.append("Trail settings must be an object.")

    night = payload.get("night", {})
    if isinstance(night, dict):
        mode = str(night.get("mode", "off"))
        cfg["night"]["mode"] = mode if mode in ("off", "sun", "schedule") else "off"
        level = _number(night.get("brightness", 25))
        # 1.0.2 stores HHMM text ("from"/"to"); fromHour/toHour stay as whole
        # hours so a rollback to 1.0.1 still reads a sensible schedule.
        for text_key, hour_key, fallback in (("from", "fromHour", 22), ("to", "toHour", 6)):
            raw = night.get(text_key)
            if raw is not None and str(raw).strip() != "":
                try:
                    hours = hhmm_to_hours(str(raw))
                except ValueError:
                    errors.append(f"Night {'start' if text_key == 'from' else 'end'} must be 4 digits, 24-hour, like 2200.")
                    continue
                cfg["night"][text_key] = str(raw).strip()
                cfg["night"][hour_key] = int(hours)
            else:
                number = _number(night.get(hour_key, fallback))
                if number is not None:
                    whole = int(round(_clamp(number, 0, 23)))
                    cfg["night"][hour_key] = whole
                    cfg["night"][text_key] = hours_to_hhmm(whole)
        if level is not None:
            cfg["night"]["brightness"] = int(round(_clamp(level, 5, 80)))
    else:
        errors.append("Night settings must be an object.")

    icons = str(payload.get("icons", "maverick"))
    if icons == "silhouette":
        cfg["icons"] = "linecut"
    elif icons in ("classic", "planform", "compact", "linecut", "maverick"):
        cfg["icons"] = icons
    else:
        cfg["icons"] = "maverick"

    display = payload.get("display", {})
    if isinstance(display, dict):
        try:
            rotation = int(display.get("rotation", cfg["display"]["rotation"]))
        except (TypeError, ValueError):
            rotation = -1
        if rotation in ROTATIONS:
            cfg["display"]["rotation"] = rotation
        else:
            errors.append("Display rotation must be 0, 90, 180, or 270.")
        output = str(display.get("output", cfg["display"]["output"]) or "")
        if OUTPUT_RE.fullmatch(output):
            cfg["display"]["output"] = output
        else:
            errors.append("Display output must look like DSI-1.")
        touch = str(display.get("touchDevice", cfg["display"]["touchDevice"]) or "")
        if len(touch) <= 80 and all(ch.isprintable() and ch not in '<>&"' for ch in touch):
            cfg["display"]["touchDevice"] = touch
        else:
            errors.append("Touch device name has characters that are not allowed.")
        cfg["display"]["touchMatrix"] = bool(display.get("touchMatrix", False))
    else:
        errors.append("Display settings must be an object.")

    wifi = payload.get("wifi", {})
    if isinstance(wifi, dict):
        country = str(wifi.get("country", cfg["wifi"]["country"]) or "").strip().upper()
        if COUNTRY_RE.fullmatch(country):
            cfg["wifi"]["country"] = country
        else:
            errors.append("Wi-Fi country must be a two-letter code such as US.")
    else:
        errors.append("Wi-Fi settings must be an object.")

    return cfg, errors


class QuadratureDecoder:
    """Full-step quadrature. Four edges in one direction make one detent."""

    def __init__(self) -> None:
        self.state = 0
        self.acc = 0

    def update(self, clk: int, dt: int) -> int:
        current = ((int(clk) & 1) << 1) | (int(dt) & 1)
        delta = QUADRATURE[(self.state << 2) | current]
        self.state = current
        self.acc += delta
        if self.acc >= 4:
            self.acc -= 4
            return 1
        if self.acc <= -4:
            self.acc += 4
            return -1
        return 0
