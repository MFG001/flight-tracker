"""1.0.18: boot glass and setup hotspot recover without a saved network."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from server.logic import CONFIG_SCHEMA, DEFAULT_CONFIG  # noqa: E402
import updater as up  # noqa: E402


class VersionPinTests(unittest.TestCase):
    def test_version_is_at_least_1018(self) -> None:
        # 1.0.20 moved on; test_v1020 pins the exact number.
        version = (ROOT / "VERSION").read_text().strip()
        self.assertGreaterEqual(tuple(int(x) for x in version.split(".")), (1, 0, 18))
        self.assertEqual(CONFIG_SCHEMA, 6)
        self.assertEqual(DEFAULT_CONFIG["schema"], 6)


class FeaturePresenceTests(unittest.TestCase):
    def test_kiosk_opens_when_health_is_late(self) -> None:
        kiosk = (ROOT / "scripts/kiosk.sh").read_text()
        self.assertIn("opening the glass anyway", kiosk)
        self.assertIn("/api/health", kiosk)

    def test_wifi_service_does_not_wait_for_the_display_server(self) -> None:
        unit = (ROOT / "deploy/flight-tracker-wifi.service").read_text()
        after = next(line for line in unit.splitlines() if line.startswith("After="))
        self.assertIn("NetworkManager.service", after)
        self.assertNotIn("flight-tracker.service", after)

    def test_ota_installs_display_units_after_a_healthy_apply(self) -> None:
        text = (ROOT / "server/updater.py").read_text()
        apply = text[text.index("def apply_update") :]
        # Units are installed only after the new release has already passed
        # the health window, so a substitution mistake cannot roll back a
        # running server mid-apply.
        health = apply.index("if not _wait_healthy(")
        refresh = apply.index("refresh_display_units(final)")
        kiosk = apply.index("kiosk_restart()")
        self.assertLess(health, refresh)
        self.assertLess(refresh, kiosk)
        body = text[text.index("def refresh_display_units"):text.index("def refresh_systemd_units")]
        self.assertIn("daemon-reload", body)
        self.assertNotIn("restart", body.lower())
        # Do not add display units to SYSTEMD_UNITS (that list is restarted).
        self.assertNotIn("flight-tracker.service", up.SYSTEMD_UNITS)
        self.assertNotIn("flight-tracker-kiosk.service", up.SYSTEMD_UNITS)
        self.assertIn("flight-tracker.service", up.DISPLAY_UNITS)

    def test_setup_can_forget_saved_networks(self) -> None:
        html = (ROOT / "setup/index.html").read_text(encoding="utf-8")
        self.assertIn('id="wifi-forget"', html)
        self.assertIn("/api/wifi/forget", html)


if __name__ == "__main__":
    unittest.main()
