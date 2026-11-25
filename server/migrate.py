#!/usr/bin/env python3
"""Config migrations for Flight Tracker.

The updater runs this file from the new release before it restarts the
service. Each step must leave a config the previous release can still read,
so a rollback does not depend on reversing the migration. The updater also
keeps a copy of the config and restores it if the new release fails.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA = 4
PUBLIC_REPO = "MFG001/flight-tracker"
PUBLIC_MANIFEST_URL = f"https://github.com/{PUBLIC_REPO}/releases/latest/download/manifest.json"
OLD_SWEEP_SEC = 4
NEW_SWEEP_SEC = 8
DEFAULT_LOCAL_PATH = "/run/readsb/aircraft.json"


def migrate_update_source(cfg: dict[str, Any]) -> None:
    """1.0.7: tokenless updates from the public repo. The private releases
    repo (and its token) is left behind; any other self-hosted URL is kept."""
    updates = cfg.get("updates")
    if not isinstance(updates, dict):
        return
    url = str(updates.get("url") or "")
    if not url or "/flight-tracker-updates/" in url or url.rstrip("/").endswith("/flight-tracker-updates"):
        updates["url"] = PUBLIC_MANIFEST_URL
        updates["repo"] = PUBLIC_REPO
    updates.setdefault("channel", "stable")


def migrate_range(cfg: dict[str, Any]) -> None:
    """1.0.8: steps are 10, 20, 30, 40, 50, 75, 100 NM. A saved 2 or 5 (or any
    other value not in that list) snaps to the nearest remaining step; anything
    below 10 becomes 10. 1.0.7 can still read 10, so a rollback stays valid."""
    try:
        from rings import snap_range
    except ImportError:
        from server.rings import snap_range
    cfg["rangeNm"] = snap_range(cfg.get("rangeNm"))


def migrate_rings(cfg: dict[str, Any]) -> None:
    """1.0.8: the shipped default of 4 rings is now Auto, so 30/50/75 NM get
    even, round labels (10/20/30, 10/20/30/40/50, 25/50/75). A unit that
    already chose 2, 3, 5 or 6 keeps it. 0 is stored only after a successful
    1.0.8 install (a rollback restores the previous file)."""
    if cfg.get("rings") == 4:
        cfg["rings"] = 0


def migrate_config(cfg: dict[str, Any], path_exists: Any = None) -> dict[str, Any]:
    try:
        from logic import migrate_default_metar_station
    except ImportError:
        from server.logic import migrate_default_metar_station

    migrate_update_source(cfg)
    migrate_range(cfg)
    migrate_rings(cfg)

    schema = int(cfg.get("schema") or 0)
    if schema < 1:
        cfg["schema"] = 1
        schema = 1
    if schema < 2:
        # 1.0.1 adds the adsb.fi internet feed as the default. A unit still on
        # the untouched local default with no receiver file moves to it; a unit
        # with a receiver, a remote URL, or demo keeps its choice.
        exists = path_exists or (lambda p: Path(p).is_file())
        feed = cfg.get("feed")
        if (
            isinstance(feed, dict)
            and feed.get("mode") == "local"
            and feed.get("localPath") == DEFAULT_LOCAL_PATH
            and not exists(DEFAULT_LOCAL_PATH)
        ):
            feed["mode"] = "adsbfi"
        cfg["schema"] = 2
        schema = 2
    if schema < 3:
        # 1.0.2 halves the sweep base rate. A unit still on the old 4 s default
        # moves to 8 s; any other chosen speed is kept. Display rotation and
        # Wi-Fi country get their defaults when missing.
        sweep = cfg.get("sweep")
        if isinstance(sweep, dict) and sweep.get("periodSec") in (OLD_SWEEP_SEC, float(OLD_SWEEP_SEC)):
            sweep["periodSec"] = NEW_SWEEP_SEC
        display = cfg.get("display")
        if not isinstance(display, dict):
            display = {}
            cfg["display"] = display
        display.setdefault("rotation", 270)
        display.setdefault("output", "DSI-1")
        display.setdefault("touchDevice", "10-0014 Goodix Capacitive TouchScreen")
        display.setdefault("touchMatrix", False)
        wifi = cfg.get("wifi")
        if not isinstance(wifi, dict):
            wifi = {}
            cfg["wifi"] = wifi
        wifi.setdefault("country", "US")
        # Weather radar (RainViewer, IEM fallback) needs no key. 1.0.0/1.0.1
        # shipped it off with no setup-page switch, so turn it on once for
        # units still on that default. The new setup toggle can turn it off.
        weather = cfg.get("weather")
        if isinstance(weather, dict) and weather.get("enabled") is False:
            weather["enabled"] = True
        cfg["schema"] = 3
        schema = 3
    if schema < 4:
        # 1.0.15: METAR was shipped as KJFK and did not follow a later home
        # change. Point leftover defaults at the home airport, or nearest
        # for a lat/lon home. An explicit station other than KJFK is kept.
        migrate_default_metar_station(cfg)
        cfg["schema"] = 4
    return cfg


def post_update_system_steps(config_path: Path) -> list[str]:
    """Steps a signed update applies outside /opt/flight-tracker/current.

    The updater of every release so far (1.0.0+) runs this file from the NEW
    release, as root, before it switches ``current``. That makes it the hook
    that reaches units updating from an older updater. Each step is best
    effort and never fails the update.
    """
    notes: list[str] = []
    here = Path(__file__).resolve().parent
    import subprocess
    import sys

    display = here / "display_setup.py"
    if display.is_file():
        result = subprocess.run(
            [sys.executable, str(display), "--config", str(config_path)],
            check=False, capture_output=True, text=True, timeout=60,
        )
        notes.append((result.stdout or result.stderr or "").strip())
    # The kiosk keeps running the old kiosk.sh until it restarts. Restart it
    # after the updater has switched releases and checked health.
    if Path("/run/systemd/system").is_dir():
        subprocess.run(
            ["systemd-run", "--collect", "--quiet", "--unit=flight-tracker-kiosk-refresh",
             "--on-active=120", "/usr/bin/systemctl", "restart", "flight-tracker-kiosk.service"],
            check=False, capture_output=True, timeout=20,
        )
        notes.append("Kiosk restart scheduled in 2 minutes.")
        # 1.0.7: once this release has proved healthy, move the server to its
        # own service account. If the update is rolled back, the older
        # updater.py does not know --harden and this does nothing.
        subprocess.run(["systemctl", "reset-failed", "flight-tracker-harden.service"], check=False, capture_output=True, timeout=20)
        subprocess.run(
            ["systemd-run", "--collect", "--quiet", "--unit=flight-tracker-harden",
             "--description=Flight Tracker service account move", "--on-active=300",
             "/usr/bin/python3", "/opt/flight-tracker/current/server/updater.py", "--harden"],
            check=False, capture_output=True, timeout=20,
        )
        notes.append("Service account move scheduled in 5 minutes.")
    return notes


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate a Flight Tracker config file in place")
    parser.add_argument("--config", required=True)
    parser.add_argument("--no-system", action="store_true", help="Only migrate the JSON file")
    args = parser.parse_args()
    path = Path(args.config)
    import os
    import tempfile

    # Runs as root inside a folder the server account can write: never follow
    # a planted symlink, and replace the file through a fresh O_EXCL temp file.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as handle:
        cfg = json.loads(handle.read(4 * 1024 * 1024).decode("utf-8"))
    if not isinstance(cfg, dict):
        raise SystemExit("Config must be a JSON object")
    updated = migrate_config(cfg)
    before = os.lstat(path)
    fd, temporary = tempfile.mkstemp(prefix=".config.json.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(updated, indent=2) + "\n")
        os.chmod(temporary, before.st_mode & 0o777)
        if os.geteuid() == 0:
            os.chown(temporary, before.st_uid, before.st_gid)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise

    if not args.no_system and hasattr(os, "geteuid") and os.geteuid() == 0 and path.resolve() == Path("/etc/flight-tracker/config.json"):
        try:
            for note in post_update_system_steps(path):
                if note:
                    print(note)
        except Exception as exc:  # never block an update on panel setup
            print(f"Display setup skipped: {exc}")


if __name__ == "__main__":
    main()
