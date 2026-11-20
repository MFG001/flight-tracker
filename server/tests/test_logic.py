"""Unit tests for feed parsing, demo motion, and config checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from server.airports import search_airports
from server.logic import (
    LEG_SECONDS,
    QuadratureDecoder,
    backlight_value,
    demo_document,
    haversine_nm,
    move_nm,
    normalize_aircraft,
    position_at,
    resolved_feed_url,
    sanitize_config,
    valid_frame_id,
    valid_tile,
)
from server.wifi_net import wifi_escape, wifi_qr_payload


ROOT = Path(__file__).resolve().parents[2]


class FeedTests(unittest.TestCase):
    def test_sample_file_normalizes(self) -> None:
        raw = json.loads((ROOT / "data" / "sample-aircraft.json").read_text())
        rows = normalize_aircraft(raw)
        self.assertEqual(len(rows), 19)
        calls = {row["callsign"] for row in rows}
        self.assertIn("ASA118", calls)
        ground = next(row for row in rows if row["callsign"] == "ASA200")
        self.assertTrue(ground["ground"])
        self.assertEqual(ground["altFt"], 0)

    def test_skips_rows_without_a_position(self) -> None:
        raw = {
            "aircraft": [
                {"hex": "abc123", "flight": "TST1  ", "alt_baro": 1000},
                {"hex": "abc124", "flight": "TST2", "lat": 47.5, "lon": -122.3, "alt_baro": "ground", "gs": 0},
            ]
        }
        rows = normalize_aircraft(raw)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["callsign"], "TST2")
        self.assertTrue(rows[0]["ground"])
        self.assertEqual(rows[0]["id"], "ABC124")

    def test_prefers_position_age_and_baro_altitude(self) -> None:
        rows = normalize_aircraft(
            [
                {
                    "hex": "~a1b2c3",
                    "flight": "UAL1",
                    "lat": 47.0,
                    "lon": -122.0,
                    "alt_baro": 33000,
                    "alt_geom": 33500,
                    "track": 361,
                    "gs": 480,
                    "baro_rate": -64,
                    "seen": 9,
                    "seen_pos": 1.2,
                    "squawk": "1200",
                    "category": "A5",
                }
            ]
        )
        self.assertEqual(rows[0]["track"], 1)
        self.assertEqual(rows[0]["altFt"], 33000)
        self.assertEqual(rows[0]["seenSec"], 1.2)
        self.assertEqual(rows[0]["id"], "A1B2C3")


class MotionTests(unittest.TestCase):
    def test_north_one_hour_at_sixty_knots_is_one_degree(self) -> None:
        lat, lon = move_nm(47.0, -122.0, 0, 60)
        self.assertAlmostEqual(lat, 48.0, places=5)
        self.assertAlmostEqual(lon, -122.0, places=5)

    def test_elapsed_zero_is_the_sample_fix(self) -> None:
        spec = {"lat": 47.45, "lon": -122.3, "track": 90, "gs": 300, "alt_baro": 10000}
        lat, lon, track = position_at(spec, 0)
        self.assertEqual((lat, lon, track), (47.45, -122.3, 90))

    def test_leg_reverses_and_a_full_cycle_returns_home(self) -> None:
        spec = {"lat": 47.0, "lon": -122.0, "track": 0, "gs": 120, "alt_baro": 4000}
        _, _, track = position_at(spec, LEG_SECONDS + 1)
        self.assertEqual(track, 180)
        lat, lon, track = position_at(spec, LEG_SECONDS * 2)
        self.assertAlmostEqual(lat, 47.0, places=4)
        self.assertAlmostEqual(lon, -122.0, places=4)
        self.assertEqual(track, 0)

    def test_demo_document_preserves_count(self) -> None:
        sample = json.loads((ROOT / "data" / "sample-aircraft.json").read_text())["aircraft"]
        doc = demo_document(sample, 30)
        self.assertEqual(len(normalize_aircraft(doc)), 19)


class ConfigTests(unittest.TestCase):
    def test_default_home_is_kjfk(self) -> None:
        from server.logic import DEFAULT_CONFIG

        self.assertEqual(DEFAULT_CONFIG["home"], {"name": "KJFK", "lat": 40.6399, "lon": -73.7787})
        self.assertEqual(DEFAULT_CONFIG["metarStation"], "KJFK")

    def test_rejects_impossible_home_and_bad_url(self) -> None:
        cfg, errors = sanitize_config(
            {
                "home": {"name": "X", "lat": 120, "lon": -122.3},
                "rangeNm": 20,
                "feed": {"mode": "remote", "localPath": "/tmp/aircraft.json", "remoteUrl": "file:///etc/passwd"},
            }
        )
        self.assertTrue(errors)
        self.assertEqual(cfg["home"]["lat"], 40.6399)
        self.assertEqual(cfg["home"]["lon"], -122.3)
        self.assertEqual(cfg["home"]["name"], "X")
        self.assertNotEqual(cfg["feed"]["remoteUrl"], "file:///etc/passwd")

    def test_accepts_a_remote_feed_and_clamps_range(self) -> None:
        cfg, errors = sanitize_config(
            {
                "home": {"name": "KSEA", "lat": 47.45, "lon": -122.31},
                "rangeNm": 500,
                "units": "metric",
                "feed": {
                    "mode": "remote",
                    "localPath": "/run/readsb/aircraft.json",
                    "remoteUrl": "http://192.0.2.8:8080/data/aircraft.json",
                },
                "background": "sectional",
                "weather": {"enabled": True, "opacity": 0.4, "animate": False},
            }
        )
        self.assertEqual(errors, [])
        self.assertEqual(cfg["rangeNm"], 100)  # clamped to the 1.0.7 maximum
        self.assertEqual(cfg["background"], "sectional")
        self.assertTrue(cfg["weather"]["enabled"])
        self.assertEqual(cfg["weather"]["opacity"], 0.4)
        stepped, _ = sanitize_config({"home": {"name": "KSEA", "lat": 47.45, "lon": -122.31}, "rangeNm": 20, "weather": {"opacity": 0.66}})
        self.assertEqual(stepped["weather"]["opacity"], 0.7)
        self.assertEqual(cfg["feed"]["remoteUrl"], "http://192.0.2.8:8080/data/aircraft.json")

    def test_duplicate_gpio_is_rejected(self) -> None:
        _, errors = sanitize_config(
            {
                "home": {"name": "KSEA", "lat": 47.45, "lon": -122.3},
                "rangeNm": 20,
                "gpio": {"enabled": True, "pins": {"MAP": 5, "TFC": 5}},
            }
        )
        self.assertTrue(any("GPIO 5" in message for message in errors))


class TileAndEncoderTests(unittest.TestCase):
    def test_tile_bounds(self) -> None:
        self.assertTrue(valid_tile(10, 163, 395, 0, 19))
        self.assertTrue(valid_tile(10, 163, 395, 8, 12))
        self.assertFalse(valid_tile(7, 20, 49, 8, 12))
        self.assertFalse(valid_tile(4, -1, 2, 0, 10))
        self.assertFalse(valid_tile(4, 20, 2, 0, 10))
        self.assertTrue(valid_frame_id("aaffe2966fca"))
        self.assertFalse(valid_frame_id("../etc"))
        self.assertFalse(valid_frame_id("ab"))

    def test_clockwise_detent(self) -> None:
        decoder = QuadratureDecoder()
        steps = []
        # Gray sequence 00 -> 01 -> 11 -> 10 -> 00 is one clockwise detent.
        for clk, dt in ((0, 1), (1, 1), (1, 0), (0, 0)):
            steps.append(decoder.update(clk, dt))
        self.assertEqual(sum(steps), 1)

    def test_counterclockwise_detent(self) -> None:
        decoder = QuadratureDecoder()
        total = 0
        for clk, dt in ((1, 0), (1, 1), (0, 1), (0, 0)):
            total += decoder.update(clk, dt)
        self.assertEqual(total, -1)

    def test_feed_url_uses_host_and_port_or_an_explicit_url(self) -> None:
        self.assertEqual(resolved_feed_url({"host": "receiver.local", "port": 8080, "remoteUrl": ""}), "http://receiver.local:8080/data/aircraft.json")
        self.assertEqual(resolved_feed_url({"host": "receiver.local", "port": 8080, "remoteUrl": "http://192.0.2.5/data/aircraft.json"}), "http://192.0.2.5/data/aircraft.json")

    def test_wifi_qr_uses_the_wpa_uri(self) -> None:
        self.assertEqual(wifi_qr_payload("FlightTracker-Setup", "ABCD2345"), "WIFI:T:WPA;S:FlightTracker-Setup;P:ABCD2345;;")
        self.assertEqual(wifi_escape("a:b;c"), r"a\:b\;c")

    def test_airport_code_search_is_local(self) -> None:
        found = search_airports("KSEA")
        self.assertEqual(found[0]["icao"], "KSEA")
        by_iata = search_airports("SEA")
        self.assertEqual(by_iata[0]["icao"], "KSEA")
        self.assertEqual(by_iata[0]["iata"], "SEA")
        heathrow = search_airports("LHR")
        self.assertEqual(heathrow[0]["icao"], "EGLL")
        self.assertEqual(search_airports("ZZZZ"), [])
        self.assertAlmostEqual(found[0]["lat"], 47.45, delta=0.05)

    def test_sweep_defaults_off_and_speed_stays_between_three_and_sixteen(self) -> None:
        cfg, errors = sanitize_config({"home": {"name": "KSEA", "lat": 47.45, "lon": -122.3}, "rangeNm": 20, "sweep": {"enabled": True, "periodSec": 30}})
        self.assertEqual(errors, [])
        self.assertTrue(cfg["sweep"]["enabled"])
        self.assertEqual(cfg["sweep"]["periodSec"], 16)
        fast, _ = sanitize_config({"home": {"name": "KSEA", "lat": 47.45, "lon": -122.3}, "rangeNm": 20, "sweep": {"enabled": True, "periodSec": 1}})
        self.assertEqual(fast["sweep"]["periodSec"], 3)
        plain, _ = sanitize_config({"home": {"name": "KSEA", "lat": 47.45, "lon": -122.3}, "rangeNm": 20})
        self.assertFalse(plain["sweep"]["enabled"])
        self.assertEqual(plain["sweep"]["periodSec"], 8)

    def test_backlight_is_linear_across_the_documented_range(self) -> None:
        self.assertEqual(backlight_value(0), 0)
        self.assertEqual(backlight_value(100), 255)
        self.assertEqual(backlight_value(50), 128)
        self.assertEqual(backlight_value(80), 204)

    def test_haversine_zero(self) -> None:
        self.assertEqual(haversine_nm(47.4, -122.3, 47.4, -122.3), 0)


if __name__ == "__main__":
    unittest.main()
