"""1.0.20: sunrise/sunset night dim uses a ZIP or coordinates for this unit."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from server.logic import CONFIG_SCHEMA, DEFAULT_CONFIG  # noqa: E402
from server.migrate import migrate_config  # noqa: E402
from server.night import compute_night_status  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402


class VersionPinTests(unittest.TestCase):
    def test_version_is_1020_everywhere(self) -> None:
        self.assertEqual((ROOT / "VERSION").read_text().strip(), "1.0.20")
        self.assertEqual(json.loads((ROOT / "package.json").read_text())["version"], "1.0.20")
        lock = json.loads((ROOT / "package-lock.json").read_text())
        self.assertEqual((lock["version"], lock["packages"][""]["version"]), ("1.0.20", "1.0.20"))
        self.assertIn("FlightTracker/1.0.20 ", (ROOT / "server/flighttracker.py").read_text())
        self.assertEqual(CONFIG_SCHEMA, 6)
        self.assertEqual(DEFAULT_CONFIG["schema"], 6)
        self.assertEqual(DEFAULT_CONFIG["night"]["loc"], "zip")
        self.assertEqual(DEFAULT_CONFIG["night"]["zip"], "")


class FeaturePresenceTests(unittest.TestCase):
    def test_setup_uses_zip_or_coordinates_and_hides_custom_hours(self) -> None:
        html = (ROOT / "setup/index.html").read_text(encoding="utf-8")
        self.assertIn('id="night-zip"', html)
        self.assertIn('id="night-lat"', html)
        self.assertIn('id="night-lon"', html)
        self.assertIn("US ZIP CODE", html)
        self.assertIn("OUTSIDE THE US", html)
        self.assertIn("Enter your ZIP code to use sunrise/sunset", html)
        self.assertIn("night-schedule-fields", html)
        self.assertIn("night-sun-fields", html)
        self.assertIn("/api/solar", html)
        ft = (ROOT / "server/flighttracker.py").read_text()
        self.assertIn('path == "/api/solar"', ft)
        self.assertIn('path == "/api/zip"', ft)
        self.assertTrue((ROOT / "data/zcta-centroids.tsv.gz").is_file())

    def test_schema_6_is_idempotent_and_keeps_sun_mode_safe_without_a_zip(self) -> None:
        first = migrate_config({"schema": 5, "night": {"mode": "sun", "from": "2130", "to": "0545", "fromHour": 21, "toHour": 5, "brightness": 20}})
        self.assertEqual(first["schema"], 6)
        self.assertEqual(first["night"]["mode"], "sun")
        self.assertEqual(first["night"]["zip"], "")
        self.assertEqual(first["night"]["from"], "2130")
        again = migrate_config(dict(first))
        self.assertEqual(again["schema"], 6)
        self.assertEqual(again["night"]["mode"], "sun")
        self.assertEqual(again["night"]["zip"], "")
        when = datetime(2026, 1, 15, 22, 30, tzinfo=timezone(timedelta(hours=-5)))
        status = compute_night_status({"night": again["night"]}, when)
        self.assertTrue(status["usingScheduleFallback"])
        self.assertTrue(status["night"])


if __name__ == "__main__":
    unittest.main()
