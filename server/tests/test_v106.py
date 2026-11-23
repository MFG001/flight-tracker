"""1.0.6: no stale "Update ready" for an older release, and push-update.sh
lets sudo ask for the Pi password."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

try:
    from server.tests.test_v103 import SetupServer  # noqa: E402
except ImportError:  # discovered with -s server/tests
    from test_v103 import SetupServer  # type: ignore  # noqa: E402

SETUP = (ROOT / "setup/index.html").read_text(encoding="utf-8")
PUSH = (ROOT / "deploy/push-update.sh").read_text(encoding="utf-8")


class VersionTests(unittest.TestCase):
    def test_version_is_106(self) -> None:
        # 1.0.7 moved on; test_v107 pins the exact number.
        version = (ROOT / "VERSION").read_text().strip()
        self.assertGreaterEqual(tuple(int(x) for x in version.split(".")), (1, 0, 6))
        self.assertEqual(json.loads((ROOT / "package.json").read_text())["version"], version)
        lock = json.loads((ROOT / "package-lock.json").read_text())
        self.assertEqual((lock["version"], lock["packages"][""]["version"]), (version, version))
        self.assertIn(f"FlightTracker/{version} ", (ROOT / "server/flighttracker.py").read_text())


class StaleStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.srv = SetupServer(self)
        self.app = self.srv.app
        self.ft = self.srv.ft
        import updater as live
        self.live = live
        running = mock.patch.object(self.ft, "running_version", return_value="1.0.5")
        running.start()
        self.addCleanup(running.stop)

    def status(self, **body) -> None:
        self.live.write_status(self.app.config_path, body)

    def test_old_available_status_reads_up_to_date(self) -> None:
        # A field unit had a 1.0.2 check that found 1.0.3.
        self.status(state="available", available=True, version="1.0.3", current="1.0.2", notes="Old 1.0.3 notes")
        view = self.app.update_view()
        self.assertEqual(view["version"], "1.0.5")
        self.assertFalse(view["available"])
        self.assertEqual(view["state"], "current")
        self.assertEqual(view["notes"], "")
        self.assertEqual(view["target"], "")
        self.assertEqual(self.srv.get("/api/updates")["state"], "current")

    def test_equal_version_is_not_an_update(self) -> None:
        self.status(state="available", available=True, version="1.0.5", notes="n")
        view = self.app.update_view()
        self.assertFalse(view["available"])
        self.assertEqual(view["state"], "current")

    def test_newer_status_still_shows_available(self) -> None:
        self.status(state="available", available=True, version="1.0.7", notes="New things")
        view = self.app.update_view()
        self.assertTrue(view["available"])
        self.assertEqual((view["state"], view["latest"], view["notes"]), ("available", "1.0.7", "New things"))

    def test_startup_rewrites_stale_status(self) -> None:
        self.status(state="available", available=True, version="1.0.3", notes="Old")
        self.ft.App(self.srv.args)  # a restart
        stored = self.live.read_status(self.app.config_path)
        self.assertEqual(stored["state"], "current")
        self.assertFalse(stored["available"])
        self.assertEqual(stored["version"], "1.0.5")
        self.assertEqual(stored["notes"], "")

    def test_startup_keeps_a_newer_or_live_status(self) -> None:
        self.status(state="available", available=True, version="1.0.7", notes="New")
        self.ft.App(self.srv.args)
        self.assertEqual(self.live.read_status(self.app.config_path)["state"], "available")
        # Mid-install restart: the new server already runs the target version.
        self.status(state="installing", stage="restarting", step=4, steps=4, target="1.0.5", version="1.0.5", available=True)
        self.ft.App(self.srv.args)
        self.assertEqual(self.live.read_status(self.app.config_path)["state"], "installing")
        self.assertEqual(self.app.update_view()["state"], "installing")

    def test_installed_older_release_reads_current(self) -> None:
        self.status(state="installed", stage="complete", version="1.0.4", current="1.0.4", available=False)
        self.assertEqual(self.app.update_view()["state"], "current")
        self.status(state="installed", stage="complete", version="1.0.5", current="1.0.5", available=False)
        self.assertEqual(self.app.update_view()["state"], "installed")

    def fake_wrapper(self) -> None:
        import tempfile
        path = Path(tempfile.mkdtemp()) / "flight-tracker-update"
        path.write_text("#!/bin/bash\n")
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(path.parent)]))
        patch = mock.patch.object(self.ft.App, "UPDATE_WRAPPER", path)
        patch.start()
        self.addCleanup(patch.stop)

    def test_install_refuses_when_nothing_newer(self) -> None:
        self.fake_wrapper()
        for body in (
            dict(state="available", available=True, version="1.0.3"),
            dict(state="available", available=True, version="1.0.5"),
            dict(state="current", available=False, version="1.0.5"),
            {},
        ):
            self.live._status_path(self.app.config_path).unlink(missing_ok=True)
            if body:
                self.status(**body)
            with mock.patch.object(self.ft.subprocess, "run") as run:
                ok, detail = self.app.install_update()
            self.assertFalse(ok, body)
            self.assertIn("Nothing newer to install", detail)
            run.assert_not_called()

    def test_install_allowed_for_newer(self) -> None:
        self.fake_wrapper()
        self.status(state="available", available=True, version="1.0.7")
        with mock.patch.object(self.ft.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")):
            ok, _ = self.app.install_update()
        self.assertTrue(ok)


class SetupPageGuardTests(unittest.TestCase):
    def test_ready_box_needs_newer_version(self) -> None:
        self.assertIn("function swNewer(latest, running)", SETUP)
        self.assertIn("const canInstall = !!info.available && swNewer(info.latest, running);", SETUP)
        self.assertIn("} else if (canInstall) {", SETUP)
        self.assertNotIn("} else if (info.available) {", SETUP)
        self.assertNotRegex(SETUP, r"swButtons\(false, !!(?:info|swInfo)\.available\);")

    def test_swNewer_logic(self) -> None:
        body = SETUP[SETUP.index("function swNewer"):]
        body = body[:body.index("\n      }\n") + 8]
        code = body + "\nconsole.log(JSON.stringify([swNewer('1.0.3','1.0.5'), swNewer('1.0.5','1.0.5'), swNewer('1.0.7','1.0.5'), swNewer('1.1','1.0.9'), swNewer('','1.0.5'), swNewer('x','1.0.5')]));"
        out = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), [False, False, True, True, False, False])


class PushUpdateTtyTests(unittest.TestCase):
    def test_sudo_step_has_a_terminal(self) -> None:
        lines = [l.strip() for l in PUSH.splitlines() if not l.strip().startswith("#")]
        tty_lines = [l for l in lines if re.search(r"\bssh\b.*\s-t\s", l)]
        self.assertEqual(len(tty_lines), 1, tty_lines)
        step = tty_lines[0]
        self.assertNotIn("<<", step)
        self.assertNotIn("<", step.replace("<<", ""))
        self.assertNotIn("bash -s", step)
        self.assertNotIn("|", step)
        self.assertIn("remote-install.sh", step)
        # No heredoc is fed to any ssh command; the only heredoc writes the local script file.
        self.assertNotRegex(PUSH, r"ssh[^\n]*<<")
        self.assertIn('cat > "$local_script" <<\'REMOTE\'', PUSH)
        self.assertIn('scp "${ssh_opts[@]}" -q "$local_script" "$target:$remote_dir/remote-install.sh"', PUSH)

    def test_keeps_single_connection_cleanup_and_health(self) -> None:
        self.assertIn("ControlMaster=auto", PUSH)
        self.assertIn("trap cleanup_local EXIT", PUSH)
        self.assertIn('trap \'rm -rf "$dir"\' EXIT', PUSH)
        self.assertIn("for url in http://127.0.0.1:8741/api/health http://127.0.0.1/api/health; do", PUSH)
        self.assertIn("Run this on the Mac", PUSH)
        software = (ROOT / "docs/SOFTWARE.md").read_text(encoding="utf-8")
        self.assertIn("Run these on the Mac (in Terminal), not on the Pi.", software)


if __name__ == "__main__":
    unittest.main()
