"""Offline sunrise and sunset for the home location.

The hour-angle method is the public NOAA approximation (zenith 90.833 degrees).
Times are local hours in the timezone of the supplied offset.
"""

from __future__ import annotations

import math
from datetime import date, datetime


def solar_hours(lat: float, lon: float, day: date, tz_hours: float) -> tuple[float, float] | None:
    n = day.timetuple().tm_yday
    lng_hour = lon / 15.0

    def side(rising: bool) -> float | None:
        t = n + ((6 if rising else 18) - lng_hour) / 24.0
        m = (0.9856 * t) - 3.289
        mr = math.radians(m)
        el = (m + (1.916 * math.sin(mr)) + (0.020 * math.sin(2 * mr)) + 282.634) % 360
        lr = math.radians(el)
        ra = math.degrees(math.atan2(0.91764 * math.sin(lr), math.cos(lr))) % 360
        l_quad = math.floor(el / 90) * 90
        ra_quad = math.floor(ra / 90) * 90
        ra = (ra + (l_quad - ra_quad)) / 15
        sin_dec = 0.39782 * math.sin(lr)
        cos_dec = math.cos(math.asin(max(-1.0, min(1.0, sin_dec))))
        cos_lat = math.cos(math.radians(lat))
        if abs(cos_lat) < 1e-6 or abs(cos_dec) < 1e-6:
            return None
        cos_h = (math.cos(math.radians(90.833)) - (sin_dec * math.sin(math.radians(lat)))) / (cos_dec * cos_lat)
        if cos_h > 1 or cos_h < -1:
            return None
        if rising:
            hour = (360 - math.degrees(math.acos(cos_h))) / 15
        else:
            hour = math.degrees(math.acos(cos_h)) / 15
        local_mean = hour + ra - (0.06571 * t) - 6.622
        ut = (local_mean - lng_hour) % 24
        return (ut + tz_hours) % 24

    rise = side(True)
    sett = side(False)
    if rise is None or sett is None:
        return None
    return rise, sett


def is_night(lat: float, lon: float, when: datetime) -> bool | None:
    local = when.astimezone()
    offset = local.utcoffset()
    tz_hours = 0.0 if offset is None else offset.total_seconds() / 3600
    events = solar_hours(lat, lon, local.date(), tz_hours)
    if events is None:
        return None
    rise, sett = events
    hour = local.hour + local.minute / 60 + local.second / 3600
    if rise <= sett:
        return hour < rise or hour >= sett
    return sett <= hour < rise


def schedule_night(hour: float, start: float, end: float) -> bool:
    start %= 24
    end %= 24
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end
