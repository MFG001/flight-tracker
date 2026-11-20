"""1.0.5+: updates come from MFG001/flight-tracker-updates; saved settings survive upgrades."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from server.logic import sanitize_config  # noqa: E402
from server.migrate import migrate_config  # noqa: E402
from server.update_repo import PRIVATE_URL, UPDATE_REPO, UPDATE_URL  # noqa: E402

NEW = "https://github.com/MFG001/flight-tracker/releases/latest/download/manifest.json"
HOME = {"home": {"name": "KJFK", "lat": 40.6399, "lon": -73.7787}, "rangeNm": 20}


class VersionTests(unittest.TestCase):
    def test_version_is_105_or_later(self) -> None:
        # 1.0.6 moved on; test_v106 pins the exact number. Everything still agrees.
        version = (ROOT / "VERSION").read_text().strip()
        self.assertGreaterEqual(tuple(int(x) for x in version.split(".")), (1, 0, 5))
        self.assertEqual(json.loads((ROOT / "package.json").read_text())["version"], version)
        lock = json.loads((ROOT / "package-lock.json").read_text())
        self.assertEqual((lock["version"], lock["packages"][""]["version"]), (version, version))
        self.assertIn(f"FlightTracker/{version} ", (ROOT / "server/flighttracker.py").read_text())


class RepoTests(unittest.TestCase):
    def test_constants(self) -> None:
        self.assertEqual(UPDATE_REPO, "MFG001/flight-tracker")
        self.assertEqual(UPDATE_URL, NEW)

    def test_private_repo_url_moves_to_public_repo(self) -> None:
        cfg, errors = sanitize_config(dict(HOME, updates={"url": PRIVATE_URL, "auto": True}))
        self.assertEqual(errors, [])
        self.assertEqual({k: cfg["updates"][k] for k in ("url", "repo", "auto")}, {"url": NEW, "repo": UPDATE_REPO, "auto": True})
        migrated = migrate_config({"schema": 3, "updates": {"url": PRIVATE_URL, "auto": False}})
        self.assertEqual((migrated["updates"]["url"], migrated["updates"]["repo"]), (NEW, UPDATE_REPO))

    def test_update_url_is_kept_as_saved(self) -> None:
        custom = "https://updates.example.com/manifest.json"
        self.assertEqual(sanitize_config(dict(HOME, updates={"url": custom}))[0]["updates"]["url"], custom)
        self.assertEqual(sanitize_config(HOME)[0]["updates"]["url"], NEW)
        self.assertEqual(migrate_config({"schema": 3, "updates": {"url": custom}})["updates"]["url"], custom)

    def test_old_owner_rule_is_gone(self) -> None:
        import server.update_repo as repo
        self.assertFalse(hasattr(repo, "migrate_update_url"))
        for name in ("server/logic.py", "server/migrate.py", "server/updater.py"):
            self.assertNotIn("migrate_update_url", (ROOT / name).read_text(), name)

    def test_defaults_everywhere(self) -> None:
        example = json.loads((ROOT / "data/config.example.json").read_text())
        self.assertEqual(example["updates"]["url"], NEW)
        self.assertIn(NEW, (ROOT / "src/main.ts").read_text())
        self.assertIn('PUBLIC_REPO = "MFG001/flight-tracker"', (ROOT / "tools/sign_release").read_text())
        self.assertEqual(example["updates"]["repo"], UPDATE_REPO)
        built = "".join(p.read_text(errors="ignore") for p in (ROOT / "dist").rglob("*.js"))
        self.assertIn(NEW, built)


class ConfigFileMigrationTests(unittest.TestCase):
    """A Pi's config.json rewrites itself on start, with no edit by hand."""

    def write(self, url: str) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(tmp)]))
        example = json.loads((ROOT / "data/config.example.json").read_text())
        example["updates"] = {"url": url, "auto": True}
        self.path = tmp / "config.json"
        self.path.write_text(json.dumps(example, indent=2))

    def load(self, url: str):
        self.write(url)
        import argparse
        from unittest import mock
        import server.flighttracker as ft
        args = argparse.Namespace(dist=str(ROOT / "dist"), config=str(self.path), cache=str(self.path.parent / "cache"),
                                  sample=str(ROOT / "data/sample-aircraft.json"), demo=True)
        with mock.patch.object(ft.App, "apply_brightness", return_value=False):
            app = ft.App(args)
        return app, json.loads(self.path.read_text())

    def test_custom_url_is_left_alone(self) -> None:
        custom = "https://updates.example.com/flight-tracker/manifest.json"
        app, on_disk = self.load(custom)
        self.assertEqual(on_disk["updates"]["url"], custom)
        self.assertEqual(app.snapshot()["updates"]["url"], custom)

    def test_saved_location_survives_upgrade(self) -> None:
        """New installs default to KJFK; an existing unit keeps its own home and METAR station."""
        saved = {"name": "KSEA", "lat": 47.4499, "lon": -122.3118}
        self.write("https://updates.example.com/flight-tracker/manifest.json")
        cfg = json.loads(self.path.read_text())
        cfg["home"], cfg["metarStation"], cfg["schema"] = dict(saved), "KBFI", 1
        self.path.write_text(json.dumps(cfg))
        subprocess.run([sys.executable, str(ROOT / "server/migrate.py"), "--config", str(self.path), "--no-system"], check=True, timeout=30)
        on_disk = json.loads(self.path.read_text())
        self.assertEqual((on_disk["home"], on_disk["metarStation"]), (saved, "KBFI"))
        app, again = self.load_existing()
        self.assertEqual(app.snapshot()["home"], saved)
        self.assertEqual((again["home"], again["metarStation"]), (saved, "KBFI"))
        self.assertEqual(json.loads((ROOT / "data/config.example.json").read_text())["home"]["name"], "KJFK")

    def load_existing(self):
        import argparse
        from unittest import mock
        import server.flighttracker as ft
        args = argparse.Namespace(dist=str(ROOT / "dist"), config=str(self.path), cache=str(self.path.parent / "cache"),
                                  sample=str(ROOT / "data/sample-aircraft.json"), demo=True)
        with mock.patch.object(ft.App, "apply_brightness", return_value=False):
            app = ft.App(args)
        return app, json.loads(self.path.read_text())


if __name__ == "__main__":
    unittest.main()
