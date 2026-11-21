"""1.0.2: Pi kiosk fixes, rotation/touch setup, Wi-Fi picker, display options."""

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

from server import display_setup, wifi_net
from server.logic import DEFAULT_CONFIG, hhmm_to_hours, hours_to_hhmm, sanitize_config
from server.migrate import migrate_config
from server.rings import ring_distances
from server.updater import pack_tree
from server.watchlist import WATCH_EXAMPLE, is_watched, parse_watch_text

ROOT = Path(__file__).resolve().parents[2]
# flighttracker.py imports its siblings by bare name (it runs as a script).
if str(ROOT / "server") not in sys.path:
    sys.path.insert(0, str(ROOT / "server"))
HOME = {"home": {"name": "KJFK", "lat": 40.6399, "lon": -73.7787}, "rangeNm": 20}


def _exe(folder: Path, name: str, body: str) -> None:
    path = folder / name
    path.write_text("#!/bin/bash\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class KioskScriptTests(unittest.TestCase):
    """Run scripts/kiosk.sh with a fake Chromium and wlr-randr."""

    def run_kiosk(self, rotation: int = 270, gpu: str = "", bus: bool = True) -> tuple[list[str], list[str], dict[str, str]]:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        runtime = tmp / "run"
        runtime.mkdir()
        socks = []
        for name in ["wayland-0"] + (["bus"] if bus else []):
            sock = socket.socket(socket.AF_UNIX)
            sock.bind(str(runtime / name))
            socks.append(sock)
        self.addCleanup(lambda: [s.close() for s in socks])
        _exe(bin_dir, "chromium", f'printf "%s\\n" "$@" > {tmp}/chrome-args\nenv > {tmp}/chrome-env\n')
        _exe(bin_dir, "wlr-randr", f'printf "%s\\n" "$@" > {tmp}/randr-args\n')
        cfg = deepcopy(DEFAULT_CONFIG)
        cfg["display"]["rotation"] = rotation
        (tmp / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "XDG_RUNTIME_DIR": str(runtime),
            "FLIGHT_TRACKER_CONFIG": str(tmp / "config.json"),
            "FLIGHT_TRACKER_DISPLAY_WAIT": "1",
            "HOME": str(tmp),
        }
        if gpu:
            env["FLIGHT_TRACKER_GPU"] = gpu
        result = subprocess.run(["bash", str(ROOT / "scripts" / "kiosk.sh")], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = (tmp / "chrome-args").read_text().split("\n")
        randr = (tmp / "randr-args").read_text().split("\n") if (tmp / "randr-args").exists() else []
        chrome_env = dict(line.split("=", 1) for line in (tmp / "chrome-env").read_text().splitlines() if "=" in line)
        return args, randr, chrome_env

    def test_gpu_is_off_by_default_for_the_white_page_fix(self) -> None:
        args, _, _ = self.run_kiosk()
        self.assertIn("--kiosk", args)
        self.assertIn("--disable-gpu", args)
        self.assertIn("--disable-gpu-compositing", args)
        self.assertIn("--ozone-platform=wayland", args)
        self.assertIn("http://127.0.0.1:8741/?kiosk=1", args)

    def test_gpu_can_be_turned_back_on(self) -> None:
        args, _, _ = self.run_kiosk(gpu="1")
        self.assertNotIn("--disable-gpu", args)

    def test_rotation_from_config_goes_to_wlr_randr(self) -> None:
        _, randr, _ = self.run_kiosk(rotation=270)
        self.assertEqual(randr[:4], ["--output", "DSI-1", "--transform", "270"])
        _, randr, _ = self.run_kiosk(rotation=0)
        self.assertEqual(randr[:4], ["--output", "DSI-1", "--transform", "normal"])

    def test_session_bus_is_set_when_the_socket_exists(self) -> None:
        _, _, env = self.run_kiosk(bus=True)
        self.assertTrue(env.get("DBUS_SESSION_BUS_ADDRESS", "").startswith("unix:path="))
        _, _, env = self.run_kiosk(bus=False)
        self.assertNotIn("DBUS_SESSION_BUS_ADDRESS", env)


class DisplaySetupTests(unittest.TestCase):
    def test_transform_names(self) -> None:
        self.assertEqual(display_setup.transform_name(0), "normal")
        self.assertEqual(display_setup.transform_name(270), "270")
        with self.assertRaises(ValueError):
            display_setup.transform_name(45)

    def test_new_kanshi_config(self) -> None:
        text = display_setup.kanshi_config(None, "DSI-1", 270)
        self.assertIn("output DSI-1 enable transform 270", text)
        self.assertEqual(display_setup.kanshi_config(text, "DSI-1", 270), text)

    def test_existing_kanshi_line_is_updated_not_duplicated(self) -> None:
        old = "profile {\n\toutput DSI-1 enable mode 720x720@60 position 0,0 transform normal\n\toutput HDMI-A-1 enable\n}\n"
        new = display_setup.kanshi_config(old, "DSI-1", 270)
        self.assertIn("output DSI-1 enable mode 720x720@60 position 0,0 transform 270", new)
        self.assertIn("output HDMI-A-1 enable", new)
        self.assertEqual(new.count("DSI-1"), 1)
        self.assertEqual(display_setup.kanshi_config(new, "DSI-1", 270), new)

    def test_kanshi_without_the_output_gets_a_profile(self) -> None:
        old = "profile {\n\toutput HDMI-A-1 enable\n}\n"
        new = display_setup.kanshi_config(old, "DSI-1", 90)
        self.assertTrue(new.startswith(old.rstrip("\n")))
        self.assertIn("output DSI-1 enable transform 90", new)

    def test_rc_xml_created_merged_and_left_alone(self) -> None:
        device = "10-0014 Goodix Capacitive TouchScreen"
        created, _ = display_setup.rc_xml_with_touch(None, device, "DSI-1")
        self.assertIn('<touch deviceName="10-0014 Goodix Capacitive TouchScreen" mapToOutput="DSI-1"', created)
        again, note = display_setup.rc_xml_with_touch(created, device, "DSI-1")
        self.assertIsNone(again)
        self.assertIn("already", note)
        existing = '<?xml version="1.0"?>\n<labwc_config>\n  <keyboard><numlock>on</numlock></keyboard>\n</labwc_config>\n'
        merged, _ = display_setup.rc_xml_with_touch(existing, device, "DSI-1")
        self.assertIn("<numlock>on</numlock>", merged)
        self.assertLess(merged.index("<touch"), merged.index("</labwc_config>"))
        odd, note = display_setup.rc_xml_with_touch("<something/>", device, "DSI-1")
        self.assertIsNone(odd)
        self.assertIn("left it unchanged", note)

    def test_apply_is_idempotent_and_udev_follows_the_switch(self) -> None:
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        udev = home / "99-flight-tracker-touch.rules"
        devices = home / "devices"
        devices.write_text('I: Bus=0018\nN: Name="10-0014 Goodix Capacitive TouchScreen"\n', encoding="utf-8")
        cfg = deepcopy(DEFAULT_CONFIG)
        display_setup.apply(cfg, home, None, udev, devices)
        first = {p: p.read_text() for p in home.rglob("*") if p.is_file()}
        display_setup.apply(cfg, home, None, udev, devices)
        second = {p: p.read_text() for p in home.rglob("*") if p.is_file()}
        self.assertEqual(first, second)
        self.assertFalse(udev.exists())
        self.assertIn("transform 270", (home / ".config/kanshi/config").read_text())
        cfg["display"]["touchMatrix"] = True
        display_setup.apply(cfg, home, None, udev, devices)
        self.assertIn('LIBINPUT_CALIBRATION_MATRIX}="0 1 0 -1 0 1"', udev.read_text())
        cfg["display"]["touchMatrix"] = False
        display_setup.apply(cfg, home, None, udev, devices)
        self.assertFalse(udev.exists())

    def test_touch_device_is_detected_from_the_kernel_list(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        devices = tmp / "devices"
        devices.write_text('N: Name="vc4-hdmi"\nN: Name="11-0014 Goodix Capacitive TouchScreen"\n', encoding="utf-8")
        self.assertEqual(display_setup.detect_touch_device("10-0014 Goodix Capacitive TouchScreen", devices), "11-0014 Goodix Capacitive TouchScreen")
        self.assertEqual(display_setup.detect_touch_device("X", tmp / "missing"), "X")

    def test_print_transform_cli(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        cfg = tmp / "config.json"
        cfg.write_text(json.dumps({"display": {"rotation": 180, "output": "DSI-2"}}), encoding="utf-8")
        out = subprocess.run([sys.executable, str(ROOT / "server/display_setup.py"), "--config", str(cfg), "--print-transform"], capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.split(), ["DSI-2", "180"])


class ConfigTests(unittest.TestCase):
    def test_new_defaults(self) -> None:
        cfg, errors = sanitize_config(dict(HOME))
        self.assertEqual(errors, [])
        self.assertEqual(cfg["display"]["rotation"], 270)
        self.assertEqual(cfg["wifi"]["country"], "US")
        self.assertEqual(cfg["rings"], 0)  # Auto: round-label count for the selected range
        self.assertTrue(cfg["showClock"])
        self.assertTrue(cfg["minimalText"])
        self.assertEqual(cfg["clockFormat"], "24h")
        self.assertTrue(cfg["weather"]["enabled"])
        self.assertEqual(cfg["sweep"]["periodSec"], 8)

    def test_validation(self) -> None:
        for patch in ({"display": {"rotation": 45}}, {"display": {"output": "bad name!"}}, {"wifi": {"country": "USA"}},
                      {"rings": 9}, {"rings": True}, {"clockFormat": "36h"}, {"night": {"from": "2500"}}, {"night": {"to": "123"}}):
            payload = dict(HOME, **patch)
            _, errors = sanitize_config(payload)
            self.assertTrue(errors, patch)
        cfg, errors = sanitize_config(dict(HOME, rings=6, showClock=False, minimalText=False, clockFormat="12h", display={"rotation": 90}))
        self.assertEqual(errors, [])
        self.assertEqual((cfg["rings"], cfg["showClock"], cfg["minimalText"], cfg["clockFormat"], cfg["display"]["rotation"]), (6, False, False, "12h", 90))

    def test_schema_survives_a_save(self) -> None:
        cfg, _ = sanitize_config(dict(HOME, schema=3))
        self.assertEqual(cfg["schema"], 3)

    def test_migration_to_1_0_2(self) -> None:
        old = {"schema": 2, "sweep": {"enabled": True, "periodSec": 4}, "weather": {"enabled": False, "opacity": 0.6}}
        new = migrate_config(deepcopy(old))
        self.assertEqual(new["schema"], 3)
        self.assertEqual(new["sweep"]["periodSec"], 8)
        self.assertTrue(new["weather"]["enabled"])
        self.assertEqual(new["display"]["rotation"], 270)
        self.assertEqual(new["wifi"]["country"], "US")
        custom = migrate_config({"schema": 2, "sweep": {"periodSec": 5.5}})
        self.assertEqual(custom["sweep"]["periodSec"], 5.5)
        # After the step has run, a user's own choice of 4 s / weather off sticks.
        chosen = migrate_config({"schema": 3, "sweep": {"periodSec": 4}, "weather": {"enabled": False}})
        self.assertEqual(chosen["sweep"]["periodSec"], 4)
        self.assertFalse(chosen["weather"]["enabled"])

    def test_migrate_cli_no_system_flag(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / "config.json"
        path.write_text(json.dumps({"schema": 2, "sweep": {"periodSec": 4}}), encoding="utf-8")
        subprocess.run([sys.executable, str(ROOT / "server/migrate.py"), "--config", str(path), "--no-system"], check=True)
        self.assertEqual(json.loads(path.read_text())["schema"], 3)

    def test_example_config_is_current(self) -> None:
        example = json.loads((ROOT / "data/config.example.json").read_text())
        self.assertEqual(example["schema"], 3)
        cfg, errors = sanitize_config(example)
        self.assertEqual(errors, [])
        self.assertEqual(migrate_config(deepcopy(cfg)), cfg)

    def test_hhmm(self) -> None:
        self.assertEqual(hhmm_to_hours("2230"), 22.5)
        self.assertEqual(hhmm_to_hours("0000"), 0)
        self.assertEqual(hours_to_hhmm(6), "0600")
        for bad in ("2400", "1260", "930", "ab12", ""):
            with self.assertRaises(ValueError):
                hhmm_to_hours(bad)

    def test_night_hhmm_and_legacy_hours(self) -> None:
        cfg, errors = sanitize_config(dict(HOME, night={"mode": "schedule", "from": "2130", "to": "0545", "brightness": 20}))
        self.assertEqual(errors, [])
        self.assertEqual((cfg["night"]["from"], cfg["night"]["to"], cfg["night"]["fromHour"], cfg["night"]["toHour"]), ("2130", "0545", 21, 5))
        legacy, _ = sanitize_config(dict(HOME, night={"mode": "schedule", "fromHour": 23, "toHour": 7}))
        self.assertEqual((legacy["night"]["from"], legacy["night"]["to"]), ("2300", "0700"))

    def test_night_status_uses_minutes(self) -> None:
        from server.flighttracker import _night_hours
        self.assertEqual(_night_hours({"from": "2130", "fromHour": 21}, "from", "fromHour"), 21.5)
        self.assertEqual(_night_hours({"fromHour": 22}, "from", "fromHour"), 22.0)

    def test_ring_distances(self) -> None:
        self.assertEqual(ring_distances(20), [5, 10, 15, 20])
        self.assertEqual(ring_distances(20, 5), [4, 8, 12, 16, 20])
        self.assertEqual(ring_distances(10, 3), [3.33, 6.67, 10])
        self.assertEqual(ring_distances(10, 99), ring_distances(10, 6))


class WatchParserTests(unittest.TestCase):
    def test_example_text(self) -> None:
        self.assertEqual(parse_watch_text(WATCH_EXAMPLE), (["N123AB", "AAL100", "A1B2C3"], []))

    def test_separators_case_and_duplicates(self) -> None:
        text = " n123ab,AAL100\nA1B2C3;  n123ab \t c-gabc,,"
        self.assertEqual(parse_watch_text(text), (["N123AB", "AAL100", "A1B2C3", "CGABC"], []))

    def test_rejected_entries_are_reported(self) -> None:
        accepted, rejected = parse_watch_text("N1, X, TOOLONG123, @@")
        self.assertEqual(accepted, ["N1"])
        self.assertEqual(rejected, ["X", "TOOLONG123", "@@"])

    def test_config_accepts_text_or_list_with_commas(self) -> None:
        cfg, errors = sanitize_config(dict(HOME, watch={"enabled": True, "tails": "N123AB AAL100"}))
        self.assertEqual(errors, [])
        self.assertEqual(cfg["watch"]["tails"], ["N123AB", "AAL100"])
        cfg, _ = sanitize_config(dict(HOME, watch={"enabled": True, "tails": ["n123ab, a1b2c3", "AAL100", "N123AB"]}))
        self.assertEqual(cfg["watch"]["tails"], ["N123AB", "A1B2C3", "AAL100"])

    def test_callsign_matches(self) -> None:
        self.assertTrue(is_watched({"hex": "abcdef", "callsign": "AAL100"}, ["AAL100"]))
        self.assertTrue(is_watched({"hex": "a1b2c3", "callsign": "X"}, ["A1B2C3"]))
        self.assertFalse(is_watched({"hex": "abcdef", "callsign": "UAL1"}, ["AAL100"]))


SCAN = (
    "*:Home\\:Net:82:WPA2\n"
    ":Home\\:Net:60:WPA2\n"
    ":Cafe:45:\n"
    ":Garage:30:--\n"
    "::70:WPA2\n"
    ":Office:91:WPA1 WPA2\n"
)


class WifiTests(unittest.TestCase):
    def test_split_terse_handles_escapes(self) -> None:
        self.assertEqual(wifi_net.split_terse("*:My\\:Net:80:WPA2"), ["*", "My:Net", "80", "WPA2"])
        self.assertEqual(wifi_net.split_terse("a\\\\b:c"), ["a\\b", "c"])

    def test_parse_scan(self) -> None:
        rows = wifi_net.parse_scan(SCAN)
        self.assertEqual([r["ssid"] for r in rows], ["Home:Net", "Office", "Cafe", "Garage"])
        home = rows[0]
        self.assertTrue(home["inUse"])
        self.assertEqual(home["signal"], 82)
        self.assertTrue(home["secured"])
        cafe = next(r for r in rows if r["ssid"] == "Cafe")
        self.assertFalse(cafe["secured"])
        self.assertEqual(cafe["security"], "Open")
        self.assertFalse(next(r for r in rows if r["ssid"] == "Garage")["secured"])

    def test_scan_uses_helper_then_falls_back(self) -> None:
        calls = []

        def fake(args, timeout=8):
            calls.append(args)
            if args[0] == "sudo":
                return subprocess.CompletedProcess(args, 1, "", "sudo: a password is required")
            return subprocess.CompletedProcess(args, 0, ":Cafe:45:\n", "")

        with mock.patch.object(wifi_net, "_run", side_effect=fake), mock.patch.object(wifi_net, "_helper", return_value=Path(__file__)):
            rows = wifi_net.wifi_scan()
        self.assertEqual(rows[0]["ssid"], "Cafe")
        self.assertEqual(calls[0][-1], "scan")
        self.assertIn("list", calls[1])

    def test_validation(self) -> None:
        self.assertTrue(wifi_net.validate_wifi("", "password1"))
        self.assertTrue(wifi_net.validate_wifi("x" * 33, "password1"))
        self.assertTrue(wifi_net.validate_wifi("Net", "short"))
        self.assertTrue(wifi_net.validate_wifi("Net\nX", "password1"))
        self.assertTrue(wifi_net.validate_wifi("Net", "pass\nword1"))
        self.assertEqual(wifi_net.validate_wifi("Net", ""), "")
        self.assertEqual(wifi_net.validate_wifi("Net; rm -rf /", "pa$$ word'\"`"), "")

    def test_connect_sends_password_on_stdin_only(self) -> None:
        seen = {}
        secret = "s3cret pass'$(reboot)"

        def fake(args, input=None, timeout=None, check=None, capture_output=None, text=None):
            seen["args"] = args
            seen["input"] = input
            return subprocess.CompletedProcess(args, 0, "Device 'wlan0' successfully activated.\n", "")

        with mock.patch.object(wifi_net.subprocess, "run", side_effect=fake), mock.patch.object(wifi_net, "_helper", return_value=Path(__file__)):
            ok, detail = wifi_net.connect_wifi("Home; echo pwned", secret, hidden=True, country="us")
        self.assertTrue(ok)
        self.assertIn("activated", detail)
        self.assertEqual(seen["args"], ["sudo", "-n", __file__, "connect"])
        self.assertNotIn(secret, " ".join(seen["args"]))
        self.assertEqual(seen["input"], f"Home; echo pwned\n{secret}\nyes\nUS\n")

    def test_errors_never_echo_the_password(self) -> None:
        secret = "hunter2hunter2"

        def fake(args, input=None, **kwargs):
            return subprocess.CompletedProcess(args, 4, "", f"Error: secrets were required ({secret})")

        with mock.patch.object(wifi_net.subprocess, "run", side_effect=fake), mock.patch.object(wifi_net, "_helper", return_value=Path(__file__)):
            ok, detail = wifi_net.connect_wifi("Home", secret)
        self.assertFalse(ok)
        self.assertNotIn(secret, detail)

    def test_device_status_reports_ips(self) -> None:
        def fake(args, timeout=8):
            if "status" in args:
                return subprocess.CompletedProcess(args, 0, "eth0:ethernet:connected:Wired connection 1\nwlan0:wifi:connected:Home\nlo:loopback:connected (externally):lo\n", "")
            if "eth0" in args:
                return subprocess.CompletedProcess(args, 0, "192.0.2.15/24\n", "")
            return subprocess.CompletedProcess(args, 0, "192.0.2.30/24\n", "")

        with mock.patch.object(wifi_net, "_run", side_effect=fake):
            rows = wifi_net.device_status()
        self.assertEqual([(r["device"], r["ip"]) for r in rows], [("eth0", "192.0.2.15"), ("wlan0", "192.0.2.30")])

    def test_helper_reads_stdin_and_quotes_args(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        _exe(tmp, "nmcli", f'printf "%s\\n" "$@" > {tmp}/nm-args\n')
        env = {"PATH": f"{tmp}:/usr/bin:/bin"}
        data = "My Net; touch /tmp/pwned\npass word 123\nyes\n\n"
        result = subprocess.run(["bash", str(ROOT / "scripts/wifi-ctl.sh"), "connect"], input=data, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = (tmp / "nm-args").read_text().split("\n")
        self.assertEqual(args[:9], ["--wait", "45", "dev", "wifi", "connect", "My Net; touch /tmp/pwned", "password", "pass word 123", "hidden"])
        self.assertNotIn("pass word 123", result.stdout + result.stderr)


class WeatherIndexTests(unittest.TestCase):
    def make_app(self):
        from server.flighttracker import App
        app = App.__new__(App)
        app.weather_cache = {"at": 0.0, "body": None}
        return app

    def test_rainviewer_ok(self) -> None:
        import server.flighttracker as ft
        body = json.dumps({"radar": {"past": [{"time": 1, "path": "/v2/radar/abc123"}, {"time": 2, "path": "/v2/radar/def456"}]}}).encode()
        with mock.patch.object(ft, "fetch_bytes", return_value=body):
            index = self.make_app().weather_index()
        self.assertTrue(index["ok"])
        self.assertEqual(index["provider"], "rainviewer")
        self.assertEqual([f["id"] for f in index["frames"]], ["abc123", "def456"])

    def test_falls_back_to_iem_then_reports_unavailable(self) -> None:
        import server.flighttracker as ft

        def iem_only(url, **kwargs):
            if "rainviewer" in url:
                raise RuntimeError("HTTP 503")
            return b"\x89PNG"

        with mock.patch.object(ft, "fetch_bytes", side_effect=iem_only):
            index = self.make_app().weather_index()
        self.assertEqual(index["provider"], "iem")
        self.assertTrue(index["ok"])
        with mock.patch.object(ft, "fetch_bytes", side_effect=RuntimeError("offline")):
            index = self.make_app().weather_index()
        self.assertFalse(index["ok"])
        self.assertEqual(index["frames"], [])
        self.assertIn("unreachable", index["error"])

    def test_index_is_cached(self) -> None:
        import server.flighttracker as ft
        body = json.dumps({"radar": {"past": [{"time": 1, "path": "/v2/radar/abc123"}]}}).encode()
        app = self.make_app()
        with mock.patch.object(ft, "fetch_bytes", return_value=body) as fetch:
            app.weather_index()
            app.weather_index()
        self.assertEqual(fetch.call_count, 1)


class InstallTests(unittest.TestCase):
    def test_boot_config_is_idempotent(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        boot = tmp / "config.txt"
        boot.write_text("[all]\ndtoverlay=vc4-kms-v3d\n", encoding="utf-8")
        for _ in range(3):
            subprocess.run(["bash", str(ROOT / "scripts/boot-config.sh"), str(boot), "c", "14", "60000"], check=True, capture_output=True)
        text = boot.read_text()
        self.assertEqual(text.count("vc4-kms-dsi-waveshare-panel,4_0_inchC"), 1)
        self.assertEqual(text.count("dtoverlay=vc4-kms-v3d"), 1)
        self.assertEqual(text.count("gpio-fan"), 1)
        self.assertTrue((tmp / "config.txt.bak-flight-tracker").is_file())

    def test_release_items_cover_the_tarball(self) -> None:
        text = (ROOT / "install.sh").read_text()
        start = text.index("RELEASE_ITEMS=(") + len("RELEASE_ITEMS=(")
        items = set(text[start:text.index(")", start)].split())
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        import tarfile
        archive = tmp / "t.tar.gz"
        pack_tree(ROOT, archive)
        with tarfile.open(archive) as tar:
            tops = {Path(name).parts[0] for name in tar.getnames()}
        self.assertEqual(tops - items, set())
        self.assertNotIn('"$ROOT/" "$REL/"', text)

    def test_install_keeps_existing_password_and_runs_display_setup(self) -> None:
        text = (ROOT / "install.sh").read_text()
        self.assertIn("Re-running install.sh keeps an existing setup-page password.", text)
        self.assertIn("display_setup.py", text)
        self.assertIn('--user "$TARGET_USER"', text)
        self.assertNotIn("/home/pi", text)


class FrontendStaticTests(unittest.TestCase):
    def test_setup_page_controls(self) -> None:
        html = (ROOT / "setup/index.html").read_text()
        for needle in ('id="wx-on"', 'data-bg="dark"', 'data-bg="light"', 'data-bg="satellite"', 'data-bg="sectional"', 'data-bg="scope"',
                       'id="rings"', 'id="show-clock"', 'id="clock-format"', 'id="minimal-text"', 'placeholder="N123AB, AAL100, A1B2C3"',
                       'id="wifi-scan"', 'id="wifi-hidden"', 'id="wifi-country"', 'pattern="([01][0-9]|2[0-3])[0-5][0-9]"', 'max="16"'):
            self.assertIn(needle, html)
        for button in ("loc-save", "form-save", "night-save", "watch-add", "wifi-join", "sw-later-save", "wifi-country-save"):
            self.assertIn(f'withSave($("{button}")', html, button)
        self.assertIn("SAVED ✓", html)

    def test_display_fixes_in_source(self) -> None:
        main = (ROOT / "src/main.ts").read_text()
        css = (ROOT / "src/style.css").read_text()
        self.assertIn("saveTimer = 0;", main)
        # 1.0.3 compares the whole saved config (rangeNm, rings, background,
        # showClock, and everything else) instead of a field list.
        self.assertIn("configKey(next) !== configKey(config)", main)
        self.assertIn("weather.frames.length - 1", main)
        # 1.0.3 removed the edge keys; test_v103 checks they stay gone.
        self.assertNotIn(".key .key-label", css)
        self.assertIn("#hud.minimal", css)
        for banned in ("backdrop-filter", "mix-blend-mode"):
            self.assertNotIn(banned, css)

    def test_built_assets_are_local(self) -> None:
        html = (ROOT / "dist/index.html").read_text()
        self.assertNotIn("fonts.googleapis", html)
        self.assertTrue(list((ROOT / "dist/assets").glob("ibm-plex-sans-latin-400-normal-*.woff2")))

    @unittest.skipUnless(shutil.which("node") and (ROOT / "node_modules/esbuild").is_dir(), "node/esbuild not installed")
    def test_clock_and_ring_helpers(self) -> None:
        script = """
import { build } from "esbuild";
const out = await build({ stdin: { contents: `
  import { formatClock } from "./src/format";
  import { ringDistances, ringLabelMask } from "./src/rings";
  const d = new Date(2026, 10, 19, 13, 19, 5);
  const am = new Date(2026, 10, 19, 0, 5, 0);
  console.log(JSON.stringify({ h24: formatClock(d), h12: formatClock(d, "12h"), am12: formatClock(am, "12h"), am24: formatClock(am),
    rings5: ringDistances(20, 5), mask: ringLabelMask(6, 60), maskWide: ringLabelMask(4, 300) }));
`, resolveDir: process.cwd(), loader: "ts" }, bundle: true, write: false, format: "esm", platform: "node" });
await import("data:text/javascript;base64," + Buffer.from(out.outputFiles[0].text).toString("base64"));
"""
        result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(data["h24"], "1319")
        self.assertEqual(data["h12"], "1:19 PM")
        self.assertEqual(data["am12"], "12:05 AM")
        self.assertEqual(data["am24"], "0005")
        self.assertEqual(data["rings5"], [4, 8, 12, 16, 20])
        self.assertEqual(data["mask"][-1], True)
        self.assertIn(False, data["mask"])
        self.assertEqual(data["maskWide"], [True, True, True, True])


if __name__ == "__main__":
    unittest.main()
