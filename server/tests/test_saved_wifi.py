"""Saved Wi-Fi list, per-network forget/prefer/password, and autoconnect."""
from __future__ import annotations

import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

import wifi_net  # noqa: E402


HOME = "aaaaaaaa-1111-4111-8111-000000000001"
SHOP = "aaaaaaaa-1111-4111-8111-000000000002"
TRAVEL = "aaaaaaaa-1111-4111-8111-000000000003"
SETUP = "aaaaaaaa-1111-4111-8111-000000000099"
SPACE = "aaaaaaaa-1111-4111-8111-000000000004"
CAFE = "aaaaaaaa-1111-4111-8111-000000000005"
SPACED = "Home Net "


def _exe(folder: Path, name: str, body: str) -> None:
    path = folder / name
    path.write_text("#!/bin/bash\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class SavedWifiCtlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        t = self.tmp
        (t / "ids").write_text(
            f"{HOME}:802-11-wireless:Home\n"
            f"{SHOP}:802-11-wireless:Shop\n"
            f"{TRAVEL}:802-11-wireless:Travel\n"
            f"{SETUP}:802-11-wireless:FlightTracker-Setup\n",
            encoding="utf-8",
        )
        (t / "profiles").write_text(
            "Home:802-11-wireless\nShop:802-11-wireless\nTravel:802-11-wireless\n"
            "FlightTracker-Setup:802-11-wireless\n",
            encoding="utf-8",
        )
        (t / "ssids").write_text("Home=Home\nShop=Shop\nTravel=Travel\nFlightTracker-Setup=FlightTracker-Setup\n", encoding="utf-8")
        (t / "auto").write_text("Home=yes\nShop=yes\nTravel=yes\nFlightTracker-Setup=no\n", encoding="utf-8")
        (t / "prio").write_text("Home=100\nShop=0\nTravel=0\nFlightTracker-Setup=0\n", encoding="utf-8")
        (t / "active-uuids").write_text(HOME + "\n", encoding="utf-8")
        (t / "active").write_text("Home\n", encoding="utf-8")
        (t / "connect-rc").write_text("0", encoding="utf-8")
        (t / "up-rc").write_text("0", encoding="utf-8")
        _exe(
            t,
            "nmcli",
            f"""
{{ printf '%s' "CALL"; for a in "$@"; do printf '|%s' "$a"; done; printf '\\n'; }} >> {t}/calls
lookup_name() {{
  local ref="$1" line name uuid
  while IFS= read -r line; do
    uuid="${{line%%:*}}"
    name="${{line#*:}}"; name="${{name#*:}}"
    if [[ "$ref" == "$uuid" || "$ref" == "$name" ]]; then printf '%s' "$name"; return; fi
  done < {t}/ids
  printf '%s' "$ref"
}}
lookup_uuid() {{
  local ref="$1" line name uuid
  while IFS= read -r line; do
    uuid="${{line%%:*}}"
    name="${{line#*:}}"; name="${{name#*:}}"
    if [[ "$ref" == "$uuid" || "$ref" == "$name" ]]; then printf '%s' "$uuid"; return; fi
  done < {t}/ids
}}
if [[ "$*" == "-t -f NAME,TYPE connection show" ]]; then cat {t}/profiles; exit 0; fi
if [[ "$*" == "-t -f UUID,TYPE,NAME connection show" ]]; then cat {t}/ids; exit 0; fi
if [[ "$*" == "-t -f UUID connection show --active" ]]; then cat {t}/active-uuids; exit 0; fi
if [[ "$*" == "-t -f NAME connection show --active" ]]; then cat {t}/active; exit 0; fi
if [[ "$1" == "-g" && "$2" == "802-11-wireless.mode" ]]; then
  name="$(lookup_name "${{@: -1}}")"
  if [[ "$name" == "Hotspot" || "$name" == "FlightTracker-Setup" ]]; then echo ap; else echo infrastructure; fi
  exit 0
fi
if [[ "$1" == "-g" && "$2" == "802-11-wireless.ssid" ]]; then
  name="$(lookup_name "${{@: -1}}")"
  found="$(awk -F= -v n="$name" '$1==n {{print $2; exit}}' {t}/ssids 2>/dev/null || true)"
  if [[ -n "$found" ]]; then echo "$found"; else echo "$name"; fi
  exit 0
fi
if [[ "$1" == "-g" && "$2" == "connection.id" ]]; then lookup_name "${{@: -1}}"; echo; exit 0; fi
if [[ "$1" == "-g" && "$2" == "connection.uuid" ]]; then lookup_uuid "${{@: -1}}"; echo; exit 0; fi
if [[ "$1" == "-g" && "$2" == "connection.autoconnect" ]]; then
  name="$(lookup_name "${{@: -1}}")"
  found="$(awk -F= -v n="$name" '$1==n {{print $2; exit}}' {t}/auto 2>/dev/null || true)"
  echo "${{found:-yes}}"; exit 0
fi
if [[ "$1" == "-g" && "$2" == "connection.autoconnect-priority" ]]; then
  name="$(lookup_name "${{@: -1}}")"
  found="$(awk -F= -v n="$name" '$1==n {{print $2; exit}}' {t}/prio 2>/dev/null || true)"
  echo "${{found:-0}}"; exit 0
fi
if [[ "$1" == "--wait" && "$3" == "connection" ]]; then exit "$(cat {t}/up-rc)"; fi
if [[ "$1" == "--wait" ]]; then exit "$(cat {t}/connect-rc)"; fi
if [[ "$1" == "connection" && "$2" == "delete" ]]; then
  # do not actually edit files; tests check the call log
  exit 0
fi
exit 0
""",
        )
        self.env = {
            "PATH": f"{t}:/usr/bin:/bin",
            "FT_WIFI_SETTLE": "0",
            "FT_WIFI_GRACE_SECONDS": "0",
            "FT_WIFI_RETRY_SECONDS": "0",
            "FT_WIFI_POLL": "0.05",
        }

    def calls(self) -> list[list[str]]:
        path = self.tmp / "calls"
        if not path.is_file():
            return []
        return [line.split("|")[1:] for line in path.read_text(encoding="utf-8").splitlines()]

    def run_ctl(self, *args: str, data: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(ROOT / "scripts/wifi-ctl.sh"), *args],
            input=data,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_saved_lists_client_ssids_without_secrets(self) -> None:
        result = self.run_ctl("saved")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = wifi_net.parse_saved(result.stdout)
        ssids = [row["ssid"] for row in rows]
        self.assertEqual(ssids, ["Home", "Shop", "Travel"])
        self.assertTrue(rows[0]["active"])
        self.assertTrue(rows[0]["preferred"])
        self.assertFalse(rows[1]["preferred"])
        secretish = result.stdout + result.stderr
        self.assertNotIn("psk", secretish.lower())
        self.assertNotIn("password", secretish.lower())
        self.assertNotIn("wifi-sec", secretish.lower())
        self.assertNotIn("802-11-wireless-security", secretish)

    def test_saved_keeps_trailing_space_and_unicode(self) -> None:
        (self.tmp / "ids").write_text(
            f"{SPACE}:802-11-wireless:{SPACED}\n{CAFE}:802-11-wireless:Café\n",
            encoding="utf-8",
        )
        (self.tmp / "ssids").write_text(f"{SPACED}={SPACED}\nCafé=Café\n", encoding="utf-8")
        (self.tmp / "auto").write_text(f"{SPACED}=yes\nCafé=yes\n", encoding="utf-8")
        (self.tmp / "prio").write_text(f"{SPACED}=0\nCafé=0\n", encoding="utf-8")
        (self.tmp / "active-uuids").write_text("", encoding="utf-8")
        result = self.run_ctl("saved")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = wifi_net.parse_saved(result.stdout)
        self.assertEqual([row["ssid"] for row in rows], [SPACED, "Café"])
        self.assertTrue(all(not row["preferred"] for row in rows))

    def test_prefer_raises_priority_and_keeps_others_autoconnect(self) -> None:
        result = self.run_ctl("prefer", "uuid", SHOP)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Shop", result.stdout)
        calls = self.calls()
        self.assertTrue(any(
            c[:4] == ["connection", "modify", "uuid", SHOP]
            and "connection.autoconnect-priority" in c and "100" in c
            and "yes" in c
            for c in calls
        ), calls)
        self.assertTrue(any(
            c[:4] == ["connection", "modify", "uuid", HOME]
            and "connection.autoconnect-priority" in c and "50" in c
            and "yes" in c
            for c in calls
        ), calls)
        self.assertFalse(any(c[-1] == "no" and "connection.autoconnect" in c for c in calls), calls)
        self.assertFalse(any("FlightTracker-Setup" in c or SETUP in c and "modify" in c for c in calls), calls)

    def test_prefer_by_exact_name_with_trailing_space(self) -> None:
        (self.tmp / "ids").write_text(f"{SPACE}:802-11-wireless:{SPACED}\n", encoding="utf-8")
        result = self.run_ctl("prefer", "id", SPACED)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(c[:4] == ["connection", "modify", "uuid", SPACE] for c in self.calls()), self.calls())

    def test_forget_one_by_uuid_leaves_setup_and_others(self) -> None:
        result = self.run_ctl("forget", "uuid", SHOP)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "Shop")
        self.assertIn(["connection", "delete", "uuid", SHOP], self.calls())
        self.assertNotIn(["connection", "delete", "uuid", SETUP], self.calls())
        self.assertNotIn(["connection", "delete", "uuid", HOME], self.calls())

    def test_forget_refuses_setup_hotspot(self) -> None:
        result = self.run_ctl("forget", "uuid", SETUP)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("setup network", result.stderr.lower())
        self.assertFalse(any("delete" in c for c in self.calls() if "delete" in c), self.calls())
        # The call log still has show queries; ensure no delete of the AP.
        self.assertFalse(any(c[:3] == ["connection", "delete", "uuid"] and SETUP in c for c in self.calls()))

    def test_password_updates_psk_on_stdin_and_reconnects_when_active(self) -> None:
        secret = "new pass'word"
        result = self.run_ctl("password", "uuid", HOME, data=secret + "\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reconnected", result.stdout.lower())
        self.assertNotIn(secret, result.stdout)
        self.assertNotIn(secret, result.stderr)
        calls = self.calls()
        self.assertTrue(any(
            c[:4] == ["connection", "modify", "uuid", HOME]
            and "802-11-wireless-security.psk" in c and secret in c
            for c in calls
        ), calls)
        self.assertTrue(any(c[:5] == ["--wait", "45", "connection", "up", "uuid"] and HOME in c for c in calls), calls)

    def test_password_failed_reconnect_keeps_profile(self) -> None:
        (self.tmp / "up-rc").write_text("1", encoding="utf-8")
        secret = "changed-secret-99"
        result = self.run_ctl("password", "uuid", HOME, data=secret + "\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not reconnect", result.stderr.lower())
        self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertFalse(any(c[:2] == ["connection", "delete"] for c in self.calls()), self.calls())
        self.assertTrue(any("802-11-wireless-security.psk" in c for c in self.calls()))

    def test_password_skips_reconnect_when_not_connected(self) -> None:
        result = self.run_ctl("password", "uuid", SHOP, data="shop-pass-1\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Password updated.", result.stdout)
        self.assertNotIn("reconnected", result.stdout.lower())
        self.assertFalse(any(c[:3] == ["--wait", "45", "connection"] for c in self.calls()), self.calls())

    def test_password_refuses_setup_hotspot(self) -> None:
        result = self.run_ctl("password", "id", "FlightTracker-Setup", data="abcdefgh\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("setup network", result.stderr.lower())
        self.assertFalse(any("802-11-wireless-security.psk" in c for c in self.calls()), self.calls())

    def test_connect_still_does_not_retry_saved_at_boot(self) -> None:
        (self.tmp / "active").write_text("", encoding="utf-8")
        (self.tmp / "active-uuids").write_text("", encoding="utf-8")
        result = self.run_ctl("boot-hotspot", "FlightTracker-Setup", "ABCDEFGH")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("started the setup hotspot", result.stdout.lower())
        self.assertFalse(any(c[:3] == ["connection", "up", "id"] and c[-1] == "Home" for c in self.calls()))


class SavedWifiPythonTests(unittest.TestCase):
    def test_parse_saved_marks_preferred_and_active(self) -> None:
        sep = "\x1f"
        text = "\n".join([
            sep.join([HOME, "Home", "Home", "yes", "yes", "100"]),
            sep.join([SHOP, "Shop", "Shop", "no", "yes", "0"]),
        ])
        rows = wifi_net.parse_saved(text)
        self.assertEqual(rows[0]["ssid"], "Home")
        self.assertTrue(rows[0]["active"])
        self.assertTrue(rows[0]["preferred"])
        self.assertFalse(rows[1]["preferred"])

    def test_forget_one_python_starts_hotspot_only_when_active(self) -> None:
        sep = "\x1f"
        saved = sep.join([HOME, "Home", "Home", "yes", "yes", "100"]) + "\n"

        def fake(args, timeout=30, **kwargs):
            if args[-1] == "saved":
                return subprocess.CompletedProcess(args, 0, saved, "")
            self.assertEqual(args[-3:], ["forget", "uuid", HOME])
            return subprocess.CompletedProcess(args, 0, "Home\n", "")

        with mock.patch.object(wifi_net, "_run", side_effect=fake), mock.patch.object(
            wifi_net, "_helper", return_value=Path(__file__)
        ):
            ok, detail, start_ap = wifi_net.forget_wifi(uuid=HOME)
        self.assertTrue(ok)
        self.assertTrue(start_ap)
        self.assertIn("Home", detail)

        saved_inactive = sep.join([SHOP, "Shop", "Shop", "no", "yes", "0"]) + "\n"

        def fake2(args, timeout=30, **kwargs):
            if args[-1] == "saved":
                return subprocess.CompletedProcess(args, 0, saved_inactive, "")
            return subprocess.CompletedProcess(args, 0, "Shop\n", "")

        with mock.patch.object(wifi_net, "_run", side_effect=fake2), mock.patch.object(
            wifi_net, "_helper", return_value=Path(__file__)
        ):
            ok, detail, start_ap = wifi_net.forget_wifi(uuid=SHOP)
        self.assertTrue(ok)
        self.assertFalse(start_ap)

    def test_set_wifi_password_sends_stdin_and_scrubs_secret(self) -> None:
        secret = "super-secret-pass"

        def fake(args, input=None, timeout=60, **kwargs):
            self.assertEqual(args[-3:], ["password", "uuid", HOME])
            self.assertEqual(input, secret + "\n")
            return subprocess.CompletedProcess(args, 1, "", f"Error: ({secret}) failed")

        with mock.patch.object(wifi_net, "_run_input", side_effect=fake), mock.patch.object(
            wifi_net, "_helper", return_value=Path(__file__)
        ):
            ok, detail = wifi_net.set_wifi_password(uuid=HOME, password=secret)
        self.assertFalse(ok)
        self.assertNotIn(secret, detail)

    def test_prefer_and_password_validate_refs(self) -> None:
        ok, detail = wifi_net.prefer_wifi()
        self.assertFalse(ok)
        self.assertIn("which saved network", detail.lower())
        ok, detail = wifi_net.set_wifi_password(uuid="not-a-uuid", password="password1")
        self.assertFalse(ok)
        self.assertIn("id is not valid", detail.lower())

    def test_setup_page_and_server_have_saved_actions(self) -> None:
        html = (ROOT / "setup/index.html").read_text(encoding="utf-8")
        self.assertIn('id="saved-nets"', html)
        self.assertIn('id="wifi-forget"', html)
        self.assertIn('id="wifi-saved-pass"', html)
        self.assertIn("/api/wifi/saved", html)
        self.assertIn("/api/wifi/prefer", html)
        self.assertIn("/api/wifi/password", html)
        self.assertIn("CHANGE PASSWORD", html)
        self.assertIn("MAKE PREFERRED", html)
        self.assertIn("FORGET AND START HOTSPOT", html)
        self.assertIn("wifi-saved-pass", html)
        py = (ROOT / "server/flighttracker.py").read_text()
        self.assertIn('path == "/api/wifi/saved"', py)
        self.assertIn('parsed.path == "/api/wifi/prefer"', py)
        self.assertIn('parsed.path == "/api/wifi/password"', py)
        self.assertIn("set_wifi_password", py)


class SavedWifiHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        import argparse
        import shutil
        import threading
        import server.flighttracker as ft
        from http.server import ThreadingHTTPServer

        self.ft = ft
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        args = argparse.Namespace(
            dist=str(ROOT / "dist"),
            config=str(self.tmp / "config.json"),
            cache=str(self.tmp / "cache"),
            sample=str(ROOT / "data/sample-aircraft.json"),
            demo=True,
        )
        patch = mock.patch.object(ft.App, "apply_brightness", return_value=False)
        patch.start()
        self.addCleanup(patch.stop)
        self.app = ft.App(args)
        self.networks = [
            {"uuid": HOME, "name": "Home", "ssid": "Home", "active": True, "autoconnect": True, "priority": 100, "preferred": True},
            {"uuid": SHOP, "name": "Shop", "ssid": "Shop", "active": False, "autoconnect": True, "priority": 0, "preferred": False},
        ]
        self.patches = [
            mock.patch.object(ft, "saved_wifi", side_effect=lambda: list(self.networks)),
            mock.patch.object(ft, "prefer_wifi", return_value=(True, "Preferred Shop.")),
            mock.patch.object(ft, "forget_wifi", return_value=(True, "Forgot Shop.", False)),
            mock.patch.object(ft, "set_wifi_password", return_value=(True, "Password updated.")),
            mock.patch.object(ft, "start_setup_hotspot", return_value=(True, "Setup network is up.")),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ft.make_handler(self.app))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def get(self, path: str):
        import urllib.request
        with urllib.request.urlopen(self.base + path, timeout=10) as response:
            return json.loads(response.read())

    def post(self, path: str, body: dict, ok: bool = True):
        import urllib.request
        import urllib.error
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if ok:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read())
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=10)
        return json.loads(caught.exception.read())

    def test_get_saved_and_post_actions(self) -> None:
        body = self.get("/api/wifi/saved")
        self.assertEqual([row["ssid"] for row in body["networks"]], ["Home", "Shop"])
        self.assertNotIn("password", json.dumps(body["networks"]))
        preferred = self.post("/api/wifi/prefer", {"uuid": SHOP})
        self.assertTrue(preferred["ok"])
        forgotten = self.post("/api/wifi/forget", {"uuid": SHOP})
        self.assertTrue(forgotten["ok"])
        changed = self.post("/api/wifi/password", {"uuid": HOME, "password": "new-password-1"})
        self.assertTrue(changed["ok"])
        self.assertNotIn("new-password-1", json.dumps(changed))


if __name__ == "__main__":
    unittest.main()
