"""adsb.fi open data client for Flight Tracker.

Written from the public API description at https://github.com/adsbfi/opendata.
The public endpoint ``/v3/lat/{lat}/lon/{lon}/dist/{nm}`` returns aircraft
within a radius (up to 250 NM). Public endpoints are limited to one request per
second, and failed requests (400/401/403/404/429) count toward the limit, so
this client polls far slower than that and backs off on errors.

adsb.fi asks every user to cite adsb.fi and link to https://adsb.fi/.
"""

from __future__ import annotations

import json
import math
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

API_BASE = "https://opendata.adsb.fi/api"
HOME_PAGE = "https://adsb.fi/"
ATTRIBUTION = "Live aircraft data: adsb.fi open data (adsb.fi)"
MAX_RADIUS_NM = 250
MIN_INTERVAL_SEC = 5.0  # documented limit is 1 request/second; stay well under it
MAX_BACKOFF_SEC = 300.0
TIMEOUT_SEC = 6.0
RESPONSE_LIMIT = 6_000_000
STALE_OK_SEC = 60.0


def query_radius_nm(range_nm: Any) -> int:
    """Ask for a little more than the display range so edge traffic does not pop."""
    try:
        value = float(range_nm)
    except (TypeError, ValueError):
        value = 20.0
    if not math.isfinite(value) or value <= 0:
        value = 20.0
    return int(max(5, min(MAX_RADIUS_NM, math.ceil(value * 1.25) + 2)))


def radius_url(lat: float, lon: float, dist_nm: int) -> str:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("home position out of range")
    dist = int(max(1, min(MAX_RADIUS_NM, dist_nm)))
    return f"{API_BASE}/v3/lat/{lat:.4f}/lon/{lon:.4f}/dist/{dist}"


def to_feed_document(raw: Any) -> dict[str, Any]:
    """Turn an adsb.fi response into the readsb-style document the app normalises.

    adsb.fi lists aircraft under ``ac`` and gives ``now`` in milliseconds. Its
    ``type`` field is the message source (for example ``adsb_icao``), not the
    aircraft type, so it is moved to ``source`` and never read as a type code.
    """
    if not isinstance(raw, dict):
        raise ValueError("adsb.fi response is not a JSON object")
    rows = raw.get("ac")
    if rows is None:
        rows = raw.get("aircraft")
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise ValueError("adsb.fi response has no aircraft list")
    aircraft: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = {key: value for key, value in row.items() if key != "type"}
        if "type" in row:
            item["source"] = row.get("type")
        aircraft.append(item)
    now = raw.get("now")
    if isinstance(now, (int, float)) and now > 1e11:
        now = now / 1000.0
    return {"now": now if isinstance(now, (int, float)) else time.time(), "aircraft": aircraft, "provider": "adsb.fi"}


class HttpStatusError(RuntimeError):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


def http_get_json(url: str, user_agent: str, timeout: float = TIMEOUT_SEC) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(RESPONSE_LIMIT + 1)
    except urllib.error.HTTPError as exc:
        raise HttpStatusError(exc.code) from exc
    if len(data) > RESPONSE_LIMIT:
        raise RuntimeError("response too large")
    if not data:
        raise RuntimeError("empty response")
    return json.loads(data.decode("utf-8"))


class AdsbFiFeed:
    """Rate-limited, cached poller shared by every screen that asks for traffic.

    ``get`` never calls the network more often than ``min_interval`` seconds,
    whatever the kiosk poll rate. After a failure the wait doubles up to
    ``MAX_BACKOFF_SEC``; a 429 starts the backoff at 60 seconds.
    """

    min_interval_floor = 1.5  # seconds; adsb.fi documents 1 request/second

    def __init__(
        self,
        user_agent: str,
        fetch: Callable[[str, str, float], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        min_interval: float = MIN_INTERVAL_SEC,
    ) -> None:
        self.user_agent = user_agent
        self.fetch = fetch or http_get_json
        self.clock = clock
        self.min_interval = max(self.min_interval_floor, float(min_interval))
        self.lock = threading.Lock()
        self.doc: dict[str, Any] | None = None
        self.doc_at = 0.0
        self.doc_url = ""
        self.doc_home: tuple[float, float] | None = None
        self.last_request_at: float | None = None
        self.next_at = 0.0
        self.failures = 0
        self.last_error: str | None = None
        self.requests = 0

    def _backoff(self, exc: Exception) -> float:
        self.failures += 1
        delay = self.min_interval * (2 ** min(self.failures, 8))
        if isinstance(exc, HttpStatusError) and exc.status == 429:
            delay = max(delay, 60.0)
        return min(MAX_BACKOFF_SEC, delay)

    def get(self, lat: float, lon: float, range_nm: Any) -> dict[str, Any]:
        """Return {"doc", "fresh", "stale", "error", "ageSec"}; ``doc`` may be None."""
        url = radius_url(lat, lon, query_radius_nm(range_nm))
        home = (round(lat, 4), round(lon, 4))
        with self.lock:
            now = self.clock()
            if url != self.doc_url:
                if home != self.doc_home:
                    # Home moved: old traffic is somewhere else, drop it.
                    self.doc = None
                    self.doc_home = home
                # 1.0.7: only the range changed. 1.0.6 dropped the traffic here
                # too and then waited out the 5 s rate limit with nothing to
                # show, so aircraft vanished right after a range change (and
                # for minutes if adsb.fi then answered 429). Keep the old list
                # on the glass and ask for the new radius as soon as the
                # documented 1 request/second limit allows, unless backing off.
                self.doc_url = url
                if self.failures == 0 and self.last_request_at is not None:
                    self.next_at = min(self.next_at, self.last_request_at + self.min_interval_floor)
                elif self.failures == 0:
                    self.next_at = min(self.next_at, now)
            if now >= self.next_at:
                self.requests += 1
                self.last_request_at = now
                try:
                    doc = to_feed_document(self.fetch(url, self.user_agent, TIMEOUT_SEC))
                except Exception as exc:  # network, HTTP, JSON, or shape
                    self.last_error = f"adsb.fi: {exc}"
                    self.next_at = now + self._backoff(exc)
                else:
                    self.doc = doc
                    self.doc_at = now
                    self.failures = 0
                    self.last_error = None
                    self.next_at = now + self.min_interval
            age = now - self.doc_at if self.doc is not None else None
            if self.doc is not None and self.last_error is None:
                return {"doc": self.doc, "stale": False, "error": None, "ageSec": age}
            if self.doc is not None and age is not None and age <= STALE_OK_SEC:
                return {"doc": self.doc, "stale": True, "error": f"Feed delayed: {self.last_error}", "ageSec": age}
            return {"doc": None, "stale": False, "error": self.last_error or "adsb.fi: no data yet", "ageSec": age}
