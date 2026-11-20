"""adsb.fi feed: URL building, parsing, rate limit, backoff, fallback, migration."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from server.adsbfi import (
    MAX_RADIUS_NM,
    AdsbFiFeed,
    HttpStatusError,
    query_radius_nm,
    radius_url,
    to_feed_document,
)
from server.logic import DEFAULT_CONFIG, normalize_aircraft, sanitize_config
from server.migrate import migrate_config

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "adsbfi_v3_sample.json").read_text())


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class UrlTests(unittest.TestCase):
    def test_radius_url_for_kjfk(self) -> None:
        self.assertEqual(
            radius_url(40.6399, -73.7787, 27),
            "https://opendata.adsb.fi/api/v3/lat/40.6399/lon/-73.7787/dist/27",
        )

    def test_radius_is_padded_and_capped(self) -> None:
        self.assertEqual(query_radius_nm(20), 27)
        self.assertEqual(query_radius_nm(1000), MAX_RADIUS_NM)
        self.assertEqual(query_radius_nm("junk"), 27)
        self.assertEqual(query_radius_nm(1), 5)

    def test_bad_home_rejected(self) -> None:
        with self.assertRaises(ValueError):
            radius_url(95, 0, 10)


class ParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = {r["hex"]: r for r in normalize_aircraft(to_feed_document(FIXTURE))}

    def test_rows_without_position_are_dropped(self) -> None:
        self.assertEqual(len(self.rows), 4)
        self.assertNotIn("A4B5C6", self.rows)

    def test_airborne_jet(self) -> None:
        r = self.rows["A1B2C3"]
        self.assertEqual(r["callsign"], "TST101")
        self.assertEqual(r["registration"], "N101TS")
        self.assertEqual(r["typeCode"], "A320")
        self.assertEqual(r["altFt"], 36000)
        self.assertFalse(r["ground"])
        self.assertEqual(r["gsKt"], 437.0)
        self.assertAlmostEqual(r["track"], 323.6)
        self.assertEqual(r["squawk"], "3741")
        self.assertFalse(r["emergency"])
        self.assertEqual(r["seenSec"], 0.2)

    def test_ground_and_heading_fallback(self) -> None:
        r = self.rows["A2B3C4"]
        self.assertTrue(r["ground"])
        self.assertEqual(r["altFt"], 0)
        self.assertEqual(r["track"], 95.0)

    def test_message_source_type_is_not_aircraft_type(self) -> None:
        r = self.rows["A3B4C5"]
        self.assertIsNone(r["typeCode"])
        self.assertEqual(r["callsign"], "A3B4C5")
        self.assertAlmostEqual(r["track"], 40.0)
        self.assertTrue(r["emergency"])
        self.assertIsNone(self.rows["0D1E2F"]["typeCode"])
        self.assertEqual(self.rows["0D1E2F"]["altFt"], 900)

    def test_document_shape(self) -> None:
        doc = to_feed_document(FIXTURE)
        self.assertEqual(doc["provider"], "adsb.fi")
        self.assertAlmostEqual(doc["now"], 1795050456.001)
        self.assertEqual(doc["aircraft"][2]["source"], "mlat")
        self.assertEqual(to_feed_document({"ac": [], "msg": "No error"})["aircraft"], [])
        with self.assertRaises(ValueError):
            to_feed_document([1, 2])
        with self.assertRaises(ValueError):
            to_feed_document({"ac": "x"})


class PollerTests(unittest.TestCase):
    def make(self, responses):
        calls = []

        def fetch(url, ua, timeout):
            calls.append((url, ua, timeout))
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        clock = FakeClock()
        return AdsbFiFeed("FlightTracker/test", fetch=fetch, clock=clock, min_interval=5), clock, calls

    def test_rate_limit_and_cache(self) -> None:
        feed, clock, calls = self.make([FIXTURE, FIXTURE])
        a = feed.get(40.6399, -73.7787, 20)
        self.assertEqual(len(a["doc"]["aircraft"]), 5)
        for _ in range(20):
            clock.t += 0.2
            feed.get(40.6399, -73.7787, 20)
        self.assertEqual(len(calls), 1)  # 4 s later: still cached
        clock.t += 1.5
        feed.get(40.6399, -73.7787, 20)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1], "FlightTracker/test")
        self.assertGreater(calls[0][2], 0)

    def test_minimum_interval_floor(self) -> None:
        feed = AdsbFiFeed("ua", fetch=lambda *a: FIXTURE, min_interval=0.1)
        self.assertGreaterEqual(feed.min_interval, 1.5)

    def test_stale_then_error_with_backoff(self) -> None:
        feed, clock, calls = self.make([FIXTURE, RuntimeError("offline"), RuntimeError("offline")])
        feed.get(40.6, -73.8, 20)
        clock.t += 5
        r = feed.get(40.6, -73.8, 20)
        self.assertTrue(r["stale"])
        self.assertIsNotNone(r["doc"])
        self.assertIn("offline", r["error"])
        clock.t += 5  # backoff is 10 s after the first failure
        feed.get(40.6, -73.8, 20)
        self.assertEqual(len(calls), 2)
        clock.t += 6
        feed.get(40.6, -73.8, 20)
        self.assertEqual(len(calls), 3)
        clock.t += 120
        r = feed.get(40.6, -73.8, 20)  # not due yet (20 s backoff passed, but cache too old)
        self.assertIsNone(r["doc"])
        self.assertIsNotNone(r["error"])

    def test_429_backs_off_a_minute(self) -> None:
        feed, clock, calls = self.make([HttpStatusError(429), FIXTURE])
        r = feed.get(40.6, -73.8, 20)
        self.assertIsNone(r["doc"])
        self.assertIn("429", r["error"])
        clock.t += 59
        feed.get(40.6, -73.8, 20)
        self.assertEqual(len(calls), 1)
        clock.t += 2
        r = feed.get(40.6, -73.8, 20)
        self.assertEqual(len(calls), 2)
        self.assertIsNone(r["error"])

    def test_home_change_drops_old_traffic(self) -> None:
        feed, clock, calls = self.make([FIXTURE, RuntimeError("x")])
        feed.get(40.6, -73.8, 20)
        clock.t += 5
        r = feed.get(40.0, -75.0, 20)
        self.assertIsNone(r["doc"])
        self.assertIn("40.0000", calls[1][0])


class ConfigTests(unittest.TestCase):
    def test_default_is_adsbfi(self) -> None:
        self.assertEqual(DEFAULT_CONFIG["feed"]["mode"], "adsbfi")
        example = json.loads((Path(__file__).resolve().parents[2] / "data" / "config.example.json").read_text())
        self.assertEqual(example["feed"]["mode"], "adsbfi")

    def test_all_modes_selectable(self) -> None:
        for mode in ("adsbfi", "local", "remote", "demo"):
            payload = deepcopy(DEFAULT_CONFIG)
            payload["feed"]["mode"] = mode
            cfg, errors = sanitize_config(payload)
            self.assertEqual(errors, [])
            self.assertEqual(cfg["feed"]["mode"], mode)
        payload = deepcopy(DEFAULT_CONFIG)
        payload["feed"]["mode"] = "fr24"
        _, errors = sanitize_config(payload)
        self.assertTrue(errors)

    def test_migration_moves_only_untouched_local_default(self) -> None:
        cfg = {"schema": 1, "feed": {"mode": "local", "localPath": "/run/readsb/aircraft.json"}}
        self.assertEqual(migrate_config(cfg, path_exists=lambda p: False)["feed"]["mode"], "adsbfi")
        cfg = {"schema": 1, "feed": {"mode": "local", "localPath": "/run/readsb/aircraft.json"}}
        self.assertEqual(migrate_config(cfg, path_exists=lambda p: True)["feed"]["mode"], "local")
        cfg = {"schema": 1, "feed": {"mode": "remote", "localPath": "/run/readsb/aircraft.json"}}
        self.assertEqual(migrate_config(cfg, path_exists=lambda p: False)["feed"]["mode"], "remote")
        self.assertEqual(cfg["schema"], 3)


if __name__ == "__main__":
    unittest.main()
