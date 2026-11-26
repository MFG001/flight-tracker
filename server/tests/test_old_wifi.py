"""Old saved Wi-Fi is not retried after a new join; OTA installs display units."""
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

import updater as up  # noqa: E402
import wifi_net  # noqa: E402


def _exe(folder: Path, name: str, body: str) -> None:
    path = folder / name
    path.write_text("#!/bin/bash\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class WifiCtlForgetAndPromoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        (self.tmp / "profiles").write_text("", encoding="utf-8")
        (self.tmp / "active").write_text("", encoding="utf-8")
        (self.tmp / "connect-rc").write_text("0", encoding="utf-8")
        (self.tmp / "ssids").write_text("", encoding="utf-8")
        t = self.tmp
        _exe(
            t,
            "nmcli",
            f"""
{{ printf '%s' "CALL"; for a in "$@"; do printf '|%s' "$a"; done; printf '\\n'; }} >> {t}/calls
if [[ "$*" == "-t -f NAME,TYPE connection show" ]]; then cat {t}/profiles; exit 0; fi
if [[ "$*" == "-t -f UUID,TYPE,NAME connection show" ]]; then
  if [[ -f {t}/ids ]]; then cat {t}/ids; exit 0; fi
  i=1
  while IFS= read -r line; do
    [[ "$line" == *":802-11-wireless" ]] || continue
    name="${{line%:802-11-wireless}}"
    printf '00000000-0000-4000-8000-%012d:802-11-wireless:%s\\n' "$i" "$name"
    i=$((i+1))
  done < {t}/profiles
  exit 0
fi
if [[ "$*" == "-t -f UUID connection show --active" ]]; then cat {t}/active-uuids 2>/dev/null; exit 0; fi
lookup_name() {{
  local ref="$1" line name i=1
  if [[ -f {t}/ids ]]; then
    while IFS= read -r line; do
      typ="${{line#*:}}"; typ="${{typ%%:*}}"
      name="${{line#*:}}"; name="${{name#*:}}"
      uuid="${{line%%:*}}"
      if [[ "$ref" == "$uuid" || "$ref" == "$name" ]]; then printf '%s' "$name"; return; fi
    done < {t}/ids
  fi
  while IFS= read -r line; do
    [[ "$line" == *":802-11-wireless" ]] || continue
    name="${{line%:802-11-wireless}}"
    uuid="$(printf '00000000-0000-4000-8000-%012d' "$i")"
    if [[ "$ref" == "$uuid" || "$ref" == "$name" ]]; then printf '%s' "$name"; return; fi
    i=$((i+1))
  done < {t}/profiles
  printf '%s' "$ref"
}}
lookup_uuid() {{
  local ref="$1" line name i=1
  if [[ -f {t}/ids ]]; then
    while IFS= read -r line; do
      typ="${{line#*:}}"; typ="${{typ%%:*}}"
      name="${{line#*:}}"; name="${{name#*:}}"
      uuid="${{line%%:*}}"
      if [[ "$ref" == "$uuid" || "$ref" == "$name" ]]; then printf '%s' "$uuid"; return; fi
    done < {t}/ids
  fi
  while IFS= read -r line; do
    [[ "$line" == *":802-11-wireless" ]] || continue
    name="${{line%:802-11-wireless}}"
    uuid="$(printf '00000000-0000-4000-8000-%012d' "$i")"
    if [[ "$ref" == "$uuid" || "$ref" == "$name" ]]; then printf '%s' "$uuid"; return; fi
    i=$((i+1))
  done < {t}/profiles
}}
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
if [[ "$1" == "-g" && "$2" == "connection.id" ]]; then
  lookup_name "${{@: -1}}"; echo; exit 0
fi
if [[ "$1" == "-g" && "$2" == "connection.uuid" ]]; then
  lookup_uuid "${{@: -1}}"; echo; exit 0
fi
if [[ "$1" == "-g" && "$2" == "connection.autoconnect" ]]; then
  echo yes; exit 0
fi
if [[ "$1" == "-g" && "$2" == "connection.autoconnect-priority" ]]; then
  echo 0; exit 0
fi
if [[ "$*" == "-t -f NAME connection show --active" ]]; then cat {t}/active; exit 0; fi
if [[ "$1" == "--wait" && "$3" == "connection" ]]; then exit "$(cat {t}/up-rc 2>/dev/null || echo 0)"; fi
if [[ "$1" == "--wait" ]]; then exit "$(cat {t}/connect-rc)"; fi
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

    def test_successful_connect_prefers_new_and_keeps_others_autoconnect(self) -> None:
        (self.tmp / "profiles").write_text("OldNet:802-11-wireless\nNewNet:802-11-wireless\n", encoding="utf-8")
        (self.tmp / "ssids").write_text("OldNet=OldNet\nNewNet=NewNet\n", encoding="utf-8")
        result = self.run_ctl("connect", data="NewNet\npassword123\nno\n\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertTrue(any(c[:5] == ["--wait", "45", "dev", "wifi", "connect"] and c[5] == "NewNet" for c in calls))
        self.assertTrue(any(
            c[:3] == ["connection", "modify", "uuid"]
            and "connection.autoconnect-priority" in c and "100" in c and "yes" in c
            for c in calls
        ), calls)
        self.assertFalse(any(
            "connection.autoconnect" in c and c[-1] == "no"
            for c in calls
        ), calls)
        self.assertTrue(any(
            c[:3] == ["connection", "modify", "uuid"]
            and c[-2:] == ["connection.autoconnect", "yes"]
            for c in calls
        ), calls)

    def test_forget_deletes_client_profiles_only(self) -> None:
        (self.tmp / "profiles").write_text(
            "FlightTracker-Setup:802-11-wireless\nOldNet:802-11-wireless\n",
            encoding="utf-8",
        )
        result = self.run_ctl("forget")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OldNet", result.stdout)
        self.assertNotIn("FlightTracker-Setup", result.stdout)
        self.assertIn(["connection", "delete", "id", "OldNet"], self.calls())
        self.assertNotIn(["connection", "delete", "id", "FlightTracker-Setup"], self.calls())

    def test_boot_starts_hotspot_and_does_not_retry_saved_profile(self) -> None:
        (self.tmp / "profiles").write_text("OldNet:802-11-wireless\n", encoding="utf-8")
        result = self.run_ctl("boot-hotspot", "FlightTracker-Setup", "ABCDEFGH")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("started the setup hotspot", result.stdout.lower())
        ups = [c for c in self.calls() if c[:3] == ["connection", "up", "id"] and c[-1] == "OldNet"]
        self.assertEqual(ups, [])


class ForgetWifiPythonTests(unittest.TestCase):
    def test_forget_wifi_calls_helper(self) -> None:
        def fake(args, timeout=30, **kwargs):
            self.assertEqual(args[-1], "forget")
            return subprocess.CompletedProcess(args, 0, "OldNet\n", "")

        with mock.patch.object(wifi_net, "_run", side_effect=fake), mock.patch.object(
            wifi_net, "_helper", return_value=Path(__file__)
        ):
            ok, detail, start_ap = wifi_net.forget_wifi()
        self.assertTrue(ok)
        self.assertTrue(start_ap)
        self.assertIn("OldNet", detail)

    def test_setup_page_has_forget_action(self) -> None:
        html = (ROOT / "setup/index.html").read_text(encoding="utf-8")
        self.assertIn('id="wifi-forget"', html)
        self.assertIn("/api/wifi/forget", html)
        py = (ROOT / "server/flighttracker.py").read_text()
        self.assertIn('parsed.path == "/api/wifi/forget"', py)
        self.assertIn("forget_wifi", py)


class DisplayUnitOtaTests(unittest.TestCase):
    def test_ota_installs_display_units_with_real_users(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            release = tmp_path / "r"
            units = tmp_path / "systemd"
            (release / "deploy").mkdir(parents=True)
            units.mkdir()
            for name in ("flight-tracker.service", "flight-tracker-kiosk.service"):
                (release / "deploy" / name).write_text((ROOT / "deploy" / name).read_text(), encoding="utf-8")
            (units / "flight-tracker.service").write_text("[Service]\nUser=ft-server\n", encoding="utf-8")
            (units / "flight-tracker-kiosk.service").write_text("[Service]\nUser=flighttracker\n", encoding="utf-8")
            installed = up.refresh_display_units(release, units, run_systemctl=False)
            self.assertEqual(installed, list(up.DISPLAY_UNITS))
            server = (units / "flight-tracker.service").read_text()
            kiosk = (units / "flight-tracker-kiosk.service").read_text()
            self.assertNotIn("@USER@", server)
            self.assertNotIn("@USER@", kiosk)
            self.assertIn("User=ft-server", server)
            self.assertIn("User=flighttracker", kiosk)
            self.assertNotIn("network-online.target", server)

    def test_apply_update_refreshes_display_units(self) -> None:
        text = (ROOT / "server/updater.py").read_text()
        self.assertIn("refresh_display_units(final)", text)
        self.assertIn("DISPLAY_UNITS", text)

    def test_wifi_service_does_not_wait_for_display_server(self) -> None:
        unit = (ROOT / "deploy/flight-tracker-wifi.service").read_text()
        self.assertIn("After=NetworkManager.service", unit)
        after = unit.split("After=", 1)[1].splitlines()[0]
        self.assertNotIn("flight-tracker.service", after)


if __name__ == "__main__":
    unittest.main()
