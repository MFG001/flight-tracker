"""1.0.3: clean dial (no edge keys), screen settings on the setup page,
Save buttons on every setup card, alerts and trails that work, Zulu clock,
Wi-Fi fixes, and the Wi-Fi push-update script."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from server import wifi_net  # noqa: E402
from server.logic import BANDS, sanitize_config  # noqa: E402
from server.watchlist import filter_aircraft  # noqa: E402
from server.updater import pack_tree  # noqa: E402

HOME = {"home": {"name": "KJFK", "lat": 40.6399, "lon": -73.7787}, "rangeNm": 20}
SETUP = (ROOT / "setup/index.html").read_text(encoding="utf-8")
MAIN = (ROOT / "src/main.ts").read_text(encoding="utf-8")
CSS = (ROOT / "src/style.css").read_text(encoding="utf-8")
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")


def _exe(folder: Path, name: str, body: str) -> Path:
    path = folder / name
    path.write_text("#!/bin/bash\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def node_ts_ok() -> bool:
    if not shutil.which("node"):
        return False
    probe = subprocess.run(["node", "--experimental-strip-types", "-e", "1"], capture_output=True, text=True)
    return probe.returncode == 0


def run_ts(code: str) -> object:
    """Run an ES module snippet that imports ./src/*.ts with node's type stripping."""
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--no-warnings", "--input-type=module", "-e", code],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


class VersionTests(unittest.TestCase):
    def test_version_is_103_or_later(self) -> None:
        # 1.0.4 moved on; test_v104 pins the exact number. Everything still agrees.
        version = (ROOT / "VERSION").read_text().strip()
        self.assertGreaterEqual(tuple(int(x) for x in version.split(".")), (1, 0, 3))
        self.assertEqual(json.loads((ROOT / "package.json").read_text())["version"], version)
        lock = json.loads((ROOT / "package-lock.json").read_text())
        self.assertEqual(lock["version"], version)
        self.assertEqual(lock["packages"][""]["version"], version)


class NoEdgeKeysTests(unittest.TestCase):
    def test_no_edge_tab_buttons_on_the_glass(self) -> None:
        self.assertNotIn('id="keys"', INDEX)
        self.assertNotIn("BEZEL", MAIN)
        self.assertNotIn('className = "key"', MAIN)
        self.assertNotIn("key-label", MAIN + CSS)
        self.assertNotIn("#keys", CSS)
        for label in ("BRT", "MAP", "TFC", "WX", "MNU", "ALT", "NAV", "HDG"):
            self.assertNotIn(f">{label}<", INDEX)

    def test_tap_aircraft_hold_menu_remain(self) -> None:
        self.assertIn("radar.hitTest(", MAIN)
        self.assertIn("const HOLD_MS = 2000;", MAIN)
        self.assertIn("openMenu()", MAIN)
        # 1.0.12: the glass is locked on home; double-tap no longer recentres.
        self.assertNotIn("recenter()", MAIN)
        self.assertIn('id="m-traffic"', INDEX)
        self.assertIn('id="m-wifi"', INDEX)
        self.assertIn('id="m-touch"', INDEX)
        self.assertIn("#bottom .hold-target", CSS)
        # Automatic Wi-Fi setup QR when not connected stays.
        self.assertIn('if (outage && !wifiDismissed)', MAIN)

    def test_kiosk_applies_every_saved_setting(self) -> None:
        # 1.0.2 compared a fixed field list that missed trails, alerts, watch, night, brightness.
        self.assertIn("const changed = configKey(next) !== configKey(config);", MAIN)


class RangeSelectorTests(unittest.TestCase):
    def test_minus_range_plus_no_preset_bar(self) -> None:
        for needle in ('id="range-minus"', 'id="range"', 'id="range-plus"'):
            self.assertIn(needle, INDEX)
        self.assertNotIn("range-picker", INDEX)
        self.assertNotIn("range-picker", MAIN)
        self.assertNotIn("range-picker", CSS)
        self.assertIn('<div id="range" aria-live="polite">', INDEX)
        self.assertNotIn('aria-haspopup', INDEX)
        self.assertIn("rangeMinus.disabled = step <= 0;", MAIN)
        self.assertIn("rangePlus.disabled = step >= PRESETS.length - 1;", MAIN)
        self.assertIn("function stepRange(direction: 1 | -1)", MAIN)
        steps = (ROOT / "src/rings.ts").read_text()
        self.assertIn("export const RANGE_STEPS = [10, 20, 30, 40, 50, 75, 100]", steps)

    def test_finger_size_targets(self) -> None:
        # Only − and + are buttons; use the first .range-step block (not :disabled / :active).
        start = CSS.index("\n.range-step {")
        block = CSS[start:start + 220]
        self.assertIn("width: 40px;", block)
        self.assertIn("height: 40px;", block)

    def test_range_is_saved_and_does_not_bounce(self) -> None:
        self.assertIn("config.rangeNm = snapRange(rangeNm);", MAIN)
        self.assertIn("if (edits !== localEdits || saveTimer || saving) return;", MAIN)
        self.assertRegex(MAIN, r"function pickRange\(nm: number\): void \{[\s\S]{0,200}persist\(\);")


class ScreenSettingsTests(unittest.TestCase):
    def test_setup_has_brightness_orientation_altitude(self) -> None:
        self.assertIn('<input id="brightness" type="range" min="20" max="100" step="10" />', SETUP)
        self.assertIn('<option value="north">North Up</option>', SETUP)
        self.assertIn('<option value="track">Track Up</option>', SETUP)
        values = re.findall(r'<option value="([a-z]+)">', SETUP[SETUP.index('id="altitude-band"'):SETUP.index("</select>", SETUP.index('id="altitude-band"'))])
        self.assertEqual(tuple(values), BANDS)
        self.assertIn('"/api/brightness"', SETUP)
        self.assertIn("saveSlice({ orientation: $(\"orientation\").value, altitudeBand: $(\"altitude-band\").value })", SETUP)

    def test_validation(self) -> None:
        cfg, errors = sanitize_config(dict(HOME, brightness=5, orientation="track", altitudeBand="vhigh"))
        self.assertEqual(errors, [])
        self.assertEqual(cfg["brightness"], 20)
        self.assertEqual(cfg["orientation"], "track")
        self.assertEqual(cfg["altitudeBand"], "upper")
        self.assertEqual(sanitize_config(dict(HOME, brightness=150))[0]["brightness"], 100)
        self.assertTrue(sanitize_config(dict(HOME, brightness="bright"))[1])
        self.assertTrue(sanitize_config(dict(HOME, orientation="east"))[1])
        self.assertTrue(sanitize_config(dict(HOME, altitudeBand="space"))[1])


class SetupServer:
    """The real App and HTTP handler on a temporary config."""

    def __init__(self, test: unittest.TestCase) -> None:
        import server.flighttracker as ft
        self.ft = ft
        self.tmp = Path(tempfile.mkdtemp())
        test.addCleanup(shutil.rmtree, self.tmp, True)
        self.args = argparse.Namespace(
            dist=str(ROOT / "dist"), config=str(self.tmp / "config.json"), cache=str(self.tmp / "cache"),
            sample=str(ROOT / "data/sample-aircraft.json"), demo=True,
        )
        patch = mock.patch.object(ft.App, "apply_brightness", return_value=False)
        patch.start()
        test.addCleanup(patch.stop)
        self.app = ft.App(self.args)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ft.make_handler(self.app))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        test.addCleanup(self.server.server_close)
        test.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def get(self, path: str):
        with urllib.request.urlopen(self.base + path, timeout=10) as response:
            return json.loads(response.read())

    def post(self, path: str, body: dict):
        request = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())

    def save_slice(self, patch: dict):
        """Same as setup/index.html saveSlice: read, merge, post the whole config."""
        current = self.get("/api/config")
        current.update(patch)
        return self.post("/api/config", current)

    def reloaded(self):
        return self.ft.App(self.args).snapshot()


class EndToEndSaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.srv = SetupServer(self)

    def test_screen_settings_persist(self) -> None:
        self.assertEqual(self.srv.post("/api/brightness", {"brightness": 55})["brightness"], 55)
        self.srv.save_slice({"orientation": "track", "altitudeBand": "mid"})
        cfg = self.srv.reloaded()
        self.assertEqual((cfg["brightness"], cfg["orientation"], cfg["altitudeBand"]), (55, "track", "mid"))
        self.assertEqual(self.srv.post("/api/brightness", {"brightness": 3})["brightness"], 20)

    def test_range_from_the_glass_persists(self) -> None:
        self.srv.save_slice({"rangeNm": 10})
        self.assertEqual(self.srv.reloaded()["rangeNm"], 10)
        self.srv.save_slice({"rangeNm": 33})
        self.assertEqual(self.srv.reloaded()["rangeNm"], 30)

    def test_alerts_persist(self) -> None:
        want = {"watch": True, "military": True, "emergency": True, "chime": False}
        saved = self.srv.save_slice({"alerts": want})
        self.assertEqual(saved["alerts"], want)
        self.assertEqual(self.srv.reloaded()["alerts"], want)
        self.srv.save_slice({"alerts": {"watch": False, "military": False, "emergency": True, "chime": True}})
        self.assertEqual(self.srv.reloaded()["alerts"], {"watch": False, "military": False, "emergency": True, "chime": True})

    def test_trails_persist_and_clamp(self) -> None:
        saved = self.srv.save_slice({"trails": {"enabled": True, "minutes": 7}})
        self.assertEqual(saved["trails"], {"enabled": True, "minutes": 7})
        self.assertEqual(self.srv.reloaded()["trails"], {"enabled": True, "minutes": 7})
        self.assertEqual(self.srv.save_slice({"trails": {"enabled": True, "minutes": 40}})["trails"]["minutes"], 10)
        self.assertEqual(self.srv.save_slice({"trails": {"enabled": False, "minutes": 3}})["trails"], {"enabled": False, "minutes": 3})

    def test_watch_weather_night_persist(self) -> None:
        self.srv.save_slice({"watch": {"enabled": True, "tails": ["N123AB", "AAL100"]}})
        self.srv.save_slice({"weather": {"enabled": False, "opacity": 0.4, "animate": True}})
        self.srv.save_slice({"night": {"mode": "schedule", "from": "2130", "to": "0545", "fromHour": 21, "toHour": 5, "brightness": 20}})
        cfg = self.srv.reloaded()
        self.assertEqual(cfg["watch"], {"enabled": True, "tails": ["N123AB", "AAL100"]})
        self.assertFalse(cfg["weather"]["enabled"])
        self.assertEqual(cfg["weather"]["opacity"], 0.4)
        self.assertEqual((cfg["night"]["mode"], cfg["night"]["from"], cfg["night"]["to"]), ("schedule", "2130", "0545"))

    def test_one_card_save_keeps_the_others(self) -> None:
        self.srv.save_slice({"trails": {"enabled": True, "minutes": 4}})
        self.srv.save_slice({"alerts": {"watch": True, "military": False, "emergency": True, "chime": False}})
        self.srv.save_slice({"orientation": "track"})
        cfg = self.srv.reloaded()
        self.assertEqual(cfg["trails"], {"enabled": True, "minutes": 4})
        self.assertTrue(cfg["alerts"]["watch"])


class SetupCardsTests(unittest.TestCase):
    def test_alert_labels_verbatim_and_centered(self) -> None:
        start = SETUP.index('<section id="alerts"')
        card = SETUP[start:SETUP.index("</section>", start)]
        self.assertIn('<div class="center-group">', card)
        labels = re.findall(r'type="checkbox" /> ([^<]+)</label>', card)
        self.assertEqual(labels, ["Watched Aircraft", "Military Aircraft", "Emergency (7500, 7600, 7700)", "Chime (if available)"])
        self.assertNotIn("enters", card.lower())

    def test_every_settings_card_has_save_and_status(self) -> None:
        for button, status in (("form-save", "status"), ("wx-save", "wx-status"), ("watch-save", "watch-status"),
                               ("alerts-save", "alerts-status"), ("trails-save", "trails-status"),
                               ("night-save", "night-status"), ("screen-save", "screen-status"), ("loc-save", "loc-status")):
            self.assertIn(f'id="{button}"', SETUP, button)
            self.assertIn(f'id="{status}"', SETUP, status)
            self.assertRegex(SETUP, re.escape(f'withSave($("{button}")') + r"[\s\S]{0,1600}?" + re.escape(f'$("{status}")'), button)

    def test_trails_card_shows_minutes_and_saves(self) -> None:
        self.assertIn('<span id="trail-label">5 min</span>', SETUP)
        self.assertIn('$("trail-label").textContent = $("trail-min").value + " min";', SETUP)
        self.assertIn("await saveSlice({ trails: want });", SETUP)

    def test_watch_save_takes_typed_text(self) -> None:
        start = SETUP.index('$("watch-save").addEventListener')
        handler = SETUP[start:start + 1400]
        self.assertIn("parseWatch(typed)", handler)
        self.assertIn("await saveWatch(tails, enabled);", handler)

    def test_setup_script_parses(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node not installed")
        script = re.search(r"<script>([\s\S]*?)</script>", SETUP).group(1)
        result = subprocess.run(["node", "-e", "new Function(require('fs').readFileSync(0, 'utf8'))"], input=script, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


class WatchFlagTests(unittest.TestCase):
    rows = [{"hex": "abcdef", "callsign": "AAL100", "registration": "N1"}, {"hex": "123456", "callsign": "DAL5", "registration": "N2"}]

    def test_watched_flag_set_with_filter_off(self) -> None:
        out = filter_aircraft(self.rows, {"enabled": False, "tails": ["AAL100"]})
        self.assertEqual([row["watched"] for row in out], [True, False])

    def test_filter_on_keeps_only_watched(self) -> None:
        out = filter_aircraft(self.rows, {"enabled": True, "tails": ["AAL100"]})
        self.assertEqual([row["callsign"] for row in out], ["AAL100"])
        self.assertTrue(out[0]["watched"])


@unittest.skipUnless(node_ts_ok(), "node with --experimental-strip-types not installed")
class AlertLogicTests(unittest.TestCase):
    def test_alert_rules(self) -> None:
        data = run_ts("""
import { AlertTracker, alertReason } from "./src/alerts.ts";
const on = { watch: true, military: true, emergency: true, chime: false };
const a = (id, extra) => ({ id, callsign: id.toUpperCase(), lat: 28, lon: -80, squawk: null, ...extra });
const t = new AlertTracker();
const first = t.update([a("old"), a("emg", { squawk: "7700" }), a("mil0", { military: true })], on);
const second = t.update([a("old", { squawk: "7600" }), a("emg", { squawk: "7700" }), a("mil0", { military: true }), a("mil1", { military: true }), a("w1", { watched: true })], on);
const third = t.update([a("old", { squawk: "7600" }), a("mil1", { military: true })], on);
const off = new AlertTracker(); off.update([], { watch: false, military: false, emergency: false, chime: false });
const none = off.update([a("x", { squawk: "7500", military: true, watched: true })], { watch: false, military: false, emergency: false, chime: false });
console.log(JSON.stringify({ first, second, third, none,
  r: [alertReason(a("q", { squawk: "7500" }), on), alertReason(a("q", { emergency: true }), on), alertReason(a("q", { watched: true }), { ...on, watch: false })] }));
""")
        self.assertEqual(data["first"], [["EMERGENCY", "EMG"]])  # at start only emergencies alert
        self.assertEqual(data["second"], [["EMERGENCY", "OLD"], ["MILITARY", "MIL1"], ["WATCH", "W1"]])
        self.assertEqual(data["third"], [])  # each alert once per aircraft
        self.assertEqual(data["none"], [])
        self.assertEqual(data["r"], ["EMERGENCY", "EMERGENCY", ""])


@unittest.skipUnless(node_ts_ok(), "node with --experimental-strip-types not installed")
class TrailLogicTests(unittest.TestCase):
    def test_history_builds_fades_and_expires(self) -> None:
        data = run_ts("""
import { recordTrails, trailLines, trailAlpha } from "./src/trails.ts";
const h = new Map();
const keep = 2 * 60 * 1000;
const at = (lat) => [{ id: "a1", callsign: "A1", lat, lon: -73.8 }];
let now = 0;
for (let i = 0; i < 30; i += 1) { recordTrails(h, at(40.5 + i * 0.001), now, keep); now += 5000; }
recordTrails(h, at(40.529), now, keep);           // same position again: no new point
const count = h.get("a1").length;
const lines = trailLines(h, [{ id: "a1", callsign: "A1", lat: 40.5295, lon: -73.8 }], now, keep);
const hidden = trailLines(h, [], now, keep);      // filtered out: no line
recordTrails(h, [], now + 30000, keep);           // short feed gap keeps it
const afterGap = h.has("a1");
recordTrails(h, [], now + keep + 10000, keep);    // long gone: dropped
console.log(JSON.stringify({ count, n: lines[0].points.length, head: lines[0].points.at(-1), oldest: lines[0].points[0].age,
  hidden: hidden.length, afterGap, gone: !h.has("a1"), alphaNew: trailAlpha(0), alphaOld: trailAlpha(1) }));
""")
        self.assertEqual(data["count"], 24)  # 2 minutes at one point per 5 s; a repeated position adds none
        self.assertEqual(data["n"], data["count"] + 1)  # joined to the icon
        self.assertEqual(data["head"], {"lat": 40.5295, "lon": -73.8, "age": 0})
        self.assertGreater(data["oldest"], 0.9)
        self.assertEqual(data["hidden"], 0)
        self.assertTrue(data["afterGap"])
        self.assertTrue(data["gone"])
        self.assertGreater(data["alphaNew"], 0.85)
        self.assertGreater(data["alphaOld"], 0.1)

    def test_screen_wiring(self) -> None:
        self.assertIn("trails: trailPoints(now),", MAIN)
        self.assertIn("recordTrails(aircraft, performance.now());", MAIN)
        self.assertIn("this.drawTrails(ctx, scene, zoom.z, zoom.pxPerWorldPx);", (ROOT / "src/radar.ts").read_text())
        self.assertIn("ctx.lineWidth = 2.2;", (ROOT / "src/radar.ts").read_text())


@unittest.skipUnless(node_ts_ok(), "node with --experimental-strip-types not installed")
class ZuluClockTests(unittest.TestCase):
    def test_local_time_with_zulu(self) -> None:
        data = run_ts("""
import { formatClockZulu } from "./src/format.ts";
process.env.TZ = "America/New_York";
const d = new Date(Date.UTC(2026, 10, 19, 23, 53, 0));
console.log(JSON.stringify([formatClockZulu(d, "24h"), formatClockZulu(d, "12h"), formatClockZulu(d, "utc")]));
""")
        self.assertEqual(data, ["1853 · 2353Z", "6:53 PM · 2353Z", "2353Z"])
        self.assertNotIn("formatClock(new Date()", MAIN)
        self.assertEqual(MAIN.count("formatClockZulu(new Date(), config.clockFormat)"), 3)


SPACED = "Home Net "


class WifiSpacesTests(unittest.TestCase):
    def test_scan_keeps_trailing_space(self) -> None:
        rows = wifi_net.parse_scan(f"*:{SPACED}:80:WPA2\n:Home Net:60:WPA2\n: Lead:40:WPA2\n")
        self.assertEqual(sorted(r["ssid"] for r in rows), sorted([SPACED, "Home Net", " Lead"]))

    def test_connect_sends_exact_ssid(self) -> None:
        seen = {}

        def fake(args, input=None, **kwargs):
            seen["input"] = input
            return subprocess.CompletedProcess(args, 0, "ok", "")

        with mock.patch.object(wifi_net.subprocess, "run", side_effect=fake), mock.patch.object(wifi_net, "_helper", return_value=Path(__file__)):
            ok, _ = wifi_net.connect_wifi(SPACED, "password123")
        self.assertTrue(ok)
        self.assertTrue(seen["input"].startswith(SPACED + "\n"))
        self.assertEqual(wifi_net.validate_wifi(SPACED, "password123"), "")

    def test_setup_page_never_trims_ssid(self) -> None:
        self.assertIn('const ssid = $("wifi-ssid").value;', SETUP)
        self.assertNotIn('$("wifi-ssid").value.trim()', SETUP)
        self.assertIn('name.style.whiteSpace = "pre";', SETUP)

    def test_hotspot_profile_named_hotspot_is_not_home(self) -> None:
        def fake(args, timeout=8):
            if args[:2] == ["nmcli", "-v"]:
                return subprocess.CompletedProcess(args, 0, "nmcli 1.52", "")
            if "--active" in args:
                return subprocess.CompletedProcess(args, 0, "Hotspot:802-11-wireless:wlan0\n", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        with mock.patch.object(wifi_net, "_run", side_effect=fake):
            status = wifi_net.wifi_status({"password": "ABCDEFGH"})
        self.assertIn(status["state"], ("hotspot", "portal"))
        self.assertEqual(status["connectedSsid"], "")


class WifiHelperTests(unittest.TestCase):
    """scripts/wifi-ctl.sh and wifi-setup.sh against a fake nmcli."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "profiles").write_text("", encoding="utf-8")
        (self.tmp / "active").write_text("", encoding="utf-8")
        (self.tmp / "connect-rc").write_text("0", encoding="utf-8")
        t = self.tmp
        _exe(t, "nmcli", f'''
{{ printf '%s' "CALL"; for a in "$@"; do printf '|%s' "$a"; done; printf '\\n'; }} >> {t}/calls
if [[ "$*" == "-t -f NAME,TYPE connection show" ]]; then cat {t}/profiles; exit 0; fi
if [[ "$1" == "-g" && "$2" == "802-11-wireless.mode" ]]; then
  if [[ "${{@: -1}}" == "Hotspot" || "${{@: -1}}" == "FlightTracker-Setup" ]]; then echo ap; else echo infrastructure; fi
  exit 0
fi
if [[ "$*" == "-t -f NAME connection show --active" ]]; then cat {t}/active; exit 0; fi
if [[ "$1" == "--wait" ]]; then exit "$(cat {t}/connect-rc)"; fi
exit 0
''')
        self.env = {"PATH": f"{t}:/usr/bin:/bin", "FT_WIFI_SETTLE": "0"}

    def calls(self) -> list[list[str]]:
        path = self.tmp / "calls"
        if not path.is_file():
            return []
        return [line.split("|")[1:] for line in path.read_text(encoding="utf-8").splitlines()]

    def run_ctl(self, *args: str, data: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", str(ROOT / "scripts/wifi-ctl.sh"), *args], input=data, env=self.env, capture_output=True, text=True, timeout=30)

    def test_connect_stops_hotspot_first_and_keeps_spaces(self) -> None:
        (self.tmp / "profiles").write_text("Hotspot:802-11-wireless\nWired connection 1:802-3-ethernet\n")
        (self.tmp / "active").write_text("Hotspot\nWired connection 1\n")
        result = self.run_ctl("connect", data=f"{SPACED}\npassword123\nno\n\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        off = calls.index(["connection", "modify", "id", "Hotspot", "connection.autoconnect", "no"])
        down = calls.index(["connection", "down", "id", "Hotspot"])
        join = next(i for i, c in enumerate(calls) if c[:5] == ["--wait", "45", "dev", "wifi", "connect"])
        self.assertLess(off, join)
        self.assertLess(down, join)
        self.assertEqual(calls[join][5], SPACED)

    def test_failed_connect_brings_hotspot_back(self) -> None:
        (self.tmp / "profiles").write_text("FlightTracker-Setup:802-11-wireless\n")
        (self.tmp / "active").write_text("FlightTracker-Setup\n")
        (self.tmp / "connect-rc").write_text("4")
        result = self.run_ctl("connect", data=f"{SPACED}\npassword123\nno\n\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn(f'Could not join "{SPACED}"', result.stderr)
        self.assertNotIn("password123", result.stdout + result.stderr)
        self.assertEqual(self.calls()[-1], ["connection", "up", "id", "FlightTracker-Setup"])

    def test_boot_leaves_wlan0_alone_when_wifi_is_saved(self) -> None:
        (self.tmp / "profiles").write_text(f"Hotspot:802-11-wireless\n{SPACED}:802-11-wireless\n")
        result = self.run_ctl("boot-hotspot", "FlightTracker-Setup", "ABCDEFGH")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not starting the setup hotspot", result.stdout)
        self.assertFalse([c for c in self.calls() if "hotspot" in c])
        self.assertIn(["connection", "modify", "id", "Hotspot", "connection.autoconnect", "no"], self.calls())
        self.assertEqual(self.run_ctl("client-profiles").stdout, SPACED + "\n")

    def test_boot_starts_hotspot_without_saved_wifi(self) -> None:
        (self.tmp / "profiles").write_text("Hotspot:802-11-wireless\n")
        result = self.run_ctl("boot-hotspot", "FlightTracker-Setup", "ABCDEFGH")
        self.assertEqual(result.returncode, 0, result.stderr)
        start = next(c for c in self.calls() if "hotspot" in c)
        self.assertEqual(start, ["dev", "wifi", "hotspot", "ifname", "wlan0", "con-name", "FlightTracker-Setup", "ssid", "FlightTracker-Setup", "password", "ABCDEFGH"])
        self.assertEqual(self.calls()[-1], ["connection", "modify", "id", "FlightTracker-Setup", "connection.autoconnect", "no"])

    def test_wifi_service_script_does_not_hijack(self) -> None:
        (self.tmp / "profiles").write_text(f"{SPACED}:802-11-wireless\n")
        result = subprocess.run(["bash", str(ROOT / "scripts/wifi-setup.sh")], env=self.env, capture_output=True, text=True, timeout=30, cwd=self.tmp)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse([c for c in self.calls() if "hotspot" in c or c[:2] == ["connection", "up"]])
        unit = (ROOT / "deploy/flight-tracker-wifi.service").read_text()
        self.assertIn("scripts/wifi-setup.sh", unit)


class PushUpdateTests(unittest.TestCase):
    script = ROOT / "deploy/push-update.sh"

    def test_script_basics(self) -> None:
        text = self.script.read_text()
        self.assertTrue(os.access(self.script, os.X_OK))
        self.assertEqual(subprocess.run(["bash", "-n", str(self.script)]).returncode, 0)
        self.assertIn("flighttracker@flighttracker.local", text)
        self.assertIn('tar xf "$name"', text)
        self.assertIn("bash install.sh", text)
        self.assertIn('trap \'rm -rf "$dir"\' EXIT', text)

    def test_push_end_to_end_with_fake_ssh(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        log = tmp / "log"
        # ssh/scp run locally; sudo, systemctl and curl are stand-ins.
        _exe(bin_dir, "ssh", f'''
while [[ $# -gt 0 ]]; do case "$1" in -o|-O) [[ "$1" == "-O" ]] && exit 0; shift 2;; -t|-q) shift;; *) break;; esac; done
shift; exec bash -c "$*"
''')
        _exe(bin_dir, "scp", '''
args=(); while [[ $# -gt 0 ]]; do case "$1" in -o) shift 2;; -q) shift;; *) args+=("$1"); shift;; esac; done
cp "${args[0]}" "${args[1]#*:}"
''')
        _exe(bin_dir, "sudo", f'''[[ "$1" == --preserve-env=* ]] && shift; echo "SUDO $*" >> {log}; cd "$PWD"; "$@"''')
        _exe(bin_dir, "systemctl", "exit 0\n")
        _exe(bin_dir, "curl", 'echo \'{"version": "9.9.9"}\'\n')
        rel = tmp / "rel"
        rel.mkdir()
        (rel / "VERSION").write_text("9.9.9\n")
        (rel / "install.sh").write_text(f'echo "installed from $PWD" >> {log}\n')
        for suffix, mode in ((".tar.gz", "w:gz"), (".tar", "w")):
            archive = tmp / f"flight-tracker-9.9.9{suffix}"
            with tarfile.open(archive, mode) as tar:
                for name in ("VERSION", "install.sh"):
                    tar.add(rel / name, arcname=name)
            env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp), "TMPDIR": str(tmp)}
            result = subprocess.run(["bash", str(self.script), str(archive), "flighttracker@flighttracker.local"], env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("running 9.9.9", result.stdout)
            self.assertIn("SUDO bash install.sh", log.read_text())
        self.assertFalse(list(Path("/tmp").glob("flight-tracker-push.*/release/install.sh")), "temporary folder left on the Pi")

    def test_rejects_bad_target(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        tar = tmp / "flight-tracker-1.0.3.tar"
        tar.write_bytes(b"x")
        result = subprocess.run(["bash", str(self.script), str(tar), "bad target; rm -rf /"], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)


class PackTreeTests(unittest.TestCase):
    def test_previews_and_tokens_stay_out_of_release(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        src = tmp / "src"
        (src / "previews_v103").mkdir(parents=True)
        (src / "previews_v103" / "a.png").write_bytes(b"x")
        (src / "data").mkdir()
        (src / "data" / "update-token").write_text("secret")
        (src / "VERSION").write_text("1.0.3")
        out = tmp / "t.tar.gz"
        pack_tree(src, out)
        with tarfile.open(out) as archive:
            self.assertEqual(sorted(archive.getnames()), ["VERSION", "data"])


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(node_ts_ok(), "node with --experimental-strip-types not installed")
class StandbyScopeTests(unittest.TestCase):
    """Standby wakes only for aircraft that will draw inside the ring (1.0.3 bug)."""

    def run_scope(self, extra: str = "") -> dict:
        return run_ts("""
import { scopeAircraft, SCOPE_EDGE } from "./src/scope.ts";
const home = { lat: 40.6, lon: -73.85 };
const north = (nm) => home.lat + nm / 60;
const a = (id, extra) => ({ id, callsign: id, lat: north(5), lon: home.lon, altFt: 5000, ground: false, gsKt: 250, track: 90, vsFpm: 0, ...extra });
const band = (b) => (item) => b === "all" ? true : (item.ground || item.altFt == null) ? b === "low" : b === "low" ? item.altFt < 10000 : item.altFt >= 35000;
const view = (over) => ({ centerLat: home.lat, centerLon: home.lon, rangeNm: 20, watchOnly: false, inBand: band("all"), ...over });
const list = [
  a("inrange"),
  a("far", { lat: north(25) }),            // inside adsb.fi's 27 NM query, outside the 20 NM ring
  a("edge", { lat: north(19.85) }),        // on the ring line: not drawn, so no wake
  a("nolat", { lat: null }),
  a("nanlon", { lon: Number.NaN }),
  a("high", { altFt: 38000 }),
  a("gnd", { ground: true, altFt: 0, track: null, gsKt: null }),
  a("notrack", { track: null, gsKt: null, altFt: null }),
  a("unwatched", { watched: false }),
  a("watched", { watched: true }),
];
const ids = (xs) => xs.map((x) => x.id);
const beyond = [];
const all = scopeAircraft(list, view({}), beyond);
const low = scopeAircraft(list, view({ inBand: band("low") }));
const upper = scopeAircraft(list, view({ inBand: band("upper") }));
const watch = scopeAircraft(list, view({ watchOnly: true }));
const panned = scopeAircraft([a("far", { lat: north(25) })], view({ centerLat: north(10) }));
const empty = scopeAircraft([a("far", { lat: north(25) })], view({}));
const placed = scopeAircraft([a("mv", { track: 0, gsKt: 3600 })], view({ place: (i) => ({ ...i, lat: i.lat + 0.01 }) }));
const nanPlace = scopeAircraft([a("np")], view({ place: (i) => ({ ...i, lat: Number.NaN }) }));
const zero = scopeAircraft(list, view({ rangeNm: 0 }));
const notrack = all.find((x) => x.id === "notrack");
console.log(JSON.stringify({ all: ids(all), beyond: ids(beyond), low: ids(low), upper: ids(upper), watch: ids(watch),
  panned: ids(panned), empty: empty.length, placedLat: placed[0].lat, home: home.lat, nanPlace: ids(nanPlace), zero: zero.length,
  notrack: [notrack.track, notrack.gsKt], edge: SCOPE_EDGE }));
""")

    def test_wake_list_matches_drawn_aircraft(self) -> None:
        d = self.run_scope()
        self.assertEqual(d["all"], ["inrange", "high", "gnd", "notrack", "unwatched", "watched"])
        self.assertEqual(d["beyond"], ["far"])          # edge tick only, no wake
        self.assertEqual(d["low"], ["inrange", "gnd", "notrack", "unwatched", "watched"])
        self.assertEqual(d["upper"], ["high"])
        self.assertEqual(d["watch"], ["inrange", "high", "gnd", "notrack", "watched"])
        self.assertEqual(d["panned"], ["far"])           # pan moves the scope center
        self.assertEqual(d["empty"], 0)                  # only out-of-ring traffic: stay in standby
        self.assertGreater(d["placedLat"], d["home"])    # dead-reckoned position is the one drawn
        self.assertEqual(d["nanPlace"], ["np"])          # a NaN placement falls back to the fix
        self.assertEqual(d["zero"], 0)
        self.assertEqual(d["notrack"], [None, None])
        self.assertLess(d["edge"], 1)

    def test_main_uses_one_list_for_standby_and_draw(self) -> None:
        self.assertIn("const onScope = visible(now, beyond);\n  syncIdle(onScope.length);", MAIN)
        self.assertIn("aircraft: onScope,", MAIN)
        self.assertNotIn("watchCount > 0", MAIN)
        self.assertIn("noteArrivals(visible(performance.now()));", MAIN)
        radar = (ROOT / "src/radar.ts").read_text(encoding="utf-8")
        self.assertIn("if (!Number.isFinite(dist) || dist > this.outerRing) continue;", radar)
        self.assertIn("Number.isFinite(aircraft.track) ? aircraft.track : 0", radar)

    def test_server_keeps_sparse_adsbfi_rows(self) -> None:
        from logic import normalize_aircraft
        rows = normalize_aircraft({"aircraft": [
            {"hex": "a1b2c3", "lat": 40.7, "lon": -73.8, "alt_baro": "ground"},
            {"hex": "a1b2c4", "lat": 40.7, "lon": -73.8},
            {"hex": "a1b2c5", "lat": 40.7, "lon": -73.8, "alt_geom": 4200, "track": None, "gs": None},
            {"hex": "a1b2c6", "lastPosition": {"lat": 40.7, "lon": -73.8}},
            {"hex": "a1b2c7", "lat": float("nan"), "lon": -73.8},
        ]})
        by = {r["hex"]: r for r in rows}
        self.assertEqual(sorted(by), ["A1B2C3", "A1B2C4", "A1B2C5"])
        self.assertTrue(by["A1B2C3"]["ground"])
        self.assertEqual(by["A1B2C3"]["altFt"], 0)
        self.assertIsNone(by["A1B2C4"]["altFt"])
        self.assertEqual(by["A1B2C5"]["altFt"], 4200)
        self.assertIsNone(by["A1B2C5"]["track"])
        self.assertEqual(by["A1B2C4"]["callsign"], "A1B2C4")


@unittest.skipUnless(node_ts_ok(), "node with --experimental-strip-types not installed")
class DataBlockTests(unittest.TestCase):
    def test_altitude_in_every_block(self) -> None:
        d = run_ts("""
import { blockAltitude, dataBlockLine } from "./src/format.ts";
console.log(JSON.stringify([
  blockAltitude(3420, false, "aviation"), blockAltitude(34000, false, "aviation"), blockAltitude(18000, false, "imperial"),
  blockAltitude(0, true, "aviation"), blockAltitude(null, false, "aviation"), blockAltitude(3420, false, "metric"),
  dataBlockLine(12480, false, 1500, 250, "aviation"), dataBlockLine(34000, false, -900, 466, "aviation"),
  dataBlockLine(0, true, 0, 12, "aviation"), dataBlockLine(5000, false, null, null, "aviation"),
]));
""")
        self.assertEqual(d, ["3,400", "FL340", "FL180", "GND", "ALT ---", "1,042 m",
                             "12,500▲ 250", "FL340▼ 466", "GND 12", "5,000"])

    def test_radar_draws_altitude_line(self) -> None:
        # 1.0.13: the map box is identifier-only; altitude stays on the detail card.
        radar = (ROOT / "src/radar.ts").read_text(encoding="utf-8")
        main = (ROOT / "src/main.ts").read_text(encoding="utf-8")
        self.assertNotIn("const line2 = dataBlockLine", radar)
        self.assertIn("mapLabelIdent", radar)
        self.assertIn('["ALTITUDE", formatAltitude(item.altFt, item.ground, config.units)]', main)
        self.assertNotIn("minimal", radar)


class CompassUnderPillTests(unittest.TestCase):
    def test_no_cardinal_behind_range_pill(self) -> None:
        radar = (ROOT / "src/radar.ts").read_text(encoding="utf-8")
        self.assertIn('elementBox(["rangectl"]', radar)
        self.assertIn("boxesOverlap(box, pill)", radar)
        self.assertIn("export const TOP_PILL_HALF_DEG = 22;", radar)
        block = CSS[CSS.index("#range, .range-step {"):][:300]
        self.assertIn("background: #060b10;", block)

    @unittest.skipUnless(node_ts_ok(), "node with --experimental-strip-types not installed")
    def test_angle_from_top(self) -> None:
        # radar.ts imports a JSON module, so check the formula on its own copy.
        radar = (ROOT / "src/radar.ts").read_text(encoding="utf-8")
        body = radar[radar.index("export function angleFromTop"):]
        body = body[:body.index("\n}\n") + 3]
        body = body.replace("export ", "").replace(": number", "")
        d = run_ts(body + "\nconsole.log(JSON.stringify([0, 90, 180, 270, 350, -10, 380, -200].map((x) => angleFromTop(x))));")
        self.assertEqual(d, [0, 90, -180, -90, -10, -10, 20, 160])
