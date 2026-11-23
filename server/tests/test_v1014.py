"""1.0.14: setup hotspot when saved Wi-Fi is out of range; join QR only if AP is up."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

try:
    from server.tests.test_v103 import _exe  # noqa: E402
except ImportError:
    from test_v103 import _exe  # type: ignore  # noqa: E402

import updater as up  # noqa: E402
import wifi_net  # noqa: E402

SPACED = "Home Net "
MAKERWORLD = "https://makerworld.com/en/models/3669492-aircraft-flight-tracker-desktop-ads-b-radar"
OLD_MAKERWORLD = "https://makerworld.com/en/models/3666834-flight-tracker-instrument-case"


class VersionPinTests(unittest.TestCase):
    def test_version_is_1014_everywhere(self) -> None:
        self.assertEqual((ROOT / "VERSION").read_text().strip(), "1.0.14")
        self.assertEqual(json.loads((ROOT / "package.json").read_text())["version"], "1.0.14")
        lock = json.loads((ROOT / "package-lock.json").read_text())
        self.assertEqual((lock["version"], lock["packages"][""]["version"]), ("1.0.14", "1.0.14"))
        self.assertIn("FlightTracker/1.0.14 ", (ROOT / "server/flighttracker.py").read_text())


class MakerWorldLinkTests(unittest.TestCase):
    def test_docs_use_the_live_listing(self) -> None:
        for rel in ("README.md", "docs/BUILD.md", "docs/SOFTWARE.md"):
            text = (ROOT / rel).read_text()
            self.assertIn(MAKERWORLD, text, rel)
            self.assertNotIn(OLD_MAKERWORLD, text, rel)


class WifiStatusTests(unittest.TestCase):
    def test_offline_when_no_profile_and_ap_is_down(self) -> None:
        def fake(args, timeout=8):
            if args[:2] == ["nmcli", "-v"]:
                return subprocess.CompletedProcess(args, 0, "nmcli 1.52", "")
            if "--active" in args:
                return subprocess.CompletedProcess(args, 0, "", "")
            if args[:3] == ["nmcli", "-t", "-f"] and "NAME,TYPE" in args:
                return subprocess.CompletedProcess(args, 0, "", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        with mock.patch.object(wifi_net, "_run", side_effect=fake):
            status = wifi_net.wifi_status({"password": "ABCDEFGH"})
        self.assertEqual(status["state"], "offline")
        self.assertEqual(status["connectedSsid"], "")

    def test_failed_when_saved_client_is_down(self) -> None:
        def fake(args, timeout=8):
            if args[:2] == ["nmcli", "-v"]:
                return subprocess.CompletedProcess(args, 0, "nmcli 1.52", "")
            if "--active" in args:
                return subprocess.CompletedProcess(args, 0, "Wired connection 1:802-3-ethernet:eth0\n", "")
            if "NAME,TYPE" in " ".join(args) and "--active" not in args:
                return subprocess.CompletedProcess(
                    args, 0, f"{SPACED}:802-11-wireless\nWired connection 1:802-3-ethernet\n", ""
                )
            return subprocess.CompletedProcess(args, 0, "", "")

        with mock.patch.object(wifi_net, "_run", side_effect=fake):
            status = wifi_net.wifi_status({"password": "ABCDEFGH"})
        self.assertEqual(status["state"], "failed")
        self.assertIn("Home Net", status["note"])

    def test_hotspot_only_when_ap_is_up(self) -> None:
        def fake(args, timeout=8):
            if args[:2] == ["nmcli", "-v"]:
                return subprocess.CompletedProcess(args, 0, "nmcli 1.52", "")
            if "--active" in args:
                return subprocess.CompletedProcess(args, 0, "FlightTracker-Setup:802-11-wireless:wlan0\n", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        with mock.patch.object(wifi_net, "_run", side_effect=fake):
            status = wifi_net.wifi_status({"password": "ABCDEFGH"})
        self.assertIn(status["state"], ("hotspot", "portal"))


class JoinCardTests(unittest.TestCase):
    def test_join_setup_card_only_for_active_hotspot(self) -> None:
        main = (ROOT / "src/main.ts").read_text()
        self.assertIn('const outage = state === "hotspot" || state === "portal";', main)
        self.assertNotIn('state === "hotspot" || state === "portal" || state === "failed"', main)
        self.assertIn('info.state === "hotspot" ? "hotspot" : ""', main)
        self.assertIn("if (view) await renderWifi(view, info);", main)
        self.assertIn('else if (!outage && state !== "connected" && !wifiPinned)', main)


class WifiFallbackTests(unittest.TestCase):
    """scripts/wifi-ctl.sh boot-hotspot against a fake nmcli and iw."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "profiles").write_text("", encoding="utf-8")
        (self.tmp / "active").write_text("", encoding="utf-8")
        (self.tmp / "stations").write_text("", encoding="utf-8")
        (self.tmp / "connect-rc").write_text("0", encoding="utf-8")
        (self.tmp / "up-rc").write_text("0", encoding="utf-8")
        t = self.tmp
        _exe(t, "nmcli", f'''
{{ printf '%s' "CALL"; for a in "$@"; do printf '|%s' "$a"; done; printf '\\n'; }} >> {t}/calls
if [[ "$*" == "-t -f NAME,TYPE connection show" ]]; then cat {t}/profiles; exit 0; fi
if [[ "$1" == "-g" && "$2" == "802-11-wireless.mode" ]]; then
  name="${{@: -1}}"
  if [[ "$name" == "Hotspot" || "$name" == "FlightTracker-Setup" ]]; then echo ap; else echo infrastructure; fi
  exit 0
fi
if [[ "$*" == "-t -f NAME connection show --active" ]]; then cat {t}/active; exit 0; fi
if [[ "$1" == "dev" && "$2" == "wifi" && "$3" == "hotspot" ]]; then
  grep -qxF "FlightTracker-Setup:802-11-wireless" {t}/profiles || echo "FlightTracker-Setup:802-11-wireless" >> {t}/profiles
  printf '%s\\n' "FlightTracker-Setup" "Wired connection 1" > {t}/active
  exit 0
fi
if [[ "$1" == "connection" && "$2" == "up" && "$3" == "id" ]]; then
  if [[ "$(cat {t}/up-rc)" != "0" ]]; then exit "$(cat {t}/up-rc)"; fi
  name="$4"
  if [[ "$name" == "FlightTracker-Setup" || "$name" == "Hotspot" ]]; then
    printf '%s\\n' "$name" "Wired connection 1" > {t}/active
  else
    printf '%s\\n' "$name" "Wired connection 1" > {t}/active
  fi
  exit 0
fi
if [[ "$1" == "connection" && "$2" == "down" && "$3" == "id" ]]; then
  grep -Fxv -- "$4" {t}/active > {t}/active.tmp || true
  mv {t}/active.tmp {t}/active
  exit 0
fi
if [[ "$1" == "--wait" ]]; then exit "$(cat {t}/connect-rc)"; fi
exit 0
''')
        _exe(t, "iw", f'''
if [[ "$1" == "dev" && "$3" == "station" ]]; then
  cat {t}/stations
  exit 0
fi
exit 0
''')
        self.hotspot_json = self.tmp / "hotspot.json"
        self.hotspot_json.write_text(json.dumps({"ssid": "FlightTracker-Setup", "password": "ABCDEFGH"}), encoding="utf-8")
        self.test_dir = self.tmp / "wifitest"
        self.test_dir.mkdir()
        self.env = {
            "PATH": f"{t}:/usr/bin:/bin",
            "FT_WIFI_SETTLE": "0",
            "FT_WIFI_GRACE_SECONDS": "0",
            "FT_WIFI_RETRY_SECONDS": "0",
            "FT_WIFI_POLL": "0.05",
            "FT_WIFI_TEST_DIR": str(self.test_dir),
            "FT_HOTSPOT_JSON": str(self.hotspot_json),
            "FT_SERVER_DIR": str(ROOT / "server"),
            "FT_WIFI_CONNECTING": str(self.tmp / "connecting"),
        }

    def calls(self) -> list[list[str]]:
        path = self.tmp / "calls"
        if not path.is_file():
            return []
        return [line.split("|")[1:] for line in path.read_text(encoding="utf-8").splitlines()]

    def run_ctl(self, *args: str, env: dict[str, str] | None = None, timeout: float = 20) -> subprocess.CompletedProcess[str]:
        merged = dict(self.env)
        if env:
            merged.update(env)
        return subprocess.run(
            ["bash", str(ROOT / "scripts/wifi-ctl.sh"), *args],
            env=merged, capture_output=True, text=True, timeout=timeout,
        )

    def test_starts_hotspot_when_saved_wifi_is_out_of_range(self) -> None:
        (self.tmp / "profiles").write_text(f"{SPACED}:802-11-wireless\nWired connection 1:802-3-ethernet\n")
        (self.tmp / "active").write_text("Wired connection 1\n")
        result = self.run_ctl("boot-hotspot", "FlightTracker-Setup", "ABCDEFGH")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("No saved Wi-Fi came up", result.stdout)
        self.assertTrue(any("hotspot" in c for c in self.calls()))

    def test_ethernet_alone_does_not_count_as_wifi(self) -> None:
        (self.tmp / "profiles").write_text(f"{SPACED}:802-11-wireless\nWired connection 1:802-3-ethernet\n")
        (self.tmp / "active").write_text("Wired connection 1\n")
        result = self.run_ctl("boot-hotspot", "FlightTracker-Setup", "ABCDEFGH")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(any("hotspot" in c for c in self.calls()))

    def test_waits_grace_then_starts_if_still_down(self) -> None:
        (self.tmp / "profiles").write_text(f"{SPACED}:802-11-wireless\n")
        result = self.run_ctl(
            "boot-hotspot", "FlightTracker-Setup", "ABCDEFGH",
            env={"FT_WIFI_GRACE_SECONDS": "1", "FT_WIFI_POLL": "0.1"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("No saved Wi-Fi came up", result.stdout)
        self.assertTrue(any("hotspot" in c for c in self.calls()))

    def test_connects_during_grace_and_skips_hotspot(self) -> None:
        (self.tmp / "profiles").write_text(f"{SPACED}:802-11-wireless\n")

        def late_connect() -> None:
            import time
            time.sleep(0.2)
            (self.tmp / "active").write_text(SPACED + "\n")

        import threading
        threading.Thread(target=late_connect, daemon=True).start()
        result = self.run_ctl(
            "boot-hotspot", "FlightTracker-Setup", "ABCDEFGH",
            env={"FT_WIFI_GRACE_SECONDS": "2", "FT_WIFI_POLL": "0.1"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("not starting the setup hotspot", result.stdout)
        self.assertFalse([c for c in self.calls() if "hotspot" in c])

    def test_retry_rejoins_saved_network_when_no_station(self) -> None:
        (self.tmp / "profiles").write_text(f"{SPACED}:802-11-wireless\n")
        result = self.run_ctl(
            "boot-hotspot", "FlightTracker-Setup", "ABCDEFGH",
            env={"FT_WIFI_RETRY_SECONDS": "1", "FT_WIFI_RETRY_LIMIT": "2"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Joined saved Wi-Fi", result.stdout)
        self.assertIn(SPACED, result.stdout)
        downs = [c for c in self.calls() if c[:3] == ["connection", "down", "id"] and c[3] == "FlightTracker-Setup"]
        self.assertTrue(downs, self.calls())
        ups = [c for c in self.calls() if c[:4] == ["connection", "up", "id", SPACED]]
        self.assertTrue(ups, self.calls())

    def test_retry_leaves_hotspot_up_when_phone_is_joined(self) -> None:
        (self.tmp / "profiles").write_text(f"{SPACED}:802-11-wireless\n")
        (self.tmp / "stations").write_text("Station aa:bb:cc:dd:ee:ff (on wlan0)\n")
        result = self.run_ctl(
            "boot-hotspot", "FlightTracker-Setup", "ABCDEFGH",
            env={"FT_WIFI_RETRY_SECONDS": "1", "FT_WIFI_RETRY_LIMIT": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("a phone is connected or setup is in progress", result.stdout)
        downs = [c for c in self.calls() if c[:3] == ["connection", "down", "id"] and c[3] == "FlightTracker-Setup"]
        self.assertFalse(downs, downs)

    def test_retry_leaves_hotspot_up_while_setup_connect_is_running(self) -> None:
        (self.tmp / "profiles").write_text(f"{SPACED}:802-11-wireless\n")
        (self.tmp / "connecting").write_text("1\n")
        result = self.run_ctl(
            "boot-hotspot", "FlightTracker-Setup", "ABCDEFGH",
            env={"FT_WIFI_RETRY_SECONDS": "1", "FT_WIFI_RETRY_LIMIT": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("a phone is connected or setup is in progress", result.stdout)
        downs = [c for c in self.calls() if c[:3] == ["connection", "down", "id"] and c[3] == "FlightTracker-Setup"]
        self.assertFalse(downs, downs)

    def test_boot_leaves_test_hotspot_alone(self) -> None:
        (self.tmp / "profiles").write_text(f"{SPACED}:802-11-wireless\n")
        (self.test_dir / "running").write_text("1\n")
        result = self.run_ctl("boot-hotspot", "FlightTracker-Setup", "ABCDEFGH")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("A Wi-Fi test is running", result.stdout)
        self.assertFalse([c for c in self.calls() if "hotspot" in c])

    def test_wifi_setup_starts_fallback_when_saved_network_is_down(self) -> None:
        (self.tmp / "profiles").write_text(f"{SPACED}:802-11-wireless\n")
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/wifi-setup.sh")],
            env=self.env, capture_output=True, text=True, timeout=20, cwd=self.tmp,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("No saved Wi-Fi came up", result.stdout)
        self.assertTrue(any("hotspot" in c for c in self.calls()))
        self.assertNotIn("ABCDEFGH", result.stdout + result.stderr)


class SystemdRefreshTests(unittest.TestCase):
    def test_ota_copies_and_restarts_wifi_service(self) -> None:
        self.assertIn("flight-tracker-wifi.service", up.SYSTEMD_UNITS)
        self.assertIn("flight-tracker-wifi.service", up.SERVICE_UNITS)
        with tempfile.TemporaryDirectory() as tmp:
            release = Path(tmp) / "r"
            units = Path(tmp) / "systemd"
            runtime = Path(tmp) / "run"
            (release / "deploy").mkdir(parents=True)
            units.mkdir()
            runtime.mkdir()
            for name in up.SYSTEMD_UNITS:
                (release / "deploy" / name).write_text((ROOT / "deploy" / name).read_text())
            calls: list[list[str]] = []

            def fake_run(argv, **kwargs):
                calls.append(list(argv))
                return mock.Mock(returncode=0, stdout=b"", stderr=b"")

            with mock.patch.object(up.subprocess, "run", fake_run):
                installed = up.refresh_systemd_units(
                    release, units, systemctl="/bin/systemctl", runtime_dir=runtime,
                )
            self.assertIn("flight-tracker-wifi.service", installed)
            dest = units / "flight-tracker-wifi.service"
            self.assertIn("Type=simple", dest.read_text())
            actions = [tuple(c) for c in calls]
            self.assertIn(("/bin/systemctl", "enable", "flight-tracker-wifi.service"), actions)
            self.assertIn(("/bin/systemctl", "restart", "flight-tracker-wifi.service"), actions)


if __name__ == "__main__":
    unittest.main()
