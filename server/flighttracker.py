#!/usr/bin/env python3
"""Flight Tracker display server.

Serves the kiosk UI, the ADS-B feed, cached map tiles, and weather radar.
The desktop demo is the same process: ``python3 server/flighttracker.py --demo``.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import os
import hmac
import json
import math
import secrets
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from adsbfi import AdsbFiFeed, query_radius_nm, radius_url
from airports import search_airports
from gpio_input import GpioService
from wifi_net import connect_wifi, load_hotspot, set_country, wifi_scan, wifi_status
from logic import (
    backlight_value,
    demo_document,
    haversine_nm,
    normalize_aircraft,
    resolved_feed_url,
    sanitize_config,
    valid_frame_id,
    valid_tile,
)

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "FlightTracker/1.0.9 (personal flight display; Maverick Field Gear)"
TILE_LIMIT = 2_000_000
FEED_LIMIT = 6_000_000

BASEMAPS: dict[str, dict[str, Any]] = {
    "dark": {
        "minZoom": 0,
        "maxZoom": 16,
        "maxAge": 21 * 86400,
        "attribution": "Esri, HERE, Garmin, © OpenStreetMap contributors, and the GIS user community",
        "attributionUrl": "https://www.esri.com/en-us/legal/terms/data-attributions",
        "template": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        "labelTemplate": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
    },
    "light": {
        "minZoom": 0,
        "maxZoom": 19,
        "maxAge": 21 * 86400,
        "attribution": "Sources: Esri, HERE, Garmin, USGS, Intermap, INCREMENT P, NRCan, Esri Japan, METI, Esri China (Hong Kong), Esri Korea, Esri (Thailand), NGCC, © OpenStreetMap contributors, and the GIS User Community",
        "attributionUrl": "https://www.esri.com/en-us/legal/terms/data-attributions",
        "template": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    },
    "satellite": {
        "minZoom": 0,
        "maxZoom": 18,
        "maxAge": 21 * 86400,
        "attribution": "Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community",
        "attributionUrl": "https://www.esri.com/en-us/legal/terms/data-attributions",
        "template": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    },
    "sectional": {
        "minZoom": 8,
        "maxZoom": 12,
        "maxAge": 7 * 86400,
        "attribution": "",
        "attributionUrl": "",
        "template": "https://tiles.arcgis.com/tiles/ssFJjBXIUyZDrSYZ/arcgis/rest/services/VFR_Sectional/MapServer/tile/{z}/{y}/{x}",
    },
    "scope": {
        "minZoom": 0,
        "maxZoom": 0,
        "maxAge": 0,
        "attribution": "",
        "attributionUrl": "",
        "template": "",
    },
}

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
}


class App:
    def __init__(self, args: argparse.Namespace) -> None:
        self.dist = Path(args.dist).resolve()
        self.config_path = Path(args.config).resolve()
        self.cache = Path(args.cache).resolve()
        self.sample_path = Path(args.sample).resolve()
        self.force_demo = bool(args.demo)
        self.feed_overridden = False
        self.sessions: dict[str, float] = {}
        self.auth_path = self.config_path.with_name("auth.json")
        self.hotspot_path = self.config_path.with_name("hotspot.json")
        self.started = time.monotonic()
        self.lock = threading.Lock()
        self.sample = json.loads(self.sample_path.read_text(encoding="utf-8"))["aircraft"]
        self.config = self._load_config()
        self.normalize_update_status()
        self.gpio = GpioService()
        self.weather_cache: dict[str, Any] = {"at": 0.0, "body": None}
        self.metar_cache: dict[str, Any] = {"at": 0.0, "key": None, "body": None}
        self.remote_cache: dict[str, Any] = {"at": 0.0, "raw": None, "error": None}
        self.adsbfi = AdsbFiFeed(USER_AGENT)
        self._rate_at = 0.0
        self._rate_msgs = 0
        self.receiver_cache: dict[str, Any] = {"ok": False, "detail": "No data"}
        self.cache.mkdir(parents=True, exist_ok=True)
        self.gpio.apply(self.config)
        self.apply_brightness(self.config["brightness"])

    def _load_config(self) -> dict[str, Any]:
        example = ROOT / "data" / "config.example.json"
        if not self.config_path.is_file():
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        try:
            from migrate import migrate_config
        except ImportError:
            from server.migrate import migrate_config
        before_schema = payload.get("schema") if isinstance(payload, dict) else None
        before_updates = payload.get("updates") if isinstance(payload, dict) else None
        before_url = before_updates.get("url") if isinstance(before_updates, dict) else None
        # Migrate the file as written, then clean it. sanitize_config keeps
        # the schema number, so steps run once rather than on every start.
        if isinstance(payload, dict):
            payload = migrate_config(payload)
        cfg, errors = sanitize_config(payload)
        cfg = migrate_config(cfg)
        # Also rewrite the file when the update URL moved to the new GitHub owner (1.0.5).
        if errors or cfg.get("schema") != before_schema or cfg["updates"]["url"] != before_url:
            if errors:
                print("Config reset to safe values:", "; ".join(errors), flush=True)
            self._write_config(cfg)
        return cfg

    def _write_config(self, cfg: dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.config_path)

    def update_config(self, payload: Any) -> tuple[dict[str, Any] | None, list[str]]:
        cfg, errors = sanitize_config(payload)
        if errors:
            return None, errors
        with self.lock:
            self.config = cfg
            self._write_config(cfg)
        self.feed_overridden = True
        self.gpio.apply(cfg)
        self.apply_brightness(cfg["brightness"])
        self.metar_cache["at"] = 0
        return cfg, []

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return json.loads(json.dumps(self.config))

    def night_status(self) -> dict[str, Any]:
        from datetime import datetime

        try:
            from solar import is_night, schedule_night, solar_hours
        except ImportError:
            from server.solar import is_night, schedule_night, solar_hours
        cfg = self.snapshot()
        night = cfg.get("night") or {}
        mode = str(night.get("mode") or "off")
        local = datetime.now().astimezone()
        offset = local.utcoffset()
        tz_hours = 0.0 if offset is None else offset.total_seconds() / 3600
        events = solar_hours(float(cfg["home"]["lat"]), float(cfg["home"]["lon"]), local.date(), tz_hours)
        hour = local.hour + local.minute / 60
        active = False
        if mode == "sun":
            flag = is_night(float(cfg["home"]["lat"]), float(cfg["home"]["lon"]), local)
            active = bool(flag)
        elif mode == "schedule":
            active = schedule_night(hour, _night_hours(night, "from", "fromHour"), _night_hours(night, "to", "toHour"))
        return {
            "mode": mode,
            "night": active,
            "brightness": int(night.get("brightness") or 25),
            "sunrise": None if not events else round(events[0], 2),
            "sunset": None if not events else round(events[1], 2),
        }

    def touch_activity(self) -> None:
        path = self.config_path.with_name("activity")
        try:
            path.write_text(f"{int(time.time())}\n", encoding="ascii")
        except OSError as exc:
            print(f"Activity stamp failed: {exc}", flush=True)

    def update_view(self, **extra: Any) -> dict[str, Any]:
        """The one shape every /api/updates* answer uses, so the Software card
        never loses the saved-key line, version, or settings (1.0.3 returned a
        bare check record from CHECK FOR UPDATES and the key looked unsaved)."""
        from updater import read_status

        status = self.display_status(read_status(self.config_path))
        updates = self.config.get("updates") or {}
        state = str(status.get("state") or "")
        error = str(status.get("error") or "")
        detail = str(status.get("detail") or "")
        stage = str(status.get("stage") or "")
        if state == "installing" and self.install_stalled(status):
            state, stage = "error", "failed"
            error = "The update stopped without finishing. Check for updates and try again."
            detail = f"Update failed. Still running Version {running_version()}."

        def _int(value: Any) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        view = {
            "version": running_version(),
            "auto": bool(updates.get("auto")),
            "url": str(updates.get("url") or ""),
            "available": bool(status.get("available")),
            "latest": status.get("version") or "",
            "notes": status.get("notes") or "",
            "state": state,
            "stage": stage,
            "step": _int(status.get("step")),
            "steps": _int(status.get("steps")),
            "target": str(status.get("target") or ""),
            "detail": detail,
            "received": _int(status.get("received")),
            "total": _int(status.get("total")),
            "installedAt": status.get("installedAt") or "",
            "error": error,
            "checkedAt": status.get("checkedAt") or "",
        }
        view.update(self.update_source_view())
        view.update(self._prompt_fields(view))
        view.update(extra)
        return view

    def _update_ring(self) -> tuple[dict[str, Any], dict[str, Any]]:
        from updater import load_keyring, read_trust_state

        state = read_trust_state()
        key_env = os.environ.get("FLIGHT_TRACKER_UPDATE_KEY", "")
        return load_keyring(Path(key_env) if key_env else None, ROOT, state), state

    def update_source_view(self) -> dict[str, Any]:
        """1.0.7: where signed updates come from and the pinned key fingerprint(s)."""
        from updater import UpdateError, ring_fingerprints, update_source

        repo, channel, url = update_source(self.config.get("updates") or {})
        cached = getattr(self, "_fingerprint_cache", None)
        if cached and time.monotonic() - cached[0] < 300:
            prints = cached[1]
        else:
            try:
                prints = ring_fingerprints(self._update_ring()[0])
            except (UpdateError, Exception):  # missing key: show nothing rather than fail the card
                prints = []
            self._fingerprint_cache = (time.monotonic(), prints)
        return {
            "repo": repo,
            "channel": channel,
            "source": f"github.com/{repo}" if repo else url,
            "keyFingerprints": prints,
        }

    # ---- 1.0.7: on-screen update prompt and "install later" ----

    def _later_at(self) -> str:
        from update_schedule import DEFAULT_LATER_AT, valid_later_at

        updates = self.config.get("updates") or {}
        return valid_later_at(updates.get("laterAt")) or DEFAULT_LATER_AT

    def _later_tz(self) -> str:
        from update_schedule import DEFAULT_LATER_TZ, valid_tz

        updates = self.config.get("updates") or {}
        return valid_tz(updates.get("laterTz")) or DEFAULT_LATER_TZ

    def _prompt_fields(self, view: dict[str, Any]) -> dict[str, Any]:
        from update_schedule import prompt_visible, read_schedule, summary_line, time_label, zone_short

        schedule = read_schedule(self.config_path)
        latest = str(view.get("latest") or "")
        installing = view.get("state") == "installing"
        # A booking for a version that is no longer newer is not shown.
        pending = (
            schedule
            if schedule.get("state") == "pending" and self.is_newer(schedule.get("version"), running_version())
            else None
        )
        show = prompt_visible(
            available=bool(view.get("available")),
            latest=latest,
            token_set=True,  # 1.0.7: tokenless, every unit can check
            auto=bool(view.get("auto")),
            installing=installing,
            schedule=schedule,
            now_epoch=time.time(),
        )
        later_at = self._later_at()
        return {
            "laterAt": later_at,
            "laterTz": self._later_tz(),
            "laterZone": zone_short(self._later_tz()),
            "laterLabel": time_label(later_at, str(self.config.get("clockFormat") or "24h"), self._later_tz()),
            "schedule": {k: pending.get(k) for k in ("version", "atEpoch", "atLocal", "zone", "label", "day", "source")} if pending else None,
            "prompt": {"show": show, "version": latest if show else "", "summary": summary_line(str(view.get("notes") or "")) if show else ""},
        }

    def defer_update(self, version: str, source: str = "later") -> tuple[bool, str]:
        """LATER on the round screen (or no answer): book the install for the default time."""
        from update_schedule import booking, write_schedule
        from updater import read_status

        status = self.display_status(read_status(self.config_path))
        latest = str(status.get("version") or "")
        if not (status.get("available") and self.is_newer(latest, running_version())):
            return False, "There is no newer version to schedule."
        if version and version != latest:
            return False, f"Version {version} is not the update on offer (Version {latest})."
        source = source if source in ("later", "timeout", "auto") else "later"
        body = booking(latest, self._later_at(), str(self.config.get("clockFormat") or "24h"), source, datetime.now(timezone.utc), self._later_tz())
        write_schedule(self.config_path, body)
        return True, f"Update scheduled for {body['label']}"

    def cancel_update_schedule(self) -> tuple[bool, str]:
        from update_schedule import CHECK_EVERY_SEC, read_schedule, write_schedule

        schedule = read_schedule(self.config_path)
        if schedule.get("state") != "pending":
            return False, "No update is scheduled."
        schedule.update(state="cancelled", quietUntil=time.time() + CHECK_EVERY_SEC)
        write_schedule(self.config_path, schedule)
        return True, f"Scheduled install of Version {schedule.get('version')} cancelled."

    def set_later_at(self, value: Any) -> tuple[bool, str]:
        from update_schedule import booking, read_schedule, valid_later_at, write_schedule

        hhmm = valid_later_at(value)
        if not hhmm:
            return False, "Install later at must be a time like 02:00."
        cfg = self.snapshot()
        cfg.setdefault("updates", {})["laterAt"] = hhmm
        saved, errors = self.update_config(cfg)
        if errors or saved is None:
            return False, " ".join(errors) or "Could not save."
        schedule = read_schedule(self.config_path)
        if schedule.get("state") == "pending":
            moved = booking(str(schedule.get("version")), hhmm, str(self.config.get("clockFormat") or "24h"), str(schedule.get("source") or "later"), datetime.now(timezone.utc), self._later_tz())
            write_schedule(self.config_path, moved)
        return True, "Saved."

    def scheduler_tick(self, now: datetime | None = None) -> str:
        """One pass of the background update loop. Returns what it did (for tests and the log)."""
        from update_schedule import CHECK_EVERY_SEC, FIRST_CHECK_AFTER_SEC, read_schedule, write_schedule

        now = now or datetime.now(timezone.utc)
        mono = time.monotonic()
        if self.installing_now():
            return "installing"
        # 1. Background check: soon after start, then every 6 hours (anonymous, no key needed).
        last = getattr(self, "_bg_checked_at", None)
        due = (mono - self.started >= FIRST_CHECK_AFTER_SEC) if last is None else (mono - last >= CHECK_EVERY_SEC)
        if due:
            self._bg_checked_at = mono
            self.check_updates()
            return "checked"
        view = self.update_view()
        schedule = read_schedule(self.config_path)
        # 2. Auto-update on: book the default time without asking.
        if view.get("auto") and view.get("available") and schedule.get("version") != view.get("latest"):
            self.defer_update(str(view.get("latest")), "auto")
            return "auto-booked"
        # 3. A booked install whose time has come.
        if schedule.get("state") == "pending" and now.timestamp() >= float(schedule.get("atEpoch") or 0):
            schedule.update(state="attempted", quietUntil=time.time() + CHECK_EVERY_SEC, attemptedEpoch=time.time())
            if not (view.get("available") and view.get("latest") == schedule.get("version")):
                write_schedule(self.config_path, schedule)
                return "skipped-not-newer"
            ok, detail = self.install_update()
            schedule["result"] = "started" if ok else detail
            write_schedule(self.config_path, schedule)
            return "installed" if ok else "install-failed"
        return "idle"

    def start_update_scheduler(self, every: float = 30.0) -> threading.Thread:
        def loop() -> None:
            while True:
                try:
                    action = self.scheduler_tick()
                    if action not in ("idle", "installing"):
                        print(f"Update scheduler: {action}", flush=True)
                except Exception as exc:  # never let the loop die
                    print(f"Update scheduler error: {exc}", flush=True)
                time.sleep(every)

        thread = threading.Thread(target=loop, name="flight-tracker-update-scheduler", daemon=True)
        thread.start()
        return thread

    INSTALL_STALL_SEC = 10 * 60

    @staticmethod
    def is_newer(version: Any, running: str) -> bool:
        """True only when ``version`` parses as strictly newer than ``running``."""
        from updater import UpdateError, parse_version

        try:
            return parse_version(str(version or "")) > parse_version(running)
        except UpdateError:
            return False

    def display_status(self, status: dict[str, Any]) -> dict[str, Any]:
        """The stored update status as it applies to the version running now.

        1.0.6: a status written by an older release (e.g. "available 1.0.3"
        saved by a 1.0.2 check) is not an update for 1.0.5. "available" is
        only true for a strictly newer version; anything else reads as up to
        date, with the stale notes and target cleared.
        """
        status = dict(status)
        running = running_version()
        newer = self.is_newer(status.get("version"), running)
        state = str(status.get("state") or "")
        status["available"] = bool(status.get("available")) and newer
        stale = (
            (state == "available" and not newer)
            or (state == "installed" and str(status.get("version") or "") != running)
            or (state == "installing" and not newer and self.install_stalled(status))
        )
        if stale:
            status.update(state="current", stage="", target="", notes="", detail="", error="", version=running, available=False)
        elif not newer and state in ("rolled-back", "error"):
            status["notes"] = ""
        return status

    def normalize_update_status(self) -> None:
        """On start, rewrite a stale update-status.json once (see display_status)."""
        from updater import read_status, write_status

        stored = read_status(self.config_path)
        if not stored:
            return
        shown = self.display_status(stored)
        if shown.get("state") == "current" and stored.get("state") != "current":
            try:
                write_status(self.config_path, {k: v for k, v in shown.items() if k not in ("updatedAt", "updatedEpoch")})
            except OSError as exc:
                print(f"Update status not rewritten: {exc}", flush=True)

    def install_stalled(self, status: dict[str, Any]) -> bool:
        """An "installing" status nobody has touched for 10 minutes (power cut, crash)."""
        try:
            stamp = float(status.get("updatedEpoch") or 0)
        except (TypeError, ValueError):
            stamp = 0.0
        if not stamp:
            try:
                stamp = self.config_path.with_name("update-status.json").stat().st_mtime
            except OSError:
                return True
        return time.time() - stamp > self.INSTALL_STALL_SEC

    def installing_now(self) -> bool:
        from updater import read_status

        status = read_status(self.config_path)
        return status.get("state") == "installing" and not self.install_stalled(status)

    def check_updates(self) -> dict[str, Any]:
        from updater import UpdateError, check_for_update, record_check, update_source

        if self.installing_now():
            return self.update_view(ok=False, detail="An update is installing. Wait for it to finish.")
        repo, channel, url = update_source(self.config.get("updates") or {})
        ca = os.environ.get("FLIGHT_TRACKER_UPDATE_CA") or None
        try:
            ring, state = self._update_ring()
            found = check_for_update(url, ring, running_version(), ca_file=ca, repo=repo, channel=channel, state=state)
            found.pop("manifest", None)
            record_check(self.config_path, found)
            return self.update_view(ok=True)
        except UpdateError as exc:
            record_check(self.config_path, {"current": running_version(), "available": False}, str(exc))
            return self.update_view(ok=False)

    UPDATE_WRAPPER = Path("/usr/local/sbin/flight-tracker-update")

    def install_update(self) -> tuple[bool, str]:
        """Queue the signed install and report whether it really started.

        The root helper hands the job to systemd with --no-block, so it returns
        within a second: exit 0 when systemd accepted the job, otherwise the
        real sudo/systemd error. 1.0.3 fired it off with Popen and always said
        "Installing...", even when the helper died at once.
        """
        from updater import read_status, write_status

        wrapper = self.UPDATE_WRAPPER
        if not wrapper.is_file():
            return False, "Install runs on the Pi. The update helper is not installed on this machine."
        if self.installing_now():
            return False, "An update is already installing. Wait for it to finish."
        before = read_status(self.config_path)
        running = running_version()
        if not (before.get("available") and self.is_newer(before.get("version"), running)):
            return False, f"Nothing newer to install. This unit is running Version {running}. Tap CHECK FOR UPDATES first."
        target = str(before.get("version") or "")
        base = {
            "current": running,
            "version": target,
            "notes": before.get("notes") or "",
            "available": bool(before.get("available")),
            "checkedAt": before.get("checkedAt") or "",
        }
        write_status(
            self.config_path,
            {**base, "state": "installing", "stage": "starting", "step": 0, "steps": 4, "target": target, "error": "", "detail": "Starting update..."},
        )
        try:
            result = subprocess.run(
                ["sudo", "-n", str(wrapper), "--install"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            failure = "" if result.returncode == 0 else (
                (result.stderr or "").strip() or (result.stdout or "").strip() or f"The update helper exited with code {result.returncode}."
            )
        except subprocess.TimeoutExpired:
            failure = "The update helper did not answer within 15 seconds."
        except OSError as exc:
            failure = str(exc)
        if failure:
            failure = failure.splitlines()[-1][:300]
            current = read_status(self.config_path)
            # The helper may already have written its own failure; keep that one.
            if current.get("state") == "installing" and current.get("stage") == "starting":
                write_status(
                    self.config_path,
                    {**base, "state": "error", "stage": "failed", "target": "", "error": failure,
                     "detail": f"Update could not start. Still running Version {running}."},
                )
            return False, failure
        return True, "Installing. Progress shows here step by step; the round screen reloads when the new version is running."

    def set_auto_update(self, enabled: bool) -> tuple[dict[str, Any] | None, list[str]]:
        cfg = self.snapshot()
        updates = cfg.get("updates")
        if not isinstance(updates, dict):
            cfg["updates"] = {}
        cfg["updates"]["auto"] = bool(enabled)
        return self.update_config(cfg)

    def backlight_nodes(self) -> list[str]:
        return sorted(glob.glob("/sys/class/backlight/*/brightness"))

    def apply_brightness(self, percent: float) -> bool:
        """Write the panel backlight the way the 4inch DSI LCD (C) wiki specifies.

        Returns True when a sysfs node accepted the value. The desktop demo
        has no node; the page then dims itself instead of pretending the
        panel backlight changed.
        """
        value = backlight_value(percent)
        nodes = self.backlight_nodes()
        if not nodes:
            return False
        wrapper = Path("/usr/local/sbin/flight-tracker-brightness")
        script = wrapper if wrapper.is_file() else ROOT / "scripts" / "brightness.sh"
        if script.is_file():
            result = subprocess.run(
                ["sudo", "-n", str(script), str(value)],
                timeout=3,
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print(f"Backlight {value}/255 via {script.name}", flush=True)
                return True
            detail = (result.stderr or result.stdout or "").strip()
            print(f"Backlight sudo write failed ({detail or result.returncode})", flush=True)
        # Same sysfs path as the wiki. Used only when this process can write
        # the node without sudo. TODO: the wiki always shows sudo tee and
        # does not say the node is group-writable.
        wrote = False
        for path in nodes:
            try:
                Path(path).write_text(str(value), encoding="ascii")
            except OSError as exc:
                print(f"Backlight write {path} failed: {exc}", flush=True)
            else:
                wrote = True
        return wrote

    def hotspot(self) -> dict[str, str]:
        return load_hotspot(self.hotspot_path)

    def wifi(self) -> dict[str, Any]:
        return wifi_status(self.hotspot())

    def auth_record(self) -> dict[str, str] | None:
        if not self.auth_path.is_file():
            return None
        try:
            data = json.loads(self.auth_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if isinstance(data, dict) and data.get("salt") and data.get("hash"):
            return {"salt": str(data["salt"]), "hash": str(data["hash"])}
        return None

    def check_password(self, password: str) -> bool:
        record = self.auth_record()
        if record is None:
            return True
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), record["salt"].encode("ascii"), 120_000).hex()
        return hmac.compare_digest(digest, record["hash"])

    def open_session(self) -> str:
        token = secrets.token_urlsafe(24)
        self.sessions[token] = time.time() + 60 * 60 * 12
        return token

    def session_ok(self, token: str) -> bool:
        expiry = self.sessions.get(token, 0)
        if expiry < time.time():
            self.sessions.pop(token, None)
            return False
        return True

    def test_feed(self, draft: dict[str, Any] | None = None) -> dict[str, Any]:
        cfg = self.snapshot()
        feed = dict(cfg["feed"])
        if isinstance(draft, dict):
            for key in ("mode", "localPath", "remoteUrl", "host", "port", "fallbackDemo"):
                if key in draft:
                    feed[key] = draft[key]
        mode = str(feed.get("mode") or "local")
        if self.force_demo and not self.feed_overridden and not isinstance(draft, dict):
            mode = "demo"
        if mode == "demo":
            return {"ok": True, "mode": "demo", "count": len(self.sample), "detail": "Sample tracks are loaded."}
        if mode == "adsbfi":
            home = cfg["home"]
            result = self.adsbfi.get(float(home["lat"]), float(home["lon"]), cfg.get("rangeNm"))
            if result["doc"] is None:
                return {"ok": False, "mode": "adsbfi", "count": 0, "detail": str(result["error"])}
            rows = normalize_aircraft(result["doc"])
            dist = query_radius_nm(cfg.get("rangeNm"))
            return {"ok": True, "mode": "adsbfi", "count": len(rows), "detail": f"{len(rows)} aircraft within {dist} NM from adsb.fi."}
        if mode == "local":
            path = Path(str(feed.get("localPath") or ""))
            try:
                rows = normalize_aircraft(json.loads(path.read_text(encoding="utf-8")))
            except FileNotFoundError:
                return {"ok": False, "mode": "local", "count": 0, "detail": f"No file at {path}"}
            except (OSError, json.JSONDecodeError) as exc:
                return {"ok": False, "mode": "local", "count": 0, "detail": str(exc)}
            return {"ok": True, "mode": "local", "count": len(rows), "detail": f"{len(rows)} aircraft with a position."}
        url = resolved_feed_url(feed)
        if not url:
            return {"ok": False, "mode": "remote", "count": 0, "detail": "Enter a host or a JSON URL."}
        try:
            rows = normalize_aircraft(json.loads(fetch_bytes(url, limit=FEED_LIMIT, timeout=4).decode("utf-8")))
        except Exception as exc:
            return {"ok": False, "mode": "remote", "count": 0, "detail": f"{url}: {exc}"}
        return {"ok": True, "mode": "remote", "count": len(rows), "detail": f"{len(rows)} aircraft from {url}"}

    def reset_config(self) -> dict[str, Any]:
        from logic import DEFAULT_CONFIG

        cfg, _errors = sanitize_config(DEFAULT_CONFIG)
        with self.lock:
            self.config = cfg
            self._write_config(cfg)
        self.feed_overridden = True
        self.apply_brightness(cfg["brightness"])
        return cfg

    def restart_display(self) -> tuple[bool, str]:
        result = subprocess.run(
            ["sudo", "-n", "systemctl", "restart", "flight-tracker-kiosk.service"],
            timeout=8,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True, "Display restarted."
        # TODO: systemctl restart of the kiosk was not tested on a Pi.
        detail = (result.stderr or result.stdout or "systemctl is not available").strip()
        return False, f"Settings are already live. Kiosk restart did not run ({detail})."

    @staticmethod
    def requested_range(value: Any) -> float | None:
        """A display range sent by the kiosk (?range=NM), or None when absent or invalid."""
        try:
            nm = float(value)
        except (TypeError, ValueError):
            return None
        # 1.0.8: display steps start at 10 NM; 100 is the maximum (adsb.fi allows up to 250).
        # Values between 1 and 100 are still accepted so a mid-animation poll is not dropped.
        if not math.isfinite(nm) or nm < 1 or nm > 100:
            return None
        return nm

    def aircraft(self, freeze: bool, range_nm: float | None = None) -> dict[str, Any]:
        cfg = self.snapshot()
        # 1.0.7: the kiosk sends the range it is showing right now, so a range
        # picked on the glass is fetched at once instead of after the debounced
        # config save reaches the server.
        query_range = range_nm if range_nm is not None else cfg.get("rangeNm")
        mode = cfg["feed"]["mode"]
        if self.force_demo and not self.feed_overridden:
            mode = "demo"
        source = mode
        stale = False
        error = None
        raw: Any = None
        if mode == "demo":
            raw = demo_document(self.sample, 0.0 if freeze else time.monotonic() - self.started)
        elif mode == "adsbfi":
            home = cfg["home"]
            result = self.adsbfi.get(float(home["lat"]), float(home["lon"]), query_range)
            raw = result["doc"]
            stale = bool(result["stale"])
            error = result["error"]
            if raw is None and cfg["feed"]["fallbackDemo"]:
                source = "demo-fallback"
                raw = demo_document(self.sample, 0.0 if freeze else time.monotonic() - self.started)
        elif mode == "local":
            path = Path(cfg["feed"]["localPath"])
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                if cfg["feed"]["fallbackDemo"]:
                    source = "demo-fallback"
                    raw = demo_document(self.sample, 0.0 if freeze else time.monotonic() - self.started)
                else:
                    error = f"No aircraft file at {path}"
            except (OSError, json.JSONDecodeError) as exc:
                error = f"Could not read the local feed: {exc}"
        else:
            url = resolved_feed_url(cfg["feed"])
            if not url:
                error = "Remote feed URL is empty."
            else:
                try:
                    raw = json.loads(fetch_bytes(url, limit=FEED_LIMIT, timeout=4).decode("utf-8"))
                    self.remote_cache = {"at": time.time(), "raw": raw, "error": None}
                except Exception as exc:  # network, HTTP, or JSON
                    age = time.time() - float(self.remote_cache["at"] or 0)
                    if self.remote_cache["raw"] is not None and age < 30:
                        raw = self.remote_cache["raw"]
                        stale = True
                        error = f"Feed delayed: {exc}"
                    else:
                        error = f"Remote feed failed: {exc}"
        rows = normalize_aircraft(raw) if raw is not None else []
        try:
            from watchlist import filter_aircraft, load_registration_db
        except ImportError:
            from server.watchlist import filter_aircraft, load_registration_db
        rows = filter_aircraft(rows, cfg.get("watch"), load_registration_db())
        receiver = self._receiver_stats(raw, rows)
        return {
            "now": time.time(),
            "source": source,
            "stale": stale,
            "error": error,
            "aircraft": rows,
            "receiver": receiver,
        }

    def _receiver_stats(self, raw: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(raw, dict):
            self.receiver_cache = {"ok": False, "detail": "No data"}
            return self.receiver_cache
        messages = raw.get("messages")
        try:
            messages_n = int(messages) if messages is not None else None
        except (TypeError, ValueError):
            messages_n = None
        now = time.time()
        rate = None
        if messages_n is not None and self._rate_at:
            dt = now - self._rate_at
            if dt >= 0.8 and messages_n >= self._rate_msgs:
                rate = round((messages_n - self._rate_msgs) / dt, 1)
        if messages_n is not None:
            self._rate_at = now
            self._rate_msgs = messages_n
        rssi: list[float] = []
        ages: list[float] = []
        internet = raw.get("provider") == "adsb.fi"
        for row in raw.get("aircraft") or []:
            if not isinstance(row, dict):
                continue
            # adsb.fi signal levels belong to other people's receivers, not this unit.
            if not internet and isinstance(row.get("rssi"), (int, float)):
                rssi.append(float(row["rssi"]))
            if isinstance(row.get("seen"), (int, float)):
                ages.append(float(row["seen"]))
            elif isinstance(row.get("seen_pos"), (int, float)):
                ages.append(float(row["seen_pos"]))
        self.receiver_cache = {
            "ok": True,
            "messages": messages_n,
            "messageRate": rate,
            "aircraft": len(rows),
            "rssi": round(sum(rssi) / len(rssi), 1) if rssi else None,
            "lastSeenSec": round(min(ages), 1) if ages else None,
            "detail": "" if rows or messages_n else "No data",
            "provider": "adsb.fi" if internet else "receiver",
        }
        if not rows and messages_n is None and not internet:
            self.receiver_cache["ok"] = False
            self.receiver_cache["detail"] = "No data"
        return self.receiver_cache

    def weather_index(self) -> dict[str, Any]:
        # Ages use the monotonic clock: a wall-clock step (NTP correcting a Pi
        # that booted with an old time) must not pin the cache for hours.
        now = time.monotonic()
        cached = self.weather_cache
        body = cached["body"]
        # Rate limit: one index request per 2 minutes while RainViewer works
        # (frames change every 10 minutes), one per 60 s while it is failing
        # or the IEM stand-in is on, so RainViewer is retried soon.
        if body is not None:
            ttl = 120 if body.get("ok", True) and body.get("provider") == "rainviewer" else 60
            if 0 <= now - float(cached["at"]) < ttl:
                return body
        body = self._fetch_weather_index()
        self.weather_cache = {"at": now, "body": body}
        self._prune_weather_cache()
        return body

    def _fetch_weather_index(self) -> dict[str, Any]:
        try:
            meta = json.loads(
                fetch_bytes("https://api.rainviewer.com/public/weather-maps.json", timeout=6).decode("utf-8")
            )
            frames = []
            for frame in meta.get("radar", {}).get("past", []):
                path = str(frame.get("path", "")).strip("/")
                parts = path.split("/")
                if len(parts) == 3 and parts[0] == "v2" and parts[1] == "radar" and valid_frame_id(parts[2]):
                    frames.append({"id": parts[2], "time": frame.get("time")})
            if not frames:
                raise RuntimeError("RainViewer returned no frames")
            self.weather_good_at = time.monotonic()
            return {
                "provider": "rainviewer",
                "attribution": "Weather radar by RainViewer",
                "attributionUrl": "https://www.rainviewer.com/",
                # RainViewer's free tiles stop at zoom 7 ("Zoom Level Not
                # Supported" above it); the display scales z7 up.
                "maxZoom": 7,
                "frames": frames,
                "ok": True,
                "error": "",
            }
        except Exception as exc:
            print(f"Weather index fell back to IEM: {exc}", flush=True)
            previous = self.weather_cache.get("body")
            good_at = getattr(self, "weather_good_at", None)
            if (
                isinstance(previous, dict)
                and previous.get("provider") == "rainviewer"
                and good_at is not None
                and time.monotonic() - float(good_at) < 30 * 60
            ):
                return previous
            try:
                fetch_bytes(
                    "https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913/0/0/0.png",
                    timeout=6,
                )
            except Exception as iem_exc:
                print(f"Weather unavailable: RainViewer ({exc}); IEM ({iem_exc})", flush=True)
                return {
                    "provider": "none",
                    "attribution": "",
                    "attributionUrl": "",
                    "maxZoom": 7,
                    "frames": [],
                    "ok": False,
                    "error": "Weather radar is unreachable. Check the internet connection.",
                }
            # IEM serves one "current" composite that it redraws every 5
            # minutes. 1.0.2 called that frame "latest" for ever, so the tile
            # URL and the server's 2-day tile cache never changed and the
            # radar froze on the first picture. Name it by its 5-minute slot
            # so each new composite gets a new URL and a new cache folder.
            frame_id, frame_time = iem_frame(time.time())
            return {
                "provider": "iem",
                "attribution": "NEXRAD composite via Iowa Environmental Mesonet",
                "attributionUrl": "https://mesonet.agron.iastate.edu/",
                "maxZoom": 8,
                "frames": [{"id": frame_id, "time": frame_time}],
                "ok": True,
                "error": "",
            }

    def weather_tile(self, frame: str, z: int, x: int, y: int) -> tuple[int, bytes | str]:
        """Return (200, png bytes) or (status, error text) for one radar tile."""
        if not valid_frame_id(frame):
            return 400, "Bad frame"
        index = self.weather_index()
        if not index.get("frames"):
            return 503, "Weather radar unavailable"
        max_z = int(index["maxZoom"])
        if not valid_tile(z, x, y, 0, max_z):
            return 404, "Tile out of range"
        known = {item["id"] for item in index["frames"]}
        provider = index["provider"]
        if provider == "iem":
            # Allow the previous 5-minute slot too: the display may ask for it
            # just after the slot rolls over.
            slot = iem_slot(frame)
            current = iem_slot(index["frames"][-1]["id"])
            if slot is None or current is None or not 0 <= current - slot <= 2 * IEM_SLOT_SEC:
                return 404, "Unknown frame"
        elif frame not in known:
            return 404, "Unknown frame"
        if provider == "rainviewer":
            url = f"https://tilecache.rainviewer.com/v2/radar/{frame}/256/{z}/{x}/{y}/2/1_1.png"
            max_age = 2 * 86400  # a RainViewer frame never changes
        else:
            url = (
                "https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/"
                f"nexrad-n0q-900913/{z}/{x}/{y}.png"
            )
            max_age = IEM_SLOT_SEC
        dest = cache_path(self.cache, "weather", provider, frame, str(z), str(x), f"{y}.png")
        # A failed radar tile is retried after 60 s, not 10 minutes, so a
        # Wi-Fi blip does not leave a hole in the picture.
        data = cached_fetch(self.cache, dest, url, max_age, miss_ttl=60)
        if data is None:
            return 404, "Radar tile unavailable"
        return 200, data

    def _prune_weather_cache(self) -> None:
        """Delete radar frames older than 3 hours so the SD card does not fill."""
        now = time.monotonic()
        cache = getattr(self, "cache", None)
        if cache is None or now - float(getattr(self, "_weather_pruned_at", -1e9)) < 600:
            return
        self._weather_pruned_at = now
        try:
            prune_weather_cache(cache / "weather", time.time() - WEATHER_KEEP_SEC)
        except OSError as exc:
            print(f"Weather cache prune skipped: {exc}", flush=True)

    def metar(self, lat: float, lon: float, station: str = "") -> dict[str, Any] | None:
        station = station.strip().upper()
        key: Any = ("id", station) if station else (round(lat, 2), round(lon, 2))
        now = time.monotonic()
        cached = self.metar_cache
        # 2 minutes between fetches while it works, 60 s while it fails.
        ttl = 120 if cached.get("body") is not None and not cached["body"].get("stale") else 60
        if cached["key"] == key and 0 <= now - float(cached["at"]) < ttl:
            return cached["body"]
        body = self._fetch_metar(lat, lon, station)
        good = getattr(self, "metar_good", None)
        if body is not None:
            self.metar_good = {"key": key, "body": body, "at": time.time()}
        elif isinstance(good, dict) and good.get("key") == key:
            # A failed fetch keeps the last report on the glass, marked stale,
            # for up to 3 hours after it was observed, instead of blanking it.
            seen = good["body"].get("obsTime")
            seen = float(seen) if isinstance(seen, (int, float)) else float(good["at"])
            if time.time() - seen < 3 * 3600:
                body = dict(good["body"], stale=True)
        self.metar_cache = {"at": now, "key": key, "body": body}
        return body

    def _fetch_metar(self, lat: float, lon: float, station: str = "") -> dict[str, Any] | None:
        if station:
            url = f"https://aviationweather.gov/api/data/metar?format=json&ids={urllib.parse.quote(station)}"
        else:
            dlat = 0.9
            dlon = 0.9 / max(0.25, abs(math.cos(math.radians(lat))))
            south, north = lat - dlat, lat + dlat
            west, east = lon - dlon, lon + dlon
            url = (
                "https://aviationweather.gov/api/data/metar?format=json"
                f"&bbox={south:.3f},{west:.3f},{north:.3f},{east:.3f}"
            )
        try:
            rows = json.loads(fetch_bytes(url, timeout=6).decode("utf-8"))
        except Exception as exc:
            print(f"METAR unavailable: {exc}", flush=True)
            return None
        if not isinstance(rows, list) or not rows:
            return None
        best = None
        best_nm = 1e9
        for row in rows:
            if not isinstance(row, dict):
                continue
            rlat, rlon = row.get("lat"), row.get("lon")
            if not isinstance(rlat, (int, float)) or not isinstance(rlon, (int, float)):
                continue
            dist = haversine_nm(lat, lon, float(rlat), float(rlon))
            if dist < best_nm:
                best_nm = dist
                best = row
        if best is None:
            return None
        raw = str(best.get("rawOb") or "")
        if raw.upper().startswith("METAR "):
            raw = raw[6:]
        return {
            "icao": best.get("icaoId"),
            "name": best.get("name"),
            "raw": raw,
            "lat": best.get("lat"),
            "lon": best.get("lon"),
            "distanceNm": round(best_nm, 1),
            "tempC": best.get("temp"),
            "windDir": best.get("wdir"),
            "windKt": best.get("wspd"),
            "obsTime": best.get("obsTime"),
        }


IEM_SLOT_SEC = 300
WEATHER_KEEP_SEC = 3 * 3600


def iem_frame(now: float) -> tuple[str, int]:
    """Frame id and time for the IEM composite of the 5-minute slot holding now."""
    slot = int(now // IEM_SLOT_SEC) * IEM_SLOT_SEC
    return f"iem{slot}", slot


def iem_slot(frame: str) -> int | None:
    if not frame.startswith("iem") or not frame[3:].isdigit():
        return None
    return int(frame[3:])


def prune_weather_cache(root: Path, cutoff: float) -> int:
    """Remove radar frame folders (weather/<provider>/<frame>) last changed before cutoff."""
    removed = 0
    if not root.is_dir():
        return 0
    for provider in root.iterdir():
        if not provider.is_dir():
            continue
        for frame in provider.iterdir():
            if frame.is_dir() and frame.stat().st_mtime < cutoff:
                shutil.rmtree(frame, ignore_errors=True)
                removed += 1
    return removed


def fetch_bytes(url: str, timeout: float = 8, limit: int = TILE_LIMIT) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc
    if len(data) > limit:
        raise RuntimeError("response too large")
    if not data:
        raise RuntimeError("empty response")
    return data


def sniff_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data.startswith(b"GIF8"):
        return "image/gif"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return "image/webp"
    return "application/octet-stream"


def cache_path(cache: Path, *parts: str) -> Path:
    path = cache.joinpath(*parts)
    if not str(path.resolve()).startswith(str(cache.resolve())):
        raise ValueError("cache path escaped")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def cached_fetch(cache: Path, dest: Path, url: str, max_age: float, miss_ttl: float = 600) -> bytes | None:
    miss = dest.with_suffix(dest.suffix + ".miss")
    if dest.is_file() and dest.stat().st_size > 32 and 0 <= (time.time() - dest.stat().st_mtime) < max_age:
        return dest.read_bytes()
    if miss.is_file() and 0 <= (time.time() - miss.stat().st_mtime) < miss_ttl:
        return None
    try:
        data = fetch_bytes(url)
    except Exception:
        miss.write_bytes(b"1")
        return None
    if sniff_type(data) == "application/octet-stream":
        miss.write_bytes(b"1")
        return None
    dest.write_bytes(data)
    if miss.exists():
        miss.unlink()
    return data


def running_version() -> str:
    path = ROOT / "VERSION"
    if not path.is_file():
        return "0.0.0"
    return path.read_text(encoding="utf-8").strip() or "0.0.0"


def _night_hours(night: dict[str, Any], text_key: str, hour_key: str) -> float:
    try:
        from logic import hhmm_to_hours
    except ImportError:
        from server.logic import hhmm_to_hours
    try:
        return hhmm_to_hours(str(night.get(text_key) or ""))
    except ValueError:
        return float(night.get(hour_key) or 0)


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            line = fmt % args
            if "/api/tiles/" in line or "/api/weather/" in line or "/api/aircraft" in line or "/api/controls" in line:
                return
            print(f"{self.address_string()} {line}", flush=True)

        def do_GET(self) -> None:  # noqa: N802
            try:
                self._get()
            except Exception:
                traceback.print_exc()
                self._json({"error": "Internal error"}, 500)

        def do_POST(self) -> None:  # noqa: N802
            try:
                self._post()
            except Exception:
                traceback.print_exc()
                self._json({"error": "Internal error"}, 500)

        def _get(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            if path in (
                "/generate_204",
                "/gen_204",
                "/hotspot-detect.html",
                "/library/test/success.html",
                "/connecttest.txt",
                "/ncsi.txt",
                "/success.txt",
            ):
                self.send_response(302)
                self.send_header("Location", "/setup")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path in ("/setup", "/setup/"):
                app.touch_activity()
                self._file(ROOT / "setup" / "index.html", "text/html; charset=utf-8")
                return
            if self.server.server_address[1] == 80 and path in ("", "/"):
                self._file(ROOT / "setup" / "index.html", "text/html; charset=utf-8")
                return
            if path == "/api/health":
                self._json(
                    {
                        "ok": True,
                        "version": running_version(),
                        "demoLock": app.force_demo,
                        "gpioError": app.gpio.last_error,
                        "backlightNodes": app.backlight_nodes(),
                    }
                )
                return
            if path == "/api/config":
                self._json(app.snapshot())
                return
            if path == "/api/basemaps":
                public = {
                    name: {
                        "minZoom": spec["minZoom"],
                        "maxZoom": spec["maxZoom"],
                        "attribution": spec["attribution"],
                        "attributionUrl": spec["attributionUrl"],
                        "labels": bool(spec.get("labelTemplate")),
                    }
                    for name, spec in BASEMAPS.items()
                }
                self._json(public)
                return
            if path == "/api/aircraft":
                freeze = query.get("freeze", ["0"])[0] in ("1", "true")
                self._json(app.aircraft(freeze, app.requested_range(query.get("range", [None])[0])))
                return
            if path == "/api/weather":
                self._json(app.weather_index())
                return
            if path == "/api/metar":
                cfg = app.snapshot()
                try:
                    lat = float(query.get("lat", [cfg["home"]["lat"]])[0])
                    lon = float(query.get("lon", [cfg["home"]["lon"]])[0])
                except ValueError:
                    self._json({"error": "Bad coordinates"}, 400)
                    return
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    self._json({"error": "Bad coordinates"}, 400)
                    return
                body = app.metar(lat, lon, str(cfg.get("metarStation") or ""))
                self._json({"metar": body})
                return
            if path == "/api/wifi":
                if not self._allowed(app):
                    return
                self._json(app.wifi())
                return
            if path == "/api/wifi/scan":
                if not self._allowed(app):
                    return
                rescan = query.get("rescan", ["1"])[0] != "0"
                self._json({"networks": wifi_scan(rescan=rescan)})
                return
            if path == "/api/airports":
                self._json({"airports": search_airports(query.get("q", [""])[0])})
                return
            if path == "/api/receiver":
                if not app.receiver_cache.get("ok"):
                    app.aircraft(False)
                self._json(app.receiver_cache)
                return
            if path == "/api/night":
                self._json(app.night_status())
                return
            if path == "/api/nearest":
                from airports import nearest_airport
                cfg = app.snapshot()
                try:
                    lat = float(query.get("lat", [cfg["home"]["lat"]])[0])
                    lon = float(query.get("lon", [cfg["home"]["lon"]])[0])
                except ValueError:
                    self._json({"error": "Bad coordinates"}, 400)
                    return
                self._json({"airport": nearest_airport(lat, lon)})
                return
            if path == "/api/updates":
                self._json(app.update_view())
                return
            if path == "/api/auth":
                self._json({"required": app.auth_record() is not None})
                return
            if path == "/api/controls":
                self._json({"events": app.gpio.drain(), "error": app.gpio.last_error})
                return
            if path.startswith("/api/tiles/"):
                self._tile(path, query)
                return
            if path.startswith("/api/weather/"):
                self._weather_tile(path)
                return
            self._static(path)

        def _post(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length > 65536:
                self._json({"error": "Body too large"}, 413)
                return
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                self._json({"error": "Invalid JSON"}, 400)
                return
            if not self._allowed(app) and parsed.path != "/api/login":
                return
            if parsed.path == "/api/login":
                if app.check_password(str(payload.get("password") or "")):
                    token = app.open_session()
                    self.send_response(200)
                    body = json.dumps({"ok": True}).encode("utf-8")
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Set-Cookie", f"ft_session={token}; HttpOnly; SameSite=Lax; Path=/")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self._json({"error": "Wrong password."}, 401)
                return
            if parsed.path == "/api/activity":
                app.touch_activity()
                self._json({"ok": True})
                return
            if parsed.path == "/api/updates/check":
                self._json(app.check_updates())
                return
            if parsed.path == "/api/updates/install":
                ok, detail = app.install_update()
                self._json(app.update_view(ok=ok, detail=detail) if ok else app.update_view(ok=ok, detail=detail, error=detail), 202 if ok else 409)
                return
            if parsed.path == "/api/updates/token":
                # 1.0.7: updates are tokenless; the old endpoint saves nothing.
                saved = app.update_view(ok=False, error="Updates no longer need an access key.")
                self._json(saved, 200 if saved.get("ok") else 400)
                return
            if parsed.path == "/api/updates/later":
                ok, detail = app.defer_update(str(payload.get("version") or ""), str(payload.get("source") or "later"))
                self._json(app.update_view(ok=ok, detail=detail, **({} if ok else {"error": detail})), 200 if ok else 409)
                return
            if parsed.path == "/api/updates/schedule/cancel":
                ok, detail = app.cancel_update_schedule()
                self._json(app.update_view(ok=ok, detail=detail), 200 if ok else 409)
                return
            if parsed.path == "/api/updates/later-at":
                ok, detail = app.set_later_at(payload.get("laterAt"))
                self._json(app.update_view(ok=ok, detail=detail, **({} if ok else {"error": detail})), 200 if ok else 400)
                return
            if parsed.path == "/api/updates/auto":
                saved, errors = app.set_auto_update(bool(payload.get("auto")))
                if errors or saved is None:
                    self._json(app.update_view(ok=False, errors=errors, error=" ".join(errors)), 400)
                    return
                self._json(app.update_view(ok=True))
                return
            if parsed.path in ("/api/config", "/api/brightness", "/api/display/restart", "/api/feed/test", "/api/wifi/connect", "/api/wifi/country", "/api/config/reset"):
                app.touch_activity()
            if parsed.path == "/api/config":
                cfg, errors = app.update_config(payload)
                if errors:
                    self._json({"errors": errors}, 400)
                    return
                self._json(cfg)
                return
            if parsed.path == "/api/brightness":
                try:
                    percent = float(payload.get("brightness"))
                except (TypeError, ValueError):
                    self._json({"error": "brightness required"}, 400)
                    return
                cfg = app.snapshot()
                cfg["brightness"] = percent
                saved, errors = app.update_config(cfg)
                if errors or saved is None:
                    self._json({"errors": errors}, 400)
                    return
                self._json({"brightness": saved["brightness"], "hardware": app.backlight_nodes() != []})
                return
            if parsed.path == "/api/config/reset":
                self._json(app.reset_config())
                return
            if parsed.path == "/api/display/restart":
                ok, detail = app.restart_display()
                self._json({"ok": ok, "detail": detail}, 200 if ok else 202)
                return
            if parsed.path == "/api/feed/test":
                self._json(app.test_feed(payload if payload else None))
                return
            if parsed.path == "/api/wifi/connect":
                country = str((app.snapshot().get("wifi") or {}).get("country") or "US")
                # The password is passed to the root helper on stdin and is
                # never printed or logged (log_message records only the path).
                ok, detail = connect_wifi(
                    str(payload.get("ssid") or ""),
                    str(payload.get("password") or ""),
                    hidden=bool(payload.get("hidden")),
                    country=country,
                )
                self._json({"ok": ok, "detail": detail, "wifi": app.wifi()}, 200 if ok else 400)
                return
            if parsed.path == "/api/wifi/country":
                country = str(payload.get("country") or "").strip().upper()
                ok, detail = set_country(country)
                if ok:
                    cfg = app.snapshot()
                    cfg.setdefault("wifi", {})["country"] = country
                    app.update_config(cfg)
                self._json({"ok": ok, "detail": detail}, 200 if ok else 400)
                return
            self._json({"error": "Not found"}, 404)

        def _allowed(self, app: App) -> bool:
            if app.auth_record() is None or self.client_address[0] in ("127.0.0.1", "::1"):
                return True
            token = ""
            for part in (self.headers.get("Cookie") or "").split(";"):
                name, _, value = part.strip().partition("=")
                if name == "ft_session":
                    token = value
            if app.session_ok(token):
                return True
            self._json({"error": "Sign in required."}, 401)
            return False

        def _file(self, path: Path, mime: str) -> None:
            if not path.is_file():
                self._json({"error": "Not found"}, 404)
                return
            self._bytes(path.read_bytes(), mime, 0)

        def _tile(self, path: str, query: dict[str, list[str]]) -> None:
            parts = path.strip("/").split("/")
            # api tiles style z x y.png
            if len(parts) != 6 or not parts[5].endswith(".png"):
                self._json({"error": "Bad tile"}, 400)
                return
            _, _, style, zs, xs, ys = parts
            spec = BASEMAPS.get(style)
            labels = query.get("layer", ["base"])[0] == "labels"
            template = spec.get("labelTemplate") if spec and labels else (spec or {}).get("template")
            if spec is None or not template:
                self._json({"error": "Unknown map"}, 404)
                return
            try:
                z, x, y = int(zs), int(xs), int(ys[: -4])
            except ValueError:
                self._json({"error": "Bad tile"}, 400)
                return
            if not valid_tile(z, x, y, int(spec["minZoom"]), int(spec["maxZoom"])):
                self._json({"error": "Tile out of range"}, 404)
                return
            folder = f"{style}-labels" if labels else style
            dest = cache_path(app.cache, "maps", folder, str(z), str(x), f"{y}.png")
            url = str(template).format(z=z, x=x, y=y)
            data = cached_fetch(app.cache, dest, url, float(spec["maxAge"]))
            if data is None:
                self._json({"error": "Tile unavailable"}, 404)
                return
            self._bytes(data, sniff_type(data), 86400)

        def _weather_tile(self, path: str) -> None:
            parts = path.strip("/").split("/")
            # api weather frame z x y.png
            if len(parts) != 6 or not parts[5].endswith(".png"):
                self._json({"error": "Bad tile"}, 400)
                return
            _, _, frame, zs, xs, ys = parts
            try:
                z, x, y = int(zs), int(xs), int(ys[: -4])
            except ValueError:
                self._json({"error": "Bad tile"}, 400)
                return
            status, data = app.weather_tile(frame, z, x, y)
            if status != 200 or not isinstance(data, bytes):
                self._json({"error": str(data)}, status)
                return
            self._bytes(data, sniff_type(data), 300)

        def _static(self, path: str) -> None:
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            if ".." in rel.split("/"):
                self._json({"error": "Not found"}, 404)
                return
            candidate = (app.dist / rel).resolve()
            dist = app.dist.resolve()
            if not str(candidate).startswith(str(dist)) or not candidate.is_file():
                self._json({"error": "Not found"}, 404)
                return
            data = candidate.read_bytes()
            mime = MIME.get(candidate.suffix.lower(), "application/octet-stream")
            cache = 0 if candidate.name == "index.html" else 86400
            self._bytes(data, mime, cache)

        def _json(self, payload: Any, status: int = 200) -> None:
            data = json.dumps(payload).encode("utf-8")
            self._bytes(data, "application/json; charset=utf-8", 0, status)

        def _bytes(self, data: bytes, mime: str, cache_seconds: int, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store" if cache_seconds <= 0 else f"public, max-age={cache_seconds}")
            self.end_headers()
            self.wfile.write(data)

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Flight Tracker display server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8741)
    parser.add_argument("--http-port", type=int, default=80, help="Setup page port. 0 disables it.")
    parser.add_argument("--demo", action="store_true", help="Play the bundled sample tracks")
    parser.add_argument("--config", default=str(ROOT / "data" / "config.json"))
    parser.add_argument("--cache", default=str(ROOT / "data" / "cache"))
    parser.add_argument("--dist", default=str(ROOT / "dist"))
    parser.add_argument("--sample", default=str(ROOT / "data" / "sample-aircraft.json"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = App(args)
    handler = make_handler(app)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    extra = None
    if args.http_port and args.http_port != args.port:
        try:
            extra = ThreadingHTTPServer((args.host, args.http_port), handler)
        except OSError as exc:
            print(f"Setup port {args.http_port} is not available ({exc}). Use http://{args.host}:{args.port}/setup", flush=True)
    app.start_update_scheduler()
    mode = "demo" if app.force_demo and not app.feed_overridden else app.config["feed"]["mode"]
    print(f"Flight Tracker display on http://{args.host}:{args.port}  feed={mode}", flush=True)
    if extra:
        print(f"Setup page on http://{args.host}:{args.http_port}/", flush=True)
        threading.Thread(target=extra.serve_forever, name="flight-tracker-setup", daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.gpio.close()
        server.server_close()
        if extra:
            extra.server_close()


if __name__ == "__main__":
    main()
