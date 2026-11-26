"""Sunrise/sunset night dim uses a US ZIP or coordinates, not the map center."""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from server.logic import CONFIG_SCHEMA, DEFAULT_CONFIG, sanitize_config  # noqa: E402
from server.migrate import migrate_config  # noqa: E402
from server.night import compute_night_status, format_clock, solar_preview  # noqa: E402
from server.zcta import lookup_zip, zip_error  # noqa: E402

# Neutral public sample used in tests and the setup placeholder. Not a personal ZIP.
SAMPLE_ZIP = "10001"
ET = timezone(timedelta(hours=-5))


def night_cfg(**extra):
    night = {
        "mode": "off",
        "fromHour": 22,
        "toHour": 6,
        "from": "2200",
        "to": "0600",
        "brightness": 25,
        "loc": "zip",
        "zip": "",
        "lat": None,
        "lon": None,
    }
    night.update(extra)
    return {"home": {"name": "KJFK", "lat": 40.6399, "lon": -73.7787}, "night": night}


class ZipTableTests(unittest.TestCase):
    def test_sample_zip_resolves_offline(self) -> None:
        found = lookup_zip(SAMPLE_ZIP)
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found["zip"], SAMPLE_ZIP)
        self.assertEqual(found["label"], "ZIP 10001")
        self.assertAlmostEqual(found["lat"], 40.7506, places=3)
        self.assertAlmostEqual(found["lon"], -73.9973, places=3)

    def test_unknown_and_empty_zip_have_clear_errors(self) -> None:
        self.assertIn("Enter your ZIP code", zip_error(""))
        self.assertEqual(zip_error("00000"), "That ZIP code was not found.")
        self.assertEqual(zip_error("abcde"), "Enter a 5-digit US ZIP code.")
        self.assertEqual(zip_error(SAMPLE_ZIP), "")
        self.assertIsNone(lookup_zip("00000"))


class SolarPreviewTests(unittest.TestCase):
    def test_preview_zip_returns_tonight_times(self) -> None:
        when = datetime(2026, 1, 15, 12, 0, tzinfo=ET)
        body = solar_preview(SAMPLE_ZIP, when=when)
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["label"], "ZIP 10001")
        self.assertRegex(body["sunsetAt"], r"^\d{2}:\d{2}$")
        self.assertRegex(body["sunriseAt"], r"^\d{2}:\d{2}$")
        # Mid-January in this area, sunset is late afternoon, not the custom 22:00.
        self.assertNotEqual(body["sunsetAt"], "22:00")
        self.assertGreater(body["sunset"], 16)
        self.assertLess(body["sunset"], 18)

    def test_preview_rejects_unknown_zip(self) -> None:
        body = solar_preview("00000")
        self.assertFalse(body["ok"])
        self.assertEqual(body["detail"], "That ZIP code was not found.")

    def test_preview_accepts_coordinates(self) -> None:
        when = datetime(2026, 1, 15, 12, 0, tzinfo=ET)
        body = solar_preview("", 40.75, -74.0, when=when)
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["kind"], "ll")
        self.assertIn("40.7500", body["label"])
        self.assertRegex(body["sunsetAt"], r"^\d{2}:\d{2}$")


class NightStatusTests(unittest.TestCase):
    def test_sun_mode_uses_solar_times_not_custom_hours(self) -> None:
        # 21:00 is after January sunset at this ZIP, but before the saved 22:00 custom start.
        when = datetime(2026, 1, 15, 21, 0, tzinfo=ET)
        solar = compute_night_status(night_cfg(mode="sun", loc="zip", zip=SAMPLE_ZIP), when)
        custom = compute_night_status(night_cfg(mode="schedule"), when)
        self.assertTrue(solar["night"], solar)
        self.assertFalse(custom["night"], custom)
        self.assertFalse(solar["usingScheduleFallback"])
        self.assertFalse(solar["needsLocation"])
        self.assertEqual(solar["location"]["label"], "ZIP 10001")
        self.assertNotEqual(solar["sunsetAt"], "22:00")

    def test_sun_mode_without_location_falls_back_to_custom_hours(self) -> None:
        when = datetime(2026, 1, 15, 21, 0, tzinfo=ET)
        status = compute_night_status(night_cfg(mode="sun", loc="zip", zip=""), when)
        self.assertTrue(status["needsLocation"])
        self.assertTrue(status["usingScheduleFallback"])
        self.assertFalse(status["night"], status)  # 21:00 is before 22:00
        self.assertIn("ZIP", status["detail"])
        later = compute_night_status(night_cfg(mode="sun", loc="zip", zip=""), datetime(2026, 1, 15, 23, 0, tzinfo=ET))
        self.assertTrue(later["night"])
        self.assertTrue(later["usingScheduleFallback"])

    def test_sun_mode_coordinates_do_not_use_map_center(self) -> None:
        when = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
        # A far-west point: solar times should differ from the default KJFK home.
        west = compute_night_status(
            night_cfg(mode="sun", loc="ll", zip="", lat=34.05, lon=-118.25),
            when,
        )
        east = compute_night_status(night_cfg(mode="sun", loc="zip", zip=SAMPLE_ZIP), when)
        self.assertTrue(west["location"]["lat"] == 34.05)
        self.assertIsNotNone(west["sunsetAt"])
        self.assertIsNotNone(east["sunsetAt"])
        self.assertNotEqual(west["sunsetAt"], east["sunsetAt"])

    def test_clock_format(self) -> None:
        self.assertEqual(format_clock(7.25), "07:15")
        self.assertEqual(format_clock(16 + 42 / 60), "16:42")


class SanitizeAndMigrateTests(unittest.TestCase):
    def test_cannot_save_sunrise_mode_without_a_location(self) -> None:
        _, errors = sanitize_config(dict(DEFAULT_CONFIG, night={"mode": "sun", "loc": "zip", "zip": "", "from": "2200", "to": "0600", "brightness": 25}))
        self.assertTrue(errors)
        self.assertTrue(any("ZIP" in err or "coordinates" in err for err in errors), errors)

    def test_unknown_zip_is_rejected(self) -> None:
        _, errors = sanitize_config(dict(DEFAULT_CONFIG, night={"mode": "sun", "loc": "zip", "zip": "00000", "from": "2200", "to": "0600", "brightness": 25}))
        self.assertTrue(any("not found" in err.lower() for err in errors), errors)

    def test_valid_zip_saves_sun_mode(self) -> None:
        cfg, errors = sanitize_config(dict(DEFAULT_CONFIG, night={"mode": "sun", "loc": "zip", "zip": SAMPLE_ZIP, "from": "2200", "to": "0600", "brightness": 25}))
        self.assertEqual(errors, [])
        self.assertEqual(cfg["night"]["mode"], "sun")
        self.assertEqual(cfg["night"]["zip"], SAMPLE_ZIP)
        self.assertAlmostEqual(float(cfg["night"]["lat"]), 40.7506, places=3)

    def test_coordinates_save_sun_mode(self) -> None:
        cfg, errors = sanitize_config(dict(DEFAULT_CONFIG, night={"mode": "sun", "loc": "ll", "lat": 51.5, "lon": -0.12, "from": "2200", "to": "0600", "brightness": 25}))
        self.assertEqual(errors, [])
        self.assertEqual(cfg["night"]["loc"], "ll")
        self.assertEqual(cfg["night"]["lat"], 51.5)

    def test_bad_coordinates_are_rejected(self) -> None:
        _, errors = sanitize_config(dict(DEFAULT_CONFIG, night={"mode": "sun", "loc": "ll", "lat": 100, "lon": 0, "from": "2200", "to": "0600", "brightness": 25}))
        self.assertTrue(any("latitude" in err.lower() for err in errors), errors)

    def test_schema_6_is_idempotent_and_keeps_existing_sun_mode_safe(self) -> None:
        self.assertEqual(CONFIG_SCHEMA, 6)
        first = migrate_config({"schema": 5, "night": {"mode": "sun", "from": "2130", "to": "0545", "fromHour": 21, "toHour": 5, "brightness": 20}})
        self.assertEqual(first["schema"], 6)
        self.assertEqual(first["night"]["mode"], "sun")
        self.assertEqual(first["night"]["zip"], "")
        self.assertEqual(first["night"]["loc"], "zip")
        self.assertEqual(first["night"]["from"], "2130")
        again = migrate_config(dict(first))
        self.assertEqual(again["schema"], 6)
        self.assertEqual(again["night"]["mode"], "sun")
        self.assertEqual(again["night"]["zip"], "")
        # Runtime still falls back to the saved hours instead of crashing.
        when = datetime(2026, 1, 15, 22, 30, tzinfo=ET)
        status = compute_night_status({"night": again["night"]}, when)
        self.assertTrue(status["usingScheduleFallback"])
        self.assertTrue(status["night"])


class HtmlAndApiPresenceTests(unittest.TestCase):
    def test_setup_page_has_zip_or_coordinates_and_hides_custom_times(self) -> None:
        html = (ROOT / "setup/index.html").read_text(encoding="utf-8")
        self.assertIn('id="night-zip"', html)
        self.assertIn('id="night-lat"', html)
        self.assertIn('id="night-lon"', html)
        self.assertIn("US ZIP CODE", html)
        self.assertIn("OUTSIDE THE US", html)
        self.assertIn("Enter your ZIP code to use sunrise/sunset", html)
        self.assertIn("/api/solar", html)
        self.assertIn("night-schedule-fields", html)
        self.assertIn("night-sun-fields", html)
        server = (ROOT / "server/flighttracker.py").read_text()
        self.assertIn('path == "/api/solar"', server)
        self.assertIn("compute_night_status", server)

    def test_example_config_schema_is_current(self) -> None:
        example = json.loads((ROOT / "data/config.example.json").read_text())
        self.assertEqual(example["schema"], CONFIG_SCHEMA)
        self.assertEqual(example["night"]["loc"], "zip")
        self.assertEqual(example["night"]["zip"], "")


if __name__ == "__main__":
    unittest.main()
