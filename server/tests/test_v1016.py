"""1.0.16: Wi-Fi setup address, on-device keyboard, and kiosk boot retry."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from server.logic import CONFIG_SCHEMA, DEFAULT_CONFIG  # noqa: E402


class VersionPinTests(unittest.TestCase):
    def test_version_is_1016_everywhere(self) -> None:
        self.assertEqual((ROOT / "VERSION").read_text().strip(), "1.0.16")
        self.assertEqual(json.loads((ROOT / "package.json").read_text())["version"], "1.0.16")
        lock = json.loads((ROOT / "package-lock.json").read_text())
        self.assertEqual((lock["version"], lock["packages"][""]["version"]), ("1.0.16", "1.0.16"))
        self.assertIn("FlightTracker/1.0.16 ", (ROOT / "server/flighttracker.py").read_text())
        self.assertEqual(CONFIG_SCHEMA, 4)
        self.assertEqual(DEFAULT_CONFIG["schema"], 4)


class FeaturePresenceTests(unittest.TestCase):
    def test_wifi_setup_uses_reachable_address_and_starts_hotspot(self) -> None:
        wifi = (ROOT / "server/wifi_net.py").read_text()
        main = (ROOT / "src/main.ts").read_text()
        self.assertIn("def start_setup_hotspot", wifi)
        self.assertIn("def apply_service_urls", wifi)
        self.assertIn('/api/wifi/hotspot', main)
        self.assertIn("Join this Wi-Fi, then scan.", main)
        self.assertTrue((ROOT / "deploy/dnsmasq-shared-flighttracker.conf").is_file())

    def test_device_wifi_keyboard_is_fitted_to_the_circle(self) -> None:
        html = (ROOT / "setup/index.html").read_text(encoding="utf-8")
        self.assertIn('id="ft-osk"', html)
        self.assertIn("function bindWifiOsk()", html)

    def test_kiosk_boot_retries_and_units_keep_running(self) -> None:
        main = (ROOT / "src/main.ts").read_text()
        kiosk = (ROOT / "scripts/kiosk.sh").read_text()
        unit = (ROOT / "deploy/flight-tracker.service").read_text()
        kunit = (ROOT / "deploy/flight-tracker-kiosk.service").read_text()
        self.assertIn("async function loadDisplay()", main)
        self.assertIn("function fetchOk(", main)
        self.assertIn("/api/health", kiosk)
        self.assertIn("Restart=always", unit)
        self.assertIn("StartLimitIntervalSec=0", unit)
        self.assertIn("Restart=always", kunit)


if __name__ == "__main__":
    unittest.main()
