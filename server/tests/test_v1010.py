"""1.0.10: map-block altitude without ft, larger helicopter icons, Wi-Fi QR test."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

try:
    from server.tests.test_v103 import _exe, run_ts  # noqa: E402
except ImportError:
    from test_v103 import _exe, run_ts  # type: ignore  # noqa: E402

import updater as up  # noqa: E402

SPACED_SSID = "Home Net "


class VersionPinTests(unittest.TestCase):
    def test_version_is_at_least_1010(self) -> None:
        # 1.0.11 moved on; test_v1011 pins the exact number.
        version = (ROOT / "VERSION").read_text().strip()
        self.assertGreaterEqual(tuple(int(x) for x in version.split(".")), (1, 0, 10))


class BlockAltitudeTests(unittest.TestCase):
    def test_map_block_drops_ft_keeps_gnd_fl_metric_and_detail_ft(self) -> None:
        fmt = (ROOT / "src/format.ts").read_text()
        radar = (ROOT / "src/radar.ts").read_text()
        main = (ROOT / "src/main.ts").read_text()
        self.assertIn('return `${(Math.round(Math.max(0, ft) / 100) * 100).toLocaleString("en-US")}`;', fmt)
        self.assertNotIn('} ft`;', fmt)
        self.assertIn('return `${Math.round(ft).toLocaleString("en-US")} FT`;', fmt)
        self.assertIn('["ALTITUDE", formatAltitude(item.altFt, item.ground, config.units)]', main)
        # 1.0.13: map labels no longer draw a data block; the formatter remains for tests / reuse.
        self.assertNotIn("const line2 = dataBlockLine", radar)
        self.assertIn("mapLabelIdent", radar)
        self.assertIn("export function dataBlockLine", fmt)
        data = run_ts("""
import { blockAltitude, dataBlockLine, formatAltitude, listAltitude } from "./src/format.ts";
console.log(JSON.stringify([
  blockAltitude(3420, false, "aviation"),
  blockAltitude(34000, false, "aviation"),
  blockAltitude(18000, false, "imperial"),
  blockAltitude(0, true, "aviation"),
  blockAltitude(null, false, "aviation"),
  blockAltitude(3420, false, "metric"),
  dataBlockLine(12480, false, 1500, 250, "aviation"),
  dataBlockLine(5000, false, null, null, "aviation"),
  formatAltitude(3400, false, "aviation"),
  listAltitude(3400, false, "aviation"),
]));
""")
        self.assertEqual(data, [
            "3,400", "FL340", "FL180", "GND", "ALT ---", "1,042 m",
            "12,500▲ 250", "5,000", "3,400 FT", "3,400",
        ])
        for value in data:
            self.assertNotRegex(value, r"\bft\b")


class RotorIconTests(unittest.TestCase):
    def test_helicopter_scaled_in_every_set_others_unchanged(self) -> None:
        icons = (ROOT / "src/icons.ts").read_text()
        self.assertIn("export const ROTOR_ICON_SCALE = 1.22;", icons)
        self.assertIn('if (kind === "rotor" || mark === "rotor")', icons)
        self.assertIn("ctx.scale(ROTOR_ICON_SCALE, ROTOR_ICON_SCALE);", icons)
        line = next(row for row in icons.splitlines() if row.startswith("export const ROTOR_ICON_SCALE"))
        scale = float(line.split("=")[1].strip().rstrip(";"))
        self.assertGreaterEqual(scale, 1.20)
        self.assertLessEqual(scale, 1.25)
        # Scale is applied once, around the shared paint path, so every
        # helicopter is covered and non-rotor kinds are not scaled.
        paint = icons[icons.index("export function paintAircraftIcon") : icons.index("function markFromKind")]
        self.assertEqual(paint.count("ctx.scale(ROTOR_ICON_SCALE, ROTOR_ICON_SCALE);"), 1)
        self.assertIn('kind === "rotor" || mark === "rotor"', paint)


class WifiPromptTests(unittest.TestCase):
    def test_hotspot_after_connected_reopens_dismissed_card(self) -> None:
        main = (ROOT / "src/main.ts").read_text()
        self.assertIn("wifiDismissed = false;", main)
        self.assertIn('if (outage && !["hotspot", "portal"].includes(wifiSeen))', main)
        self.assertIn("if (outage && !wifiDismissed)", main)
        self.assertIn('const outage = state === "hotspot" || state === "portal";', main)


class WifiCardLayoutTests(unittest.TestCase):
    def test_qr_is_sharp_square_with_quiet_zone(self) -> None:
        main = (ROOT / "src/main.ts").read_text()
        css = (ROOT / "src/style.css").read_text()
        index = (ROOT / "index.html").read_text()
        self.assertIn("const WIFI_QR_CSS_PX = 240;", main)
        self.assertIn("const WIFI_QR_MARGIN_MODULES = 4;", main)
        self.assertIn("const WIFI_CONNECTED_TIMEOUT_MS = 120_000;", main)
        self.assertIn("Math.round(css * dpr)", main)
        self.assertIn("wifiQr.style.width = `${css}px`;", main)
        self.assertNotIn("width: 280", main)
        self.assertNotIn("margin: 1,", main)
        self.assertIn("wifi-overlay", index)
        self.assertIn('id="wifi-close"', index)
        self.assertNotIn('<ol id="wifi-steps">', index)
        self.assertIn("#wifi-qr", css)
        self.assertIn("width: 240px;", css)
        self.assertNotIn("border-radius: 50%", css[css.index(".qr-card") : css.index("#wifi-qr")])
        self.assertIn("function dismissWifi()", main)
        self.assertIn("armConnectedAutoClose()", main)
        self.assertIn('if (disc && !disc.contains(event.target as Node)) dismissWifi();', main)
        self.assertIn("Join setup", main)
        self.assertIn("Scan to join FlightTracker-Setup.", main)
        self.assertNotIn("Connected — configure at", main)

    def test_safe_circle_covers_all_wifi_views(self) -> None:
        script = (ROOT / "scripts/check-safe-circle.mjs").read_text()
        self.assertIn('for (const view of ["hotspot", "portal", "connected"])', script)
        self.assertIn("checkWifiFit", script)


class HelperInstallTests(unittest.TestCase):
    def test_wrapper_and_install_sh(self) -> None:
        wrapper = ROOT / "deploy/flight-tracker-wifi-test"
        text = wrapper.read_text()
        self.assertTrue(os.access(wrapper, os.X_OK))
        self.assertIn("wifi-ctl.sh test-hotspot", text)
        self.assertIn("exec /opt/flight-tracker/current/scripts/wifi-ctl.sh", text)
        install = (ROOT / "install.sh").read_text()
        self.assertIn('install -m 0755 "$ROOT/deploy/flight-tracker-wifi-test" /usr/local/sbin/flight-tracker-wifi-test', install)
        # Users run sudo themselves; the service account does not get NOPASSWD.
        sudoers = install[install.index("SUDOERS=") : install.index("chmod 0440")]
        self.assertNotIn("flight-tracker-wifi-test", sudoers)

    def test_ota_creates_missing_wifi_test_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = Path(tmp) / "r"
            sbin = Path(tmp) / "sbin"
            (release / "deploy").mkdir(parents=True)
            sbin.mkdir()
            src = (ROOT / "deploy/flight-tracker-wifi-test").read_text()
            (release / "deploy" / "flight-tracker-wifi-test").write_text(src)
            (release / "deploy" / "flight-tracker-wifi").write_text("#!/bin/sh\n")
            (release / "deploy" / "flight-tracker-brightness").write_text("#!/bin/sh\n")
            self.assertFalse((sbin / "flight-tracker-wifi-test").exists())
            installed = up.refresh_helpers(release, sbin)
            self.assertIn("flight-tracker-wifi-test", installed)
            dest = sbin / "flight-tracker-wifi-test"
            self.assertTrue(dest.is_file())
            self.assertEqual(dest.read_text(), src)
            self.assertTrue(os.access(dest, os.X_OK))


class WifiTestHotspotTests(unittest.TestCase):
    """scripts/wifi-ctl.sh test-hotspot against a fake nmcli."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        (self.tmp / "profiles").write_text(f"{SPACED_SSID}:802-11-wireless\nWired connection 1:802-3-ethernet\n", encoding="utf-8")
        (self.tmp / "active").write_text(f"{SPACED_SSID}\nWired connection 1\n", encoding="utf-8")
        self.password = "ABCD2345"
        self.hotspot_json = self.tmp / "hotspot.json"
        self.hotspot_json.write_text(json.dumps({"ssid": "FlightTracker-Setup", "password": self.password}), encoding="utf-8")
        self.test_dir = self.tmp / "wifitest"
        self.test_dir.mkdir()
        t = self.tmp
        _exe(t, "nmcli", f'''
{{ printf '%s' "CALL"; for a in "$@"; do printf '|%s' "$a"; done; printf '\\n'; }} >> {t}/calls
if [[ "$*" == "-t -f NAME,TYPE connection show" ]]; then cat {t}/profiles; exit 0; fi
if [[ "$1" == "-g" && "$2" == "802-11-wireless.mode" ]]; then
  name="${{@: -1}}"
  if [[ "$name" == "Hotspot" || "$name" == "FlightTracker-Setup" ]]; then echo ap; else echo infrastructure; fi
  exit 0
fi
if [[ "$*" == "-t -f NAME connection show --active" ]]; then cat {t}/active; exit 0; fi
if [[ "$1" == "dev" && "$2" == "wifi" && "$3" == "hotspot" ]]; then
  grep -qxF "FlightTracker-Setup:802-11-wireless" {t}/profiles || echo "FlightTracker-Setup:802-11-wireless" >> {t}/profiles
  printf '%s\\n' "FlightTracker-Setup" "Wired connection 1" > {t}/active
  exit 0
fi
if [[ "$1" == "connection" && "$2" == "up" && "$3" == "id" ]]; then
  name="$4"
  if [[ "$name" == "FlightTracker-Setup" || "$name" == "Hotspot" ]]; then
    printf '%s\\n' "$name" "Wired connection 1" > {t}/active
  else
    printf '%s\\n' "$name" "Wired connection 1" > {t}/active
  fi
  exit 0
fi
if [[ "$1" == "connection" && "$2" == "down" && "$3" == "id" ]]; then
  grep -Fxv -- "$4" {t}/active > {t}/active.tmp || true
  mv {t}/active.tmp {t}/active
  exit 0
fi
exit 0
''')
        _exe(t, "systemctl", f'''
echo "SYSTEMCTL $*" >> {t}/calls
if [[ "$1" == "is-active" ]]; then exit 1; fi
exit 0
''')
        _exe(t, "systemd-run", f'''
{{ printf '%s' "CALL"; for a in "$@"; do printf '|%s' "$a"; done; printf '\\n'; }} >> {t}/systemd-run.log
exit 0
''')
        _exe(t, "logger", "exit 0\n")
        self.env = {
            "PATH": f"{t}:/usr/bin:/bin",
            "FT_WIFI_SETTLE": "0",
            "FT_WIFI_TEST_DIR": str(self.test_dir),
            "FT_HOTSPOT_JSON": str(self.hotspot_json),
            "FT_SERVER_DIR": str(ROOT / "server"),
            "FT_WIFI_TEST_RETRY_SLEEP": "0",
            "FT_WIFI_TEST_POLL": "0.05",
            "FT_WIFI_TEST_HOTSPOT_WAIT": "0",
            "FT_WIFI_TEST_SECONDS": "0",
        }

    def calls(self) -> list[list[str]]:
        path = self.tmp / "calls"
        if not path.is_file():
            return []
        return [line.split("|")[1:] for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("CALL")]

    def run_ctl(self, *args: str, env: dict[str, str] | None = None, timeout: float = 20) -> subprocess.CompletedProcess[str]:
        merged = dict(self.env)
        if env:
            merged.update(env)
        return subprocess.run(
            ["bash", str(ROOT / "scripts/wifi-ctl.sh"), *args],
            env=merged, capture_output=True, text=True, timeout=timeout,
        )

    def assert_no_password(self, result: subprocess.CompletedProcess[str]) -> None:
        blob = result.stdout + result.stderr
        self.assertNotIn(self.password, blob)

    def assert_profile_untouched(self) -> None:
        for c in self.calls():
            if c[:3] == ["connection", "modify", "id"] and c[3] == SPACED_SSID:
                self.fail(f"client profile was modified: {c}")
            if c[:3] == ["connection", "delete", "id"] and c[3] == SPACED_SSID:
                self.fail(f"client profile was deleted: {c}")
            if len(c) >= 2 and c[0] == "connection" and "delete" in c:
                if SPACED_SSID in c:
                    self.fail(f"client profile was deleted: {c}")

    def test_reverts_to_trailing_space_profile(self) -> None:
        result = self.run_ctl("test-hotspot", "10", env={"FT_WIFI_TEST_FOREGROUND": "1"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_no_password(result)
        calls = self.calls()
        start = next(c for c in calls if c[:3] == ["dev", "wifi", "hotspot"])
        self.assertEqual(start[6], "FlightTracker-Setup")
        self.assertEqual(start[8], "FlightTracker-Setup")
        # Password is passed to nmcli but must not be printed by the helper.
        self.assertEqual(start[start.index("password") + 1], self.password)
        ups = [c for c in calls if c[:4] == ["connection", "up", "id", SPACED_SSID]]
        self.assertTrue(ups, f"never restored {SPACED_SSID!r}: {calls}")
        downs = [c for c in calls if c[:3] == ["connection", "down", "id"] and c[3] in ("FlightTracker-Setup", "Hotspot")]
        self.assertTrue(downs)
        self.assert_profile_untouched()
        self.assertIn("Restored the original Wi-Fi profile.", result.stdout)
        recorded = (self.test_dir / "profile").read_text(encoding="utf-8")
        # The file may have been removed after restore; if it remains, it is exact.
        if recorded:
            self.assertEqual(recorded, SPACED_SSID + "\n")

    def test_stop_reverts_early(self) -> None:
        proc = subprocess.Popen(
            ["bash", str(ROOT / "scripts/wifi-ctl.sh"), "test-hotspot", "30"],
            env={**self.env, "FT_WIFI_TEST_FOREGROUND": "1", "FT_WIFI_TEST_SECONDS": "20"},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        # Wait until the test is actually running, then stop it.
        for _ in range(50):
            if (self.test_dir / "running").is_file():
                break
            time.sleep(0.05)
        else:
            proc.kill()
            out, err = proc.communicate(timeout=5)
            self.fail(f"test never started: {out}{err}")
        stop = self.run_ctl("test-hotspot", "--stop")
        self.assertEqual(stop.returncode, 0, stop.stdout + stop.stderr)
        self.assert_no_password(stop)
        try:
            stdout, stderr = proc.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            self.fail(f"test did not exit after --stop: {stdout}{stderr}")
        self.assertEqual(proc.returncode, 0, stdout + stderr)
        self.assert_no_password(subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr))
        ups = [c for c in self.calls() if c[:4] == ["connection", "up", "id", SPACED_SSID]]
        self.assertTrue(ups)
        self.assert_profile_untouched()

    def test_systemd_run_keeps_trailing_space_and_hides_password(self) -> None:
        result = self.run_ctl("test-hotspot", "12")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_no_password(result)
        raw = (self.tmp / "systemd-run.log").read_text(encoding="utf-8")
        self.assertNotIn(self.password, raw)
        self.assertIn("--unit=flight-tracker-wifi-test", raw)
        self.assertIn("--collect", raw)
        self.assertIn("FT_WIFI_TEST_SUPERVISED=1", raw)
        self.assertIn(f"FT_WIFI_TEST_PROFILE={SPACED_SSID}", raw)
        self.assertIn("test-hotspot|12", raw.replace("\n", ""))
        self.assertIn("SSH session may drop", result.stdout)

    def test_rejects_invalid_minutes(self) -> None:
        result = self.run_ctl("test-hotspot", "45")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("1-30", result.stderr)
        self.assertFalse((self.tmp / "systemd-run.log").exists())


if __name__ == "__main__":
    unittest.main()
