"""1.0.19: saved Wi-Fi networks, backlight writes, and Maverick-only icons."""
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
    def test_version_is_1019_everywhere(self) -> None:
        self.assertEqual((ROOT / "VERSION").read_text().strip(), "1.0.19")
        self.assertEqual(json.loads((ROOT / "package.json").read_text())["version"], "1.0.19")
        lock = json.loads((ROOT / "package-lock.json").read_text())
        self.assertEqual((lock["version"], lock["packages"][""]["version"]), ("1.0.19", "1.0.19"))
        self.assertIn("FlightTracker/1.0.19 ", (ROOT / "server/flighttracker.py").read_text())
        self.assertEqual(CONFIG_SCHEMA, 5)
        self.assertEqual(DEFAULT_CONFIG["schema"], 5)
        self.assertEqual(DEFAULT_CONFIG["icons"], "maverick")


class FeaturePresenceTests(unittest.TestCase):
    def test_setup_lists_saved_networks_and_can_change_a_password(self) -> None:
        html = (ROOT / "setup/index.html").read_text(encoding="utf-8")
        self.assertIn('id="saved-nets"', html)
        self.assertIn("/api/wifi/saved", html)
        self.assertIn("/api/wifi/prefer", html)
        self.assertIn("/api/wifi/password", html)
        self.assertIn("CHANGE PASSWORD", html)
        self.assertIn('id="wifi-saved-pass"', html)
        self.assertIn('id="wifi-forget"', html)
        wifi = (ROOT / "scripts/wifi-ctl.sh").read_text()
        self.assertIn("set_client_password", wifi)
        self.assertIn("prefer_one_client", wifi)
        self.assertIn("forget_one_client", wifi)
        # Joining a network must not disable other saved clients. autoconnect
        # no is only used for the setup hotspot profile.
        prefer = wifi[wifi.index("set_preferred_uuids()") : wifi.index("promote_client_network(")]
        self.assertIn("connection.autoconnect yes", prefer)
        self.assertNotIn("autoconnect no", prefer)

    def test_ota_installs_backlight_access_after_a_healthy_apply(self) -> None:
        text = (ROOT / "server/updater.py").read_text()
        apply = text[text.index("def apply_update") :]
        health = apply.index("if not _wait_healthy(")
        refresh = apply.index("refresh_backlight_access(final)")
        self.assertLess(health, refresh)
        self.assertTrue((ROOT / "deploy/99-flight-tracker-backlight.rules").is_file())
        self.assertIn("def refresh_backlight_access", text)
        migrate = (ROOT / "server/migrate.py").read_text()
        self.assertIn("install_permissions", migrate)
        ft = (ROOT / "server/flighttracker.py").read_text()
        self.assertIn("backlightOk", ft)
        self.assertIn("apply_effective_brightness", ft)
        main = (ROOT / "src/main.ts").read_text()
        self.assertIn("backlightOk", main)

    def test_maverick_is_the_only_icon_set(self) -> None:
        html = (ROOT / "setup/index.html").read_text(encoding="utf-8")
        self.assertNotIn('id="icons"', html)
        self.assertNotIn("Icon set", html)
        migrate = (ROOT / "server/migrate.py").read_text()
        self.assertIn("if schema < 5:", migrate)
        self.assertIn('cfg["icons"] = "maverick"', migrate)
        types = (ROOT / "src/types.ts").read_text()
        self.assertIn('icons: "maverick"', types)
        icons = (ROOT / "src/icons.ts").read_text()
        self.assertNotIn("export const ICON_SETS", icons)
        self.assertIn('export type IconSetId = "maverick"', icons)


class MigrationIdempotentTests(unittest.TestCase):
    def test_schema_5_is_idempotent_and_keeps_maverick_on_rollback_path(self) -> None:
        from server.migrate import migrate_config

        first = migrate_config({"schema": 4, "icons": "linecut", "rangeNm": 20})
        self.assertEqual(first["schema"], 5)
        self.assertEqual(first["icons"], "maverick")
        again = migrate_config(dict(first))
        self.assertEqual(again["schema"], 5)
        self.assertEqual(again["icons"], "maverick")
        already = migrate_config({"schema": 5, "icons": "maverick", "rangeNm": 20})
        self.assertEqual(already["schema"], 5)
        self.assertEqual(already["icons"], "maverick")


if __name__ == "__main__":
    unittest.main()
