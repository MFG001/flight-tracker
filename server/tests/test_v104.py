"""1.0.4: the OTA install really starts (no recursive systemd-run), every
/api/updates* answer keeps the saved key and version, live install progress,
kiosk reload after a good install, and a clear Software card."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

import server.updater as up  # noqa: E402

try:
    from server.tests.test_v103 import SetupServer  # noqa: E402
    from server.tests.test_updater import GOOD_MIGRATE, GOOD_SERVE, BAD_MIGRATE, BAD_SERVE, Store, UpdateFlowTest  # noqa: E402
except ImportError:  # discovered with -s server/tests
    from test_v103 import SetupServer  # type: ignore  # noqa: E402
    from test_updater import GOOD_MIGRATE, GOOD_SERVE, BAD_MIGRATE, BAD_SERVE, Store, UpdateFlowTest  # type: ignore  # noqa: E402

WRAPPER = ROOT / "deploy" / "flight-tracker-update"
SETUP = (ROOT / "setup/index.html").read_text(encoding="utf-8")


def _exe(folder: Path, name: str, body: str) -> None:
    path = folder / name
    path.write_text("#!/bin/bash\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class VersionTests(unittest.TestCase):
    def test_version_is_104_or_later(self) -> None:
        # 1.0.5 moved on; test_v105 pins the exact number. Everything still agrees.
        version = (ROOT / "VERSION").read_text().strip()
        self.assertGreaterEqual(tuple(int(x) for x in version.split(".")), (1, 0, 4))
        self.assertEqual(json.loads((ROOT / "package.json").read_text())["version"], version)
        lock = json.loads((ROOT / "package-lock.json").read_text())
        self.assertEqual(lock["version"], version)
        self.assertEqual(lock["packages"][""]["version"], version)


class WrapperTests(unittest.TestCase):
    """deploy/flight-tracker-update must queue updater.py once and return."""

    def test_no_recursive_systemd_run(self) -> None:
        text = WRAPPER.read_text(encoding="utf-8")
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        self.assertNotIn("FLIGHT_TRACKER_UPDATE_DETACHED", code)
        self.assertNotIn("--wait", code)
        self.assertNotIn("/usr/local/sbin/flight-tracker-update --install", code)
        self.assertIn("--no-block", code)
        self.assertIn('"$PYTHON" "$UPDATER" "$cmd"', code)
        self.assertIn("UPDATER=/opt/flight-tracker/current/server/updater.py", code)
        self.assertIn("systemctl reset-failed \"$UNIT\" 2>/dev/null || true", code)

    def run_wrapper(self, state: str, *args: str) -> tuple[subprocess.CompletedProcess[str], str]:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(tmp)]))
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        runtime = tmp / "systemd"
        runtime.mkdir()
        log = tmp / "calls.log"
        _exe(bin_dir, "systemctl", f'echo "systemctl $*" >> "{log}"\nif [[ "$1" == show ]]; then echo "{state}"; fi\nexit 0\n')
        _exe(bin_dir, "systemd-run", f'echo "systemd-run $*" >> "{log}"\nexit 0\n')
        env = dict(os.environ, PATH=f"{bin_dir}:/usr/bin:/bin", FT_SYSTEMD_RUNTIME=str(runtime))
        result = subprocess.run(["bash", str(WRAPPER), *args], capture_output=True, text=True, env=env, timeout=10)
        return result, log.read_text() if log.exists() else ""

    def test_install_queues_updater_once_and_returns(self) -> None:
        result, calls = self.run_wrapper("inactive", "--install")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("systemctl reset-failed flight-tracker-apply.service", calls)
        run = [line for line in calls.splitlines() if line.startswith("systemd-run")]
        self.assertEqual(len(run), 1)
        self.assertIn("--no-block", run[0])
        self.assertIn("--collect", run[0])
        self.assertIn("--unit=flight-tracker-apply.service", run[0])
        self.assertTrue(run[0].endswith("/usr/bin/python3 /opt/flight-tracker/current/server/updater.py --install"))
        self.assertNotIn("flight-tracker-update", run[0])

    def test_install_refused_while_one_runs(self) -> None:
        for state in ("active", "activating"):
            result, calls = self.run_wrapper(state, "--install")
            self.assertEqual(result.returncode, 3)
            self.assertIn("already installing", result.stderr)
            self.assertNotIn("systemd-run", calls)

    def test_bad_argument(self) -> None:
        result, _ = self.run_wrapper("inactive", "--bogus")
        self.assertEqual(result.returncode, 2)


class ServerUpdateViewTests(unittest.TestCase):
    """Every /api/updates* answer has the full view (saved key, version, settings)."""

    def setUp(self) -> None:
        self.srv = SetupServer(self)
        self.app = self.srv.app
        import updater as live  # the module flighttracker.py imports
        self.live = live
        self.ft = self.srv.ft

    def assert_full(self, view: dict) -> None:
        # 1.0.7: tokenless; the source and pinned key fingerprint replace the saved-key line.
        for key in ("source", "repo", "keyFingerprints", "version", "auto", "url", "state", "stage", "step", "steps", "target", "detail"):
            self.assertIn(key, view)
        self.assertNotIn("tokenSet", view)
        self.assertEqual(view["source"], "github.com/MFG001/flight-tracker")
        self.assertEqual(view["version"], self.ft.running_version())

    def test_check_keeps_saved_key_on_success_and_error(self) -> None:
        found = {"current": "1.0.3", "version": "1.0.9", "notes": "n", "available": True, "sha256": "x", "url": "https://e/x", "downloadUrl": "https://e/x"}
        with mock.patch.object(self.live, "load_keyring", return_value={}), \
             mock.patch.object(self.live, "check_for_update", return_value=found):
            view = self.app.check_updates()
        self.assert_full(view)
        self.assertEqual(view["state"], "available")
        self.assertEqual(view["latest"], "1.0.9")
        with mock.patch.object(self.live, "load_keyring", side_effect=self.live.UpdateError("offline")):
            view = self.app.check_updates()
        self.assert_full(view)
        self.assertEqual(view["state"], "error")
        self.assertEqual(view["error"], "offline")

    def test_http_endpoints_all_return_the_full_view(self) -> None:
        with mock.patch.object(self.live, "load_keyring", side_effect=self.live.UpdateError("offline")):
            self.assert_full(self.srv.post("/api/updates/check", {}))
        self.assert_full(self.srv.post("/api/updates/auto", {"auto": True}))
        self.assert_full(self.srv.get("/api/updates"))
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as gone:  # 1.0.7: nothing to save any more
            self.srv.post("/api/updates/token", {"token": "anything"})
        self.assertEqual(gone.exception.code, 400)
        with mock.patch.object(self.ft.App, "install_update", return_value=(True, "Installing.")):
            started = self.srv.post("/api/updates/install", {})
        self.assert_full(started)
        self.assertEqual(started["detail"], "Installing.")

    def fake_wrapper(self) -> Path:
        path = Path(tempfile.mkdtemp()) / "flight-tracker-update"
        path.write_text("#!/bin/bash\n", encoding="utf-8")
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(path.parent)]))
        patch = mock.patch.object(self.ft.App, "UPDATE_WRAPPER", path)
        patch.start()
        self.addCleanup(patch.stop)
        return path

    def test_install_reports_real_launch_failure(self) -> None:
        self.fake_wrapper()
        self.live.write_status(self.app.config_path, {"state": "available", "available": True, "version": "1.0.9", "notes": "n"})
        failed = subprocess.CompletedProcess([], 1, "", "sudo: a password is required\n")
        with mock.patch.object(self.ft.subprocess, "run", return_value=failed) as run:
            ok, detail = self.app.install_update()
        self.assertFalse(ok)
        self.assertEqual(detail, "sudo: a password is required")
        self.assertEqual(run.call_args.args[0][-2:], [str(self.ft.App.UPDATE_WRAPPER), "--install"])
        self.assertEqual(run.call_args.kwargs["timeout"], 15)
        self.assertTrue(run.call_args.kwargs["capture_output"])
        view = self.app.update_view()
        self.assertEqual((view["state"], view["stage"]), ("error", "failed"))
        self.assertEqual(view["error"], "sudo: a password is required")
        self.assertTrue(view["available"])  # INSTALL UPDATE comes back
        self.assertEqual(view["source"], "github.com/MFG001/flight-tracker")

    def test_install_records_installing_before_launch(self) -> None:
        self.fake_wrapper()
        self.live.write_status(self.app.config_path, {"state": "available", "available": True, "version": "1.0.9", "notes": "n"})
        seen: list[dict] = []

        def launch(*_a, **_k):
            seen.append(self.live.read_status(self.app.config_path))
            return subprocess.CompletedProcess([], 0, "", "")

        with mock.patch.object(self.ft.subprocess, "run", side_effect=launch):
            ok, _ = self.app.install_update()
        self.assertTrue(ok)
        self.assertEqual(seen[0]["state"], "installing")
        self.assertEqual(seen[0]["stage"], "starting")
        self.assertEqual(seen[0]["detail"], "Starting update...")
        view = self.app.update_view()
        self.assertEqual(view["state"], "installing")
        self.assertEqual(view["target"], "1.0.9")
        # A second tap while it runs is refused, and so is a check.
        ok2, detail2 = self.app.install_update()
        self.assertFalse(ok2)
        self.assertIn("already installing", detail2)
        self.assertIn("installing", self.app.check_updates()["detail"])

    def test_timeout_is_a_failure(self) -> None:
        self.fake_wrapper()
        # 1.0.6: install needs a checked, newer release first.
        self.live.write_status(self.app.config_path, {"state": "available", "available": True, "version": "1.0.9"})
        with mock.patch.object(self.ft.subprocess, "run", side_effect=subprocess.TimeoutExpired("sudo", 15)):
            ok, detail = self.app.install_update()
        self.assertFalse(ok)
        self.assertIn("15 seconds", detail)

    def test_stalled_install_is_reported(self) -> None:
        self.live.write_status(self.app.config_path, {"state": "installing", "stage": "downloading", "version": "1.0.9"})
        body = json.loads(self.live._status_path(self.app.config_path).read_text())
        body["updatedEpoch"] = time.time() - 3600
        self.live._status_path(self.app.config_path).write_text(json.dumps(body))
        view = self.app.update_view()
        self.assertEqual((view["state"], view["stage"]), ("error", "failed"))
        self.assertIn("stopped without finishing", view["error"])

    def test_no_install_off_the_pi(self) -> None:
        with mock.patch.object(self.ft.App, "UPDATE_WRAPPER", Path("/nonexistent/flight-tracker-update")):
            ok, detail = self.app.install_update()
        self.assertFalse(ok)
        self.assertIn("runs on the Pi", detail)


class ProgressFlowTests(unittest.TestCase):
    """apply_update() writes every milestone and a clean end state."""

    setUpClass = classmethod(UpdateFlowTest.setUpClass.__func__)
    tearDownClass = classmethod(UpdateFlowTest.tearDownClass.__func__)
    setUp = UpdateFlowTest.setUp
    manifest_url = UpdateFlowTest.manifest_url
    publish = UpdateFlowTest.publish
    write_config = UpdateFlowTest.write_config

    def apply(self, timeout: float = 4, **extra) -> dict:
        return up.apply_update(
            root=self.install,
            config_path=self.config_path,
            public_key=self.pub,
            manifest_url=self.manifest_url(),
            ca_file=str(self.base / "tls.crt"),
            health_url=f"http://127.0.0.1:{self.health_port}/api/health",
            health_timeout=timeout,
            restart=self.supervisor.restart,
            **extra,
        )

    def recorded(self):
        log: list[dict] = []
        real = up.write_status

        def capture(path, body):
            log.append(dict(body))
            real(path, body)

        return log, mock.patch.object(up, "write_status", side_effect=capture)

    def test_all_stages_then_complete_wrapper_refresh_and_kiosk_reload(self) -> None:
        self.write_config()
        self.publish("2.0.0", GOOD_SERVE, GOOD_MIGRATE, "Base")
        self.apply()
        # Next release ships its own root helper.
        tree_helper = "#!/bin/bash\necho new-helper\n"
        orig_publish_tree = up.pack_tree

        def pack_with_helper(source: Path, dest: Path) -> None:
            (source / "deploy").mkdir(exist_ok=True)
            (source / "deploy" / "flight-tracker-update").write_text(tree_helper)
            orig_publish_tree(source, dest)

        wrapper = self.install / "sbin-flight-tracker-update"
        wrapper.write_text("#!/bin/bash\necho old-helper\n")
        kiosk = mock.Mock()
        log, patch = self.recorded()
        try:
            from server.tests import test_updater as tu  # noqa: F401
        except ImportError:
            import test_updater as tu  # type: ignore
        with mock.patch.object(tu, "pack_tree", side_effect=pack_with_helper):
            self.publish("2.1.0", GOOD_SERVE, GOOD_MIGRATE, "Progress bar")
        with patch:
            result = self.apply(wrapper=wrapper, kiosk_restart=kiosk)
        stages = [(b.get("state"), b.get("stage"), b.get("step")) for b in log]
        self.assertEqual(stages[0], ("installing", "checking", 1))
        self.assertIn(("installing", "downloading", 2), stages)
        self.assertIn(("installing", "verifying", 3), stages)
        self.assertIn(("installing", "restarting", 4), stages)
        self.assertEqual(stages[-1], ("installed", "complete", None))
        order = [s for _, s, _ in stages]
        self.assertLess(order.index("downloading"), order.index("verifying"))
        self.assertLess(order.index("verifying"), order.index("restarting"))
        download = [b for b in log if b.get("stage") == "downloading"]
        self.assertTrue(download[-1]["detail"].startswith("Downloading Version 2.1.0 ("))
        self.assertTrue(all(b["steps"] == 4 and b["target"] == "2.1.0" for b in log[1:-1]))
        verify = next(b for b in log if b.get("stage") == "verifying")
        self.assertEqual(verify["detail"], "Verifying signature and checksum, unpacking Version 2.1.0...")
        restart = next(b for b in log if b.get("stage") == "restarting")
        self.assertEqual(restart["detail"], "Switching to Version 2.1.0 and restarting Flight Tracker...")
        done = log[-1]
        self.assertEqual(done["current"], "2.1.0")
        self.assertEqual(done["version"], "2.1.0")
        self.assertEqual(done["target"], "")
        self.assertFalse(done["available"])
        self.assertEqual(done["error"], "")
        self.assertRegex(done["installedAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(done["detail"], "Update complete. Now running Version 2.1.0.")
        self.assertEqual(result["state"], "installed")
        kiosk.assert_called_once_with()
        self.assertEqual(wrapper.read_text(), tree_helper)
        self.assertTrue(os.access(wrapper, os.X_OK))

    def test_rollback_status(self) -> None:
        self.write_config()
        self.publish("3.0.0", GOOD_SERVE, GOOD_MIGRATE, "Base")
        self.apply()
        self.publish("3.1.0", BAD_SERVE, BAD_MIGRATE, "Broken")
        kiosk = mock.Mock()
        log, patch = self.recorded()
        with patch, self.assertRaises(up.UpdateError) as caught:
            self.apply(timeout=2, kiosk_restart=kiosk)
        self.assertTrue(getattr(caught.exception, "recorded", False))
        last = log[-1]
        self.assertEqual((last["state"], last["stage"], last["target"]), ("rolled-back", "failed", ""))
        self.assertEqual(last["error"], "Update to Version 3.1.0 failed.")
        self.assertEqual(last["detail"], "Update failed and rolled back to Version 3.0.0.")
        self.assertEqual(last["current"], "3.0.0")
        self.assertTrue(last["available"])
        kiosk.assert_not_called()

    def test_bad_download_fails_without_switching(self) -> None:
        self.write_config()
        self.publish("4.0.0", GOOD_SERVE, GOOD_MIGRATE, "Base")
        self.apply()
        self.publish("4.1.0", GOOD_SERVE, GOOD_MIGRATE, "Corrupt")
        url = "/flight-tracker-4.1.0.tar.gz"
        Store.files[url] = Store.files[url][:-10] + b"0123456789"
        log, patch = self.recorded()
        with patch, self.assertRaises(up.UpdateError):
            self.apply()
        last = log[-1]
        self.assertEqual((last["state"], last["stage"]), ("error", "failed"))
        self.assertIn("sha256", last["error"])
        self.assertEqual(last["detail"], "Update failed. Still running Version 4.0.0.")
        self.assertEqual((self.install / "current").resolve().name, "4.0.0")


class ProgressTextTests(unittest.TestCase):
    def test_download_text(self) -> None:
        mb = up.MB
        self.assertEqual(up.download_text("1.0.4", 18 * mb, 71 * mb), "Downloading Version 1.0.4 (18 / 71 MB)...")
        self.assertEqual(up.download_text("1.0.4", 5 * mb, None), "Downloading Version 1.0.4 (5 MB)...")
        self.assertEqual(up.download_text("1.0.4", 0, None), "Downloading Version 1.0.4...")

    def test_download_progress_is_throttled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stages = up._Stages(Path(tmp) / "config.json", "1.0.3")
            stages.target = "1.0.4"
            with mock.patch.object(up, "write_status") as write:
                stages.downloading(0, 71 * up.MB)
                for n in range(1, 50):
                    stages.downloading(n * 65536, 71 * up.MB)
                stages.downloading(71 * up.MB, 71 * up.MB)
            self.assertLessEqual(write.call_count, 4)
            self.assertEqual(write.call_args.args[1]["detail"], "Downloading Version 1.0.4 (71 / 71 MB)...")

    def test_refresh_wrapper_skips_when_not_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = Path(tmp) / "r"
            (release / "deploy").mkdir(parents=True)
            (release / "deploy" / "flight-tracker-update").write_text("x")
            self.assertFalse(up.refresh_wrapper(release, Path(tmp) / "missing"))

    def test_restart_kiosk_is_harmless_off_the_pi(self) -> None:
        with mock.patch.object(up.shutil, "which", return_value=None):
            self.assertFalse(up.restart_kiosk())


class SoftwareCardTests(unittest.TestCase):
    def card(self) -> str:
        start = SETUP.index('<section id="software"')
        return SETUP[start:SETUP.index("</section>", start)]

    def test_card_structure(self) -> None:
        card = self.card()
        for needle in ('id="sw-version"', 'id="sw-banner"', 'id="sw-progress"', 'id="sw-progress-bar"', 'id="sw-install"', 'id="sw-check"', 'id="sw-source"', 'id="sw-key-badge"'):
            self.assertIn(needle, card)
        self.assertIn('role="status"', card)

    def test_polling_and_reconnect(self) -> None:
        self.assertIn("const SW_POLL_MS = 1500;", SETUP)
        self.assertIn("const SW_POLL_LIMIT_MS = 3 * 60 * 1000;", SETUP)
        self.assertIn('const SW_DONE = new Set(["installed", "current", "rolled-back", "error"]);', SETUP)
        self.assertIn('fetch("/api/updates", { cache: "no-store" })', SETUP)
        self.assertIn("Step 4 of 4 · Restarting Flight Tracker, reconnecting…", SETUP)
        poll = SETUP[SETUP.index("async function pollSoftware"):]
        poll = poll[:poll.index("\n      }\n")]
        self.assertIn("catch (error) {\n          swReconnecting();", poll)
        self.assertIn('if (state === "installing") startSoftwarePoll();', SETUP)

    def test_state_texts(self) -> None:
        for text in (
            '"Currently running "',
            '"Up to date · Version "',
            '"Update ready: Version "',
            '"Installing Version "',
            '"Step " + info.step + " of "',
            '"Update complete · Now running Version "',
            '"The round screen has been reloaded."',
            '"Update failed · Still running Version "',
            '"INSTALLING…"',
            '"✓ Signed updates from "',
        ):
            self.assertIn(text, SETUP)

    def test_view_merges_so_key_line_survives(self) -> None:
        self.assertIn("const info = Object.assign({}, swInfo, update || {});", SETUP)


if __name__ == "__main__":
    unittest.main()


class FailedWordingTests(unittest.TestCase):
    """Plain "update failed" wording, no "healthy" jargon on the card."""

    def test_no_healthy_jargon_in_user_text(self) -> None:
        import re
        for rel in ("setup/index.html", "scripts/sw-states.mjs", "server/flighttracker.py"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotRegex(text.lower(), r"\bhealthy\b", rel)
        updater = (ROOT / "server/updater.py").read_text(encoding="utf-8")
        for literal in re.findall(r'f?"[^"\n]*"', updater):
            self.assertNotIn("healthy", literal.lower(), literal)
        self.assertIn('''raise UpdateError(f"Update to Version {found['version']} failed.")''', updater)

    def test_failed_card_sentence(self) -> None:
        self.assertIn('const reason = /[.!?]$/.test(raw) ? raw : raw + ".";', SETUP)
        self.assertIn('reason + " Rolled back automatically; your settings are kept."', SETUP)
        states = (ROOT / "scripts/sw-states.mjs").read_text(encoding="utf-8")
        self.assertIn('error: "Update to Version 1.0.4 failed."', states)
