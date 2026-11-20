"""Weather on the glass must keep refreshing (1.0.3).

A unit showed the weather once after start, then it froze. These tests
move a fake clock forward instead of sleeping.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time as real_time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

import server.flighttracker as ft  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 40


class FakeTime:
    """Stands in for the time module inside server.flighttracker."""

    def __init__(self) -> None:
        self.wall = real_time.time()
        self.mono = 1000.0

    def time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        self.wall += seconds
        self.mono += seconds


def rainviewer_body(*ids: str) -> bytes:
    past = [{"time": 1_795_000_000 + 600 * n, "path": f"/v2/radar/{frame}"} for n, frame in enumerate(ids)]
    return json.dumps({"radar": {"past": past}}).encode()


def make_app(cache: Path | None = None) -> ft.App:
    app = ft.App.__new__(ft.App)
    app.weather_cache = {"at": 0.0, "body": None}
    app.metar_cache = {"at": 0.0, "key": None, "body": None}
    if cache is not None:
        app.cache = cache
    return app


class Upstream:
    """Scripted internet: RainViewer, IEM, and aviationweather.gov."""

    def __init__(self) -> None:
        self.rainviewer: bytes | Exception = RuntimeError("HTTP 503")
        self.iem_ok = True
        self.iem_version = 1
        self.metar: bytes | Exception = RuntimeError("offline")
        self.calls: list[str] = []

    def __call__(self, url: str, **_kwargs) -> bytes:
        self.calls.append(url)
        if "rainviewer.com/public" in url:
            if isinstance(self.rainviewer, Exception):
                raise self.rainviewer
            return self.rainviewer
        if "tilecache.rainviewer.com" in url:
            return PNG + url.encode()
        if "mesonet.agron.iastate.edu" in url:
            if not self.iem_ok:
                raise RuntimeError("IEM down")
            return PNG + f"iem-v{self.iem_version}".encode()
        if "aviationweather.gov" in url:
            if isinstance(self.metar, Exception):
                raise self.metar
            return self.metar
        raise AssertionError(url)


def metar_rows(raw: str, obs_time: float, temp: float = 22.0) -> bytes:
    return json.dumps([{
        "icaoId": "KJFK", "name": "New York/JFK Intl", "rawOb": raw, "lat": 40.64, "lon": -73.78,
        "temp": temp, "wdir": 110, "wspd": 12, "obsTime": int(obs_time),
    }]).encode()


class WeatherFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeTime()
        self.net = Upstream()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for patch in (mock.patch.object(ft, "time", self.clock), mock.patch.object(ft, "fetch_bytes", side_effect=self.net)):
            patch.start()
            self.addCleanup(patch.stop)

    def age_files(self, seconds: float) -> None:
        """Files written now are `seconds` older on the fake clock too."""
        for path in self.tmp.rglob("*"):
            if path.is_file():
                stamp = path.stat().st_mtime - seconds
                os.utime(path, (stamp, stamp))

    def test_iem_frame_id_changes_every_five_minutes(self) -> None:
        # 1.0.2 named the IEM frame "latest" for ever: same URL, same cache file.
        app = make_app(self.tmp)
        first = app.weather_index()
        self.assertEqual(first["provider"], "iem")
        self.clock.advance(6 * 60)
        second = app.weather_index()
        self.assertEqual(second["provider"], "iem")
        self.assertNotEqual(first["frames"][-1]["id"], second["frames"][-1]["id"])
        self.assertNotEqual(first["frames"][-1]["id"], "latest")
        self.assertGreater(second["frames"][-1]["time"], first["frames"][-1]["time"])

    def test_iem_radar_picture_refreshes(self) -> None:
        app = make_app(self.tmp)
        frame = app.weather_index()["frames"][-1]["id"]
        status, data = app.weather_tile(frame, 5, 8, 13)
        self.assertEqual(status, 200)
        self.assertTrue(data.endswith(b"iem-v1"))
        # Same slot: served from disk, no new download.
        before = len(self.net.calls)
        self.assertEqual(app.weather_tile(frame, 5, 8, 13), (200, data))
        self.assertEqual(len(self.net.calls), before)
        # IEM redraws its composite; 6 minutes later the glass gets it.
        self.net.iem_version = 2
        self.clock.advance(6 * 60)
        self.age_files(6 * 60)
        newer = app.weather_index()["frames"][-1]["id"]
        status, data = app.weather_tile(newer, 5, 8, 13)
        self.assertEqual(status, 200)
        self.assertTrue(data.endswith(b"iem-v2"), data)

    def test_iem_previous_slot_still_served_at_rollover(self) -> None:
        app = make_app(self.tmp)
        old = app.weather_index()["frames"][-1]["id"]
        self.clock.advance(5 * 60)
        app.weather_index()
        self.assertEqual(app.weather_tile(old, 5, 8, 13)[0], 200)
        self.assertEqual(app.weather_tile("iem1", 5, 8, 13)[0], 404)
        self.assertEqual(app.weather_tile("latest", 5, 8, 13)[0], 404)

    def test_rainviewer_new_frames_reach_the_glass(self) -> None:
        self.net.rainviewer = rainviewer_body("aaaa1111")
        app = make_app(self.tmp)
        self.assertEqual(app.weather_index()["frames"][-1]["id"], "aaaa1111")
        self.net.rainviewer = rainviewer_body("aaaa1111", "bbbb2222")
        self.clock.advance(60)
        self.assertEqual(app.weather_index()["frames"][-1]["id"], "aaaa1111")  # 2-minute rate limit
        self.clock.advance(70)
        self.assertEqual(app.weather_index()["frames"][-1]["id"], "bbbb2222")
        self.assertEqual(app.weather_tile("bbbb2222", 6, 17, 27)[0], 200)

    def test_index_recovers_after_network_error(self) -> None:
        self.net.iem_ok = False
        app = make_app(self.tmp)
        down = app.weather_index()
        self.assertFalse(down["ok"])
        self.net.rainviewer = rainviewer_body("cccc3333")
        self.clock.advance(61)
        up = app.weather_index()
        self.assertTrue(up["ok"])
        self.assertEqual(up["frames"][-1]["id"], "cccc3333")

    def test_returns_to_rainviewer_after_iem(self) -> None:
        app = make_app(self.tmp)
        self.assertEqual(app.weather_index()["provider"], "iem")
        self.net.rainviewer = rainviewer_body("dddd4444")
        self.clock.advance(61)
        self.assertEqual(app.weather_index()["provider"], "rainviewer")

    def test_wall_clock_step_back_does_not_pin_the_cache(self) -> None:
        self.net.rainviewer = rainviewer_body("eeee5555")
        app = make_app(self.tmp)
        app.weather_index()
        self.net.rainviewer = rainviewer_body("eeee5555", "ffff6666")
        self.clock.mono += 3 * 60
        self.clock.wall -= 3600  # NTP steps the wall clock back an hour
        self.assertEqual(app.weather_index()["frames"][-1]["id"], "ffff6666")

    def test_failed_radar_tile_is_retried_after_a_minute(self) -> None:
        self.net.rainviewer = rainviewer_body("abab1212")
        app = make_app(self.tmp)
        app.weather_index()
        with mock.patch.object(ft, "fetch_bytes", side_effect=RuntimeError("Wi-Fi blip")):
            self.assertEqual(app.weather_tile("abab1212", 6, 17, 27)[0], 404)
        self.clock.advance(61)
        self.age_files(61)
        self.assertEqual(app.weather_tile("abab1212", 6, 17, 27)[0], 200)

    def test_old_radar_frames_are_pruned(self) -> None:
        root = self.tmp / "weather"
        old = root / "rainviewer" / "old1"
        new = root / "rainviewer" / "new1"
        latest = root / "iem" / "latest"
        for folder in (old, new, latest):
            (folder / "7").mkdir(parents=True)
        stamp = real_time.time() - 4 * 3600
        os.utime(old, (stamp, stamp))
        os.utime(latest, (stamp, stamp))
        self.assertEqual(ft.prune_weather_cache(root, real_time.time() - ft.WEATHER_KEEP_SEC), 2)
        self.assertFalse(old.exists())
        self.assertFalse(latest.exists())
        self.assertTrue(new.exists())


class MetarRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeTime()
        self.net = Upstream()
        for patch in (mock.patch.object(ft, "time", self.clock), mock.patch.object(ft, "fetch_bytes", side_effect=self.net)):
            patch.start()
            self.addCleanup(patch.stop)
        self.app = make_app()

    def get(self):
        return self.app.metar(40.64, -73.78, "KJFK")

    def test_new_report_is_picked_up(self) -> None:
        self.net.metar = metar_rows("METAR KJFK 192253Z 11012KT 10SM 22/21 A2999", self.clock.wall - 300)
        self.assertIn("192253Z", self.get()["raw"])
        self.net.metar = metar_rows("METAR KJFK 192353Z 12010KT 10SM 21/20 A3000", self.clock.wall)
        self.clock.advance(60)
        self.assertIn("192253Z", self.get()["raw"])  # 2-minute rate limit
        self.clock.advance(61)
        self.assertIn("192353Z", self.get()["raw"])

    def test_failure_keeps_last_report_marked_stale_then_recovers(self) -> None:
        self.net.metar = metar_rows("METAR KJFK 192253Z 11012KT 10SM 22/21 A2999", self.clock.wall - 300)
        first = self.get()
        self.assertFalse(first.get("stale"))
        self.net.metar = RuntimeError("offline")
        self.clock.advance(121)
        kept = self.get()
        self.assertIsNotNone(kept)
        self.assertTrue(kept["stale"])
        self.assertEqual(kept["raw"], first["raw"])
        # Failing: retried after 60 s, not 120 s.
        self.net.metar = metar_rows("METAR KJFK 192353Z 12010KT 10SM 21/20 A3000", self.clock.wall)
        self.clock.advance(61)
        back = self.get()
        self.assertFalse(back.get("stale"))
        self.assertIn("192353Z", back["raw"])

    def test_very_old_report_is_dropped(self) -> None:
        self.net.metar = metar_rows("METAR KJFK 192253Z 11012KT 10SM 22/21 A2999", self.clock.wall)
        self.get()
        self.net.metar = RuntimeError("offline")
        self.clock.advance(3 * 3600 + 60)
        self.assertIsNone(self.get())


class WeatherTileRouteTests(unittest.TestCase):
    def test_http_route_serves_new_iem_frame(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        net = Upstream()
        patch = mock.patch.object(ft, "fetch_bytes", side_effect=net)
        patch.start()
        self.addCleanup(patch.stop)
        app = make_app(tmp)
        server = ThreadingHTTPServer(("127.0.0.1", 0), ft.make_handler(app))
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        index = json.loads(urllib.request.urlopen(f"{base}/api/weather", timeout=5).read())
        frame = index["frames"][-1]["id"]
        self.assertRegex(frame, r"^iem\d+$")
        with urllib.request.urlopen(f"{base}/api/weather/{frame}/5/8/13.png", timeout=5) as response:
            self.assertEqual(response.headers["Content-Type"], "image/png")
            self.assertTrue(response.read().endswith(b"iem-v1"))
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{base}/api/weather/latest/5/8/13.png", timeout=5)
        self.assertEqual(caught.exception.code, 404)


class DisplaySourceTests(unittest.TestCase):
    main = (ROOT / "src/main.ts").read_text(encoding="utf-8")

    def test_display_polls_weather_and_metar(self) -> None:
        self.assertIn("window.setInterval(() => void pollWeather().catch(() => undefined), 60000);", self.main)
        self.assertIn("window.setInterval(() => void pollMetar().catch(() => undefined), 240000);", self.main)
        self.assertIn("dropOldRadarTiles();", self.main)
        # 1.0.7: chip wording moved to src/wxstatus.ts.
        self.assertIn('"WX STALE"', (ROOT / "src/wxstatus.ts").read_text(encoding="utf-8"))
        self.assertIn("wxSummary(", self.main)
        self.assertIn('classList.toggle("stale", metarStale(metar))', self.main)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_short_metar_keeps_the_observation_time(self) -> None:
        match = re.search(r"function shortMetar\(report: MetarReport\): string \{\n(.*?)\n\}", self.main, re.S)
        self.assertIsNotNone(match)
        js = "function shortMetar(report) {\n" + match.group(1) + "\n}\n"
        js += "for (const raw of JSON.parse(process.argv[1])) console.log(shortMetar({ raw }));"
        cases = [
            "KJFK 192253Z AUTO 11012G18KT 7SM -RA FEW009 BKN043 OVC050 22/21 A2999 RMK AO2",
            "KJFK 192353Z 12010KT 10SM FEW030 21/20 A3000",
        ]
        out = subprocess.run(["node", "-e", js, json.dumps(cases)], capture_output=True, text=True, timeout=20, check=True).stdout.split("\n")
        self.assertEqual(out[0], "KJFK 2253Z 11012G18KT 7SM -RA FEW009")
        self.assertEqual(out[1], "KJFK 2353Z 12010KT 10SM FEW030 21/20")
        self.assertNotEqual(out[0], out[1])


if __name__ == "__main__":
    unittest.main()
