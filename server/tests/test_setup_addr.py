"""Setup address and on-demand hotspot: IPv4 on the card, start AP from WI-FI SETUP."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

import wifi_net  # noqa: E402

# Documentation / test-net address — not a private LAN IP (scrub_check).
LAN = "203.0.113.10"
LAN_URL = f"http://{LAN}/"
AP_IP = "10.42.0.1"
AP_URL = "http://10.42.0.1/"


def _nmcli_ok(args, timeout=8):
    if args[:2] == ["nmcli", "-v"]:
        return subprocess.CompletedProcess(args, 0, "nmcli 1.52", "")
    return None


class HttpUrlTests(unittest.TestCase):
    def test_builds_slash_terminated_http_url(self) -> None:
        self.assertEqual(wifi_net.http_url(LAN, wifi_net.CONFIG_URL), LAN_URL)
        self.assertEqual(wifi_net.http_url(" 10.42.0.1 ", wifi_net.CONFIG_URL), AP_URL)

    def test_falls_back_when_address_is_missing_or_bad(self) -> None:
        self.assertEqual(wifi_net.http_url("", wifi_net.CONFIG_URL), wifi_net.CONFIG_URL)
        self.assertEqual(wifi_net.http_url("flighttracker.local", AP_URL), AP_URL)
        self.assertEqual(wifi_net.http_url("not-an-ip", AP_URL), AP_URL)


class ServiceUrlTests(unittest.TestCase):
    def test_hotspot_uses_actual_wifi_ipv4(self) -> None:
        def fake(args, timeout=8):
            done = _nmcli_ok(args, timeout)
            if done:
                return done
            if "--active" in args:
                return subprocess.CompletedProcess(args, 0, "FlightTracker-Setup:802-11-wireless:wlan0\n", "")
            if args[:3] == ["nmcli", "-t", "-f"] and "DEVICE,TYPE,STATE,CONNECTION" in args:
                return subprocess.CompletedProcess(args, 0, "wlan0:wifi:connected:FlightTracker-Setup\n", "")
            if args[:3] == ["nmcli", "-g", "IP4.ADDRESS"]:
                return subprocess.CompletedProcess(args, 0, "10.42.0.1/24\n", "")
            if args[:2] == ["iw", "dev"]:
                return subprocess.CompletedProcess(args, 0, "", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        with mock.patch.object(wifi_net, "_run", side_effect=fake):
            status = wifi_net.wifi_status({"password": "ABCDEFGH"})
        self.assertEqual(status["state"], "hotspot")
        self.assertEqual(status["setupUrl"], AP_URL)
        self.assertEqual(status["setupQr"], AP_URL)
        self.assertEqual(status["configUrl"], wifi_net.CONFIG_URL)

    def test_connected_uses_lan_ipv4_not_mdns_name(self) -> None:
        def fake(args, timeout=8):
            done = _nmcli_ok(args, timeout)
            if done:
                return done
            if "--active" in args:
                return subprocess.CompletedProcess(args, 0, "HomeNet:802-11-wireless:wlan0\n", "")
            if args[:3] == ["nmcli", "-t", "-f"] and "DEVICE,TYPE,STATE,CONNECTION" in args:
                return subprocess.CompletedProcess(args, 0, "wlan0:wifi:connected:HomeNet\n", "")
            if args[:3] == ["nmcli", "-g", "IP4.ADDRESS"]:
                return subprocess.CompletedProcess(args, 0, f"{LAN}/24\n", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        with mock.patch.object(wifi_net, "_run", side_effect=fake):
            status = wifi_net.wifi_status({"password": "ABCDEFGH"})
        self.assertEqual(status["state"], "connected")
        self.assertEqual(status["configUrl"], LAN_URL)
        self.assertEqual(status["configQr"], LAN_URL)
        self.assertNotEqual(status["configUrl"], wifi_net.CONFIG_URL)

    def test_connected_without_ip_keeps_mdns_fallback(self) -> None:
        def fake(args, timeout=8):
            done = _nmcli_ok(args, timeout)
            if done:
                return done
            if "--active" in args:
                return subprocess.CompletedProcess(args, 0, "HomeNet:802-11-wireless:wlan0\n", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        with mock.patch.object(wifi_net, "_run", side_effect=fake):
            status = wifi_net.wifi_status({"password": "ABCDEFGH"})
        self.assertEqual(status["state"], "connected")
        self.assertEqual(status["configUrl"], wifi_net.CONFIG_URL)
        self.assertEqual(status["configQr"], wifi_net.CONFIG_URL)


class StartSetupHotspotTests(unittest.TestCase):
    def test_calls_helper_hotspot_command(self) -> None:
        calls: list[list[str]] = []

        def fake(args, timeout=8):
            calls.append(list(args))
            return subprocess.CompletedProcess(args, 0, "Hotspot started\n", "")

        with mock.patch.object(wifi_net, "_helper", return_value=Path("/usr/local/sbin/flight-tracker-wifi")):
            with mock.patch.object(Path, "is_file", return_value=True):
                with mock.patch.object(wifi_net, "_run", side_effect=fake):
                    ok, detail = wifi_net.start_setup_hotspot({"password": "ABCDEFGH"})
        self.assertTrue(ok)
        self.assertIn("Hotspot started", detail)
        self.assertEqual(
            calls[0],
            ["sudo", "-n", "/usr/local/sbin/flight-tracker-wifi", "hotspot", "FlightTracker-Setup", "ABCDEFGH"],
        )

    def test_scrubs_password_and_maps_sudo_error(self) -> None:
        def fake(args, timeout=8):
            return subprocess.CompletedProcess(args, 1, "", "sudo: a password is required")

        with mock.patch.object(wifi_net, "_helper", return_value=Path("/usr/local/sbin/flight-tracker-wifi")):
            with mock.patch.object(Path, "is_file", return_value=True):
                with mock.patch.object(wifi_net, "_run", side_effect=fake):
                    ok, detail = wifi_net.start_setup_hotspot({"password": "ABCDEFGH"})
        self.assertFalse(ok)
        self.assertIn("Wi-Fi permission", detail)
        self.assertNotIn("ABCDEFGH", detail)


class FrontendAndInstallTests(unittest.TestCase):
    def test_wifi_setup_starts_hotspot_when_not_already_up(self) -> None:
        main = (ROOT / "src/main.ts").read_text()
        self.assertIn('/api/wifi/hotspot', main)
        self.assertIn('info.state !== "connected" && info.state !== "portal" && info.state !== "hotspot"', main)
        self.assertIn("await renderWifi(view, info);", main)
        # Must not skip the card when state is failed/offline.
        self.assertNotIn('info.state === "hotspot" ? "hotspot" : ""', main)
        self.assertIn("Join this Wi-Fi, then scan.", main)
        self.assertNotIn("Scan to open setup.", main)

    def test_server_exposes_hotspot_post(self) -> None:
        server = (ROOT / "server/flighttracker.py").read_text()
        self.assertIn("start_setup_hotspot", server)
        self.assertIn('parsed.path == "/api/wifi/hotspot"', server)

    def test_hotspot_pins_shared_address(self) -> None:
        ctl = (ROOT / "scripts/wifi-ctl.sh").read_text()
        self.assertIn("ipv4.method shared", ctl)
        self.assertIn("ipv4.addresses 10.42.0.1/24", ctl)

    def test_install_writes_shared_dnsmasq_wildcard(self) -> None:
        install = (ROOT / "install.sh").read_text()
        conf = (ROOT / "deploy/dnsmasq-shared-flighttracker.conf").read_text()
        self.assertIn("/etc/NetworkManager/dnsmasq-shared.d/flighttracker.conf", install)
        self.assertIn("dnsmasq-shared-flighttracker.conf", install)
        self.assertIn("address=/#/10.42.0.1", conf)


if __name__ == "__main__":
    unittest.main()
