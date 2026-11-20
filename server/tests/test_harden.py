"""1.0.7: one-time move of the server to the ft-server account, with undo."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

import harden  # noqa: E402
from update_trust import key_id  # noqa: E402

DESKTOP = "kioskuser"  # stands in for the desktop login, whatever it is called


class FakeSystem:
    def __init__(self, *, healthy=True, useradd_ok=True, visudo_ok=True) -> None:
        self.users = {DESKTOP: (1000, 1000)}
        self.owners: dict[str, tuple[int, int]] = {}
        self.calls: list[list[str]] = []
        self.health_ok = healthy
        self.useradd_ok = useradd_ok
        self.visudo_ok = visudo_ok
        self.health_calls: list[str] = []

    def run(self, args, **kw):
        self.calls.append(list(args))
        code = 0
        if args[0] == "useradd":
            if self.useradd_ok:
                self.users[args[-1]] = (998, 998)
            else:
                code = 1
        if args[0] == "visudo" and not self.visudo_ok:
            code = 1
        return subprocess.CompletedProcess(args, code, "", "")

    def system(self) -> harden.System:
        return harden.System(
            run=self.run,
            user_ids=lambda name: self.users.get(name),
            group_exists=lambda name: name in ("video", "gpio"),
            chown=lambda path, uid, gid: self.owners.__setitem__(str(path), (uid, gid)),
            healthy=self.healthy,
        )

    def healthy(self, url, version, timeout) -> bool:
        self.health_calls.append(version)
        return self.health_ok


class HardenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        t = self.tmp
        self.paths = harden.Paths(
            opt=t / "opt", etc=t / "etc", cache=t / "cache", keys=t / "keys", state=t / "state",
            unit_file=t / "systemd/flight-tracker.service",
            dropin=t / "systemd/flight-tracker.service.d/10-service-account.conf",
            sudoers=t / "sudoers.d/flight-tracker-brightness",
        )
        release = t / "opt/releases/1.0.7"
        release.mkdir(parents=True)
        (release / "VERSION").write_text("1.0.7\n")
        (t / "opt/current").symlink_to(release)
        (release / "server").mkdir()
        (release / "server/app.py").write_text("x")
        (release / "server/app.py").chmod(0o666)
        (t / "etc").mkdir()
        shutil.copy(ROOT / "deploy/update-public.pem", t / "etc/update-public.pem")
        (t / "etc/config.json").write_text("{}")
        (t / "etc/update-token").write_text("old\n")
        (t / "cache").mkdir()
        self.paths.unit_file.parent.mkdir(parents=True)
        self.paths.unit_file.write_text(f"[Service]\nUser={DESKTOP}\nGroup={DESKTOP}\n")
        self.paths.sudoers.parent.mkdir(parents=True)
        self.old_sudoers = harden.sudoers_text(DESKTOP)
        self.paths.sudoers.write_text(self.old_sudoers)

    def test_success_moves_to_service_account(self) -> None:
        fake = FakeSystem()
        result = harden.harden(paths=self.paths, system=fake.system())
        self.assertTrue(result["ok"], result)
        self.assertEqual((result["user"], result["previous"]), ("ft-server", DESKTOP))
        self.assertEqual(harden.unit_user(self.paths), "ft-server")
        self.assertIn("Environment=LG_WD=", self.paths.dropin.read_text())
        self.assertEqual(self.paths.sudoers.read_text(), harden.sudoers_text("ft-server"))
        self.assertNotIn(DESKTOP, self.paths.sudoers.read_text())
        kid = key_id(self.paths.etc / "update-public.pem")
        self.assertTrue((self.paths.keys / f"release-{kid}.pem").is_file())
        self.assertEqual(fake.owners[str(self.paths.opt)], (0, 0))
        self.assertEqual(fake.owners[str(self.paths.etc / "config.json")], (998, 998))
        self.assertEqual(fake.owners[str(self.paths.etc / "update-public.pem")], (0, 0))
        self.assertEqual(fake.owners[str(self.paths.keys)], (0, 0))
        self.assertEqual((self.tmp / "opt/releases/1.0.7/server/app.py").stat().st_mode & 0o777, 0o644)
        self.assertFalse((self.paths.etc / "update-token").exists())
        self.assertEqual(json.loads(self.paths.marker.read_text())["how"], "moved")
        self.assertIn(["useradd", "--system", "--user-group", "--no-create-home", "--home-dir", str(self.paths.state), "--shell", "/usr/sbin/nologin", "ft-server"], fake.calls)
        self.assertIn(["systemctl", "restart", "flight-tracker.service"], fake.calls)
        self.assertEqual(fake.health_calls, ["1.0.7"])
        # Never touches the desktop login itself.
        for call in fake.calls:
            if call[0] in ("useradd", "usermod", "userdel"):
                self.assertNotIn(DESKTOP, call)
        self.assertIsNone(harden.harden_if_needed(paths=self.paths, system=fake.system()))

    def test_unhealthy_restart_is_undone(self) -> None:
        fake = FakeSystem(healthy=False)
        result = harden.harden(paths=self.paths, system=fake.system())
        self.assertFalse(result["ok"])
        self.assertTrue(result["rolledBack"])
        self.assertFalse(self.paths.dropin.exists())
        self.assertEqual(harden.unit_user(self.paths), DESKTOP)
        self.assertEqual(self.paths.sudoers.read_text(), self.old_sudoers)
        self.assertEqual(fake.owners[str(self.paths.etc / "config.json")], (1000, 1000))
        self.assertEqual(fake.owners[str(self.paths.opt)], (1000, 1000))
        self.assertEqual(fake.owners[str(self.paths.etc / "update-public.pem")], (0, 0))
        self.assertTrue((self.paths.etc / "update-token").exists())  # only removed after success
        self.assertEqual([c for c in fake.calls if c[:2] == ["systemctl", "restart"]], [["systemctl", "restart", "flight-tracker.service"]] * 2)
        marker = json.loads(self.paths.marker.read_text())
        self.assertEqual(marker["user"], DESKTOP)
        self.assertTrue(marker["how"].startswith("failed"))
        self.assertIsNone(harden.harden_if_needed(paths=self.paths, system=fake.system()))  # no nightly retry loop

    def test_bad_sudoers_or_useradd_changes_nothing_lasting(self) -> None:
        for fake in (FakeSystem(visudo_ok=False), FakeSystem(useradd_ok=False)):
            self.paths.marker.unlink(missing_ok=True)
            result = harden.harden(paths=self.paths, system=fake.system())
            self.assertFalse(result["ok"])
            self.assertEqual(self.paths.sudoers.read_text(), self.old_sudoers)
            self.assertFalse(self.paths.dropin.exists())
            self.assertEqual(harden.unit_user(self.paths), DESKTOP)

    def test_already_hardened_or_unexpected(self) -> None:
        self.paths.unit_file.write_text("[Service]\nUser=ft-server\n")
        self.assertEqual(harden.harden(paths=self.paths, system=FakeSystem().system())["changed"], False)
        self.paths.unit_file.write_text("[Service]\nUser=root\n")
        self.assertFalse(harden.harden(paths=self.paths, system=FakeSystem().system())["ok"])

    def test_install_script_and_wrapper(self) -> None:
        install = (ROOT / "install.sh").read_text()
        self.assertIn('SERVICE_USER="ft-server"', install)
        self.assertIn('sed "s/@USER@/${SERVICE_USER}/g" /opt/flight-tracker/current/deploy/flight-tracker.service', install)
        self.assertIn("${SERVICE_USER} ALL=(root) NOPASSWD: /usr/local/sbin/flight-tracker-update", install)
        self.assertNotIn("UPDATE_TOKEN", install)
        self.assertIn("rm -f /etc/flight-tracker/update-token", install)
        self.assertIn("/etc/flight-tracker-keys/release-${KID}.pem", install)
        self.assertIn("chown -R root:root /opt/flight-tracker", install)
        kiosk = (ROOT / "deploy/flight-tracker-kiosk.service").read_text() if (ROOT / "deploy/flight-tracker-kiosk.service").exists() else ""
        self.assertNotIn("ft-server", kiosk)
        wrapper = (ROOT / "deploy/flight-tracker-update").read_text()
        self.assertIn("--check|--install|--auto|--harden", wrapper)
        unit = (ROOT / "deploy/flight-tracker.service").read_text()
        self.assertIn("Environment=LG_WD=/var/cache/flight-tracker", unit)
        self.assertNotIn("UPDATE_TOKEN", (ROOT / "deploy/push-update.sh").read_text())


if __name__ == "__main__":
    unittest.main()
