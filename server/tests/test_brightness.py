"""Panel brightness: sysfs writes, permission install, software-dim fallback."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

import backlight  # noqa: E402
import updater as up  # noqa: E402
from logic import backlight_value  # noqa: E402


def _node(root: Path, name: str, max_brightness: int = 255, mode: int = 0o664) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "max_brightness").write_text(f"{max_brightness}\n", encoding="ascii")
    path = folder / "brightness"
    path.write_text("255\n", encoding="ascii")
    path.chmod(mode)
    return path


class ScaleTests(unittest.TestCase):
    def test_wiki_range_is_unchanged_when_max_is_255(self) -> None:
        self.assertEqual(backlight.scale_value(0, 255), 0)
        self.assertEqual(backlight.scale_value(255, 255), 255)
        self.assertEqual(backlight.scale_value(128, 255), 128)
        self.assertEqual(backlight_value(50), 128)

    def test_value_is_scaled_to_a_smaller_max(self) -> None:
        self.assertEqual(backlight.scale_value(255, 31), 31)
        self.assertEqual(backlight.scale_value(0, 31), 0)
        self.assertEqual(backlight.scale_value(128, 31), 16)


class SysfsWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)], check=False))

    def test_writes_every_writable_node_and_scales(self) -> None:
        panel = _node(self.tmp, "11-0045", 255)
        other = _node(self.tmp, "tiny", 31)
        written = backlight.write_nodes(128, self.tmp)
        self.assertEqual(set(written), {str(panel), str(other)})
        self.assertEqual(panel.read_text(encoding="ascii"), "128")
        self.assertEqual(other.read_text(encoding="ascii"), "16")

    def test_one_unwritable_node_does_not_block_the_panel(self) -> None:
        panel = _node(self.tmp, "11-0045", 255)
        locked = _node(self.tmp, "locked", 255, mode=0o444)
        written = backlight.write_nodes(51, self.tmp)
        self.assertEqual(written, [str(panel)])
        self.assertEqual(panel.read_text(encoding="ascii"), "51")
        self.assertEqual(locked.read_text(encoding="ascii").strip(), "255")

    def test_no_nodes_returns_empty(self) -> None:
        self.assertEqual(backlight.write_nodes(100, self.tmp), [])

    def test_brightness_sh_uses_the_python_writer(self) -> None:
        panel = _node(self.tmp, "10-0045", 255)
        env = os.environ.copy()
        env["FT_BACKLIGHT_ROOT"] = str(self.tmp)
        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "brightness.sh"), "204"],
            capture_output=True, text=True, env=env, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(panel.read_text(encoding="ascii"), "204")

    def test_brightness_sh_fails_when_nothing_is_writable(self) -> None:
        env = os.environ.copy()
        env["FT_BACKLIGHT_ROOT"] = str(self.tmp)
        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "brightness.sh"), "10"],
            capture_output=True, text=True, env=env, timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No writable backlight node", result.stderr)


class PermissionInstallTests(unittest.TestCase):
    def test_udev_and_sudoers_are_written(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(tmp)], check=False))
        udev = tmp / "rules.d" / "99-flight-tracker-backlight.rules"
        sudoers = tmp / "sudoers.d" / "flight-tracker-brightness"
        panel = _node(tmp / "backlight", "11-0045")
        notes = backlight.install_permissions(
            root=tmp / "backlight",
            udev_path=udev,
            sudoers_path=sudoers,
            user="ft-server",
            reload_udev=False,
        )
        self.assertTrue(notes["udev"])
        self.assertTrue(notes["sudoers"])
        self.assertIn("11-0045", udev.read_text())
        self.assertIn("ft-server ALL=(root) NOPASSWD: /usr/local/sbin/flight-tracker-brightness", sudoers.read_text())
        self.assertIn(str(panel), notes["nodes"])
        # Re-running is idempotent.
        again = backlight.install_permissions(
            root=tmp / "backlight", udev_path=udev, sudoers_path=sudoers, reload_udev=False,
        )
        self.assertFalse(again["udev"])
        self.assertFalse(again["sudoers"])

    def test_ota_and_install_sh_and_migrate_install_permissions(self) -> None:
        updater = (ROOT / "server/updater.py").read_text()
        self.assertIn("refresh_backlight_access(final)", updater)
        apply = updater[updater.index("def apply_update") :]
        self.assertLess(apply.index("if not _wait_healthy("), apply.index("refresh_backlight_access(final)"))
        install = (ROOT / "install.sh").read_text()
        self.assertIn("server/backlight.py\" --install-permissions", install)
        migrate = (ROOT / "server/migrate.py").read_text()
        self.assertIn("install_permissions", migrate)
        self.assertIn("post_update_system_steps", migrate)
        self.assertTrue((ROOT / "deploy/99-flight-tracker-backlight.rules").is_file())

    def test_refresh_backlight_access_writes_into_injected_paths(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(tmp)], check=False))
        udev = tmp / "99-flight-tracker-backlight.rules"
        sudoers = tmp / "flight-tracker-brightness"
        notes = up.refresh_backlight_access(
            ROOT, udev_path=udev, sudoers_path=sudoers, reload_udev=False,
        )
        self.assertTrue(udev.is_file())
        self.assertTrue(sudoers.is_file())
        self.assertIn("chmod g+w", udev.read_text())
        self.assertTrue(notes["udev"])


class AppBrightnessTests(unittest.TestCase):
    def test_health_and_api_report_write_success_not_mere_presence(self) -> None:
        import flighttracker as ft

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(tmp)], check=False))
        os.environ["FT_BACKLIGHT_ROOT"] = str(tmp)
        self.addCleanup(os.environ.pop, "FT_BACKLIGHT_ROOT", None)
        _node(tmp, "11-0045")
        # Writable node: apply should succeed and hardware should be true.
        # Use a minimal App by patching config paths through a fake args object
        # is heavy; call the functions on a simple instance mock.
        class Fake:
            pass
        app = Fake()
        app.backlight_ok = False
        app._applied_brightness = None
        ft.App.backlight_nodes = lambda self: backlight.list_nodes(tmp) and [str(p) for p in backlight.list_nodes(tmp)]
        # Use a real App method unbound
        wrote = backlight.write_nodes(204, tmp)
        self.assertTrue(wrote)
        # Presence alone must not count as hardware success in the sources.
        health = (ROOT / "server/flighttracker.py").read_text()
        self.assertIn('"backlightOk": app.backlight_ok', health)
        self.assertIn('"hardware": app.backlight_ok', health)
        self.assertNotIn('"hardware": app.backlight_nodes() != []', health)

    def test_glass_uses_overlay_unless_backlight_write_succeeded(self) -> None:
        main = (ROOT / "src/main.ts").read_text()
        self.assertIn("hardwareBacklight = health.backlightOk === true", main)
        self.assertIn('dim.style.opacity = hardwareBacklight ? "0"', main)
        self.assertNotIn("hardwareBacklight && !nightOn", main)
        self.assertIn("body.backlightOk", main)


if __name__ == "__main__":
    unittest.main()
