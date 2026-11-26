"""1.0.17: on-device Wi-Fi keyboard keeps CONNECT visible and submits OSK values."""
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
    def test_version_is_at_least_1017(self) -> None:
        # 1.0.20 moved on; test_v1020 pins the exact number.
        version = (ROOT / "VERSION").read_text().strip()
        self.assertGreaterEqual(tuple(int(x) for x in version.split(".")), (1, 0, 17))
        self.assertEqual(CONFIG_SCHEMA, 6)
        self.assertEqual(DEFAULT_CONFIG["schema"], 6)


class FeaturePresenceTests(unittest.TestCase):
    def test_device_wifi_connect_stays_clear_of_the_keyboard(self) -> None:
        html = (ROOT / "setup" / "index.html").read_text(encoding="utf-8")
        bind = html[html.index("function bindWifiOsk()") :]
        self.assertIn("function pinJoinButton(", bind)
        self.assertIn('"connect"', bind)
        self.assertIn('$("wifi-join")?.click()', bind)
        checker = (ROOT / "scripts" / "check-wifi-osk.mjs").read_text(encoding="utf-8")
        self.assertIn("CONNECT is covered by the keyboard", checker)
        self.assertIn("connect key did not submit the OSK values", checker)


if __name__ == "__main__":
    unittest.main()
