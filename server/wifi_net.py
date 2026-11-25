"""LAN Wi-Fi status, setup hotspot, and QR payloads.

NetworkManager commands are the Bookworm path. They were not run on a
Raspberry Pi in this project's test environment.
"""

from __future__ import annotations

import json
import re
import secrets
import subprocess
from pathlib import Path
from typing import Any

HOTSPOT_SSID = "FlightTracker-Setup"
# Profile names the setup hotspot can have. nmcli's `dev wifi hotspot` names
# its profile "Hotspot" unless told otherwise (1.0.2 did not), so a running
# hotspot was reported as a home connection called "Hotspot".
HOTSPOT_NAMES = frozenset({HOTSPOT_SSID, "Hotspot"})


def is_hotspot_name(name: str) -> bool:
    return name in HOTSPOT_NAMES
HOTSPOT_ADDRESS = "http://10.42.0.1/"
CONFIG_URL = "http://flighttracker.local/"
# TODO: NetworkManager's shared hotspot uses 10.42.0.1 by default. The wiki
# for NetworkManager does not promise that address, and it was not confirmed
# on a Pi here. The display shows this URL because it is NM's usual subnet.
# wifi-ctl.sh now pins ipv4.addresses to 10.42.0.1/24 on the setup AP.
_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def http_url(ip: str, fallback: str) -> str:
    """Build http://<ipv4>/, or fallback when no usable address is known."""
    address = (ip or "").strip()
    if _IPV4_RE.fullmatch(address):
        return f"http://{address}/"
    return fallback


def first_ipv4(devices: list[dict[str, str]], kind: str = "") -> str:
    for row in devices:
        if kind and row.get("type") != kind:
            continue
        ip = (row.get("ip") or "").strip()
        if _IPV4_RE.fullmatch(ip):
            return ip
    return ""


def apply_service_urls(payload: dict[str, Any]) -> dict[str, Any]:
    """Point the on-screen QR at a reachable IPv4 when one is known.

    flighttracker.local needs mDNS, which many phones skip on a no-internet
    hotspot and many guest/hotel networks block. The unit already reads its
    IPv4 via nmcli; the join and connected cards should show that address.
    """
    devices = payload.get("devices") or []
    state = payload.get("state")
    if state in ("hotspot", "portal"):
        url = http_url(first_ipv4(devices, "wifi"), HOTSPOT_ADDRESS)
        payload["setupUrl"] = url
        payload["setupQr"] = url
    elif state == "connected":
        ip = first_ipv4(devices, "wifi") or first_ipv4(devices, "ethernet")
        url = http_url(ip, CONFIG_URL)
        payload["configUrl"] = url
        payload["configQr"] = url
    return payload


def wifi_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace(":", r"\:")
        .replace('"', r"\"")
    )


def wifi_qr_payload(ssid: str, password: str) -> str:
    """Standard WIFI: URI so a phone camera joins a WPA hotspot."""
    return f"WIFI:T:WPA;S:{wifi_escape(ssid)};P:{wifi_escape(password)};;"


def load_hotspot(path: Path) -> dict[str, str]:
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            password = str(raw.get("password") or "")
            if re.fullmatch(r"[A-Z2-9]{8}", password):
                return {"ssid": HOTSPOT_SSID, "password": password}
        except (OSError, json.JSONDecodeError):
            pass
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    password = "".join(secrets.choice(alphabet) for _ in range(8))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ssid": HOTSPOT_SSID, "password": password}, indent=2) + "\n", encoding="utf-8")
    return {"ssid": HOTSPOT_SSID, "password": password}


def _run(args: list[str], timeout: float = 8) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, timeout=timeout, check=False, capture_output=True, text=True)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(args, 127, "", str(exc))


def nmcli_available() -> bool:
    return _run(["nmcli", "-v"]).returncode == 0


def _active_wifi() -> list[dict[str, str]]:
    result = _run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"])
    rows = []
    if result.returncode != 0:
        return rows
    for line in result.stdout.splitlines():
        parts = split_terse(line)
        if len(parts) < 3:
            continue
        name, kind, device = parts[0], parts[1], parts[2]
        if kind == "802-11-wireless":
            rows.append({"name": name, "device": device})
    return rows


def _stations(device: str) -> int:
    if not device or device == "--":
        return 0
    result = _run(["iw", "dev", device, "station", "dump"])
    if result.returncode != 0:
        return 0
    return result.stdout.count("\nStation ")


def wifi_status(hotspot: dict[str, str]) -> dict[str, Any]:
    """Best-effort NetworkManager status.

    TODO: association counts via `iw station dump` and the 10.42.0.1
    shared subnet were not verified on Raspberry Pi OS.
    """
    payload: dict[str, Any] = {
        "ssid": HOTSPOT_SSID,
        "password": hotspot["password"],
        "joinQr": wifi_qr_payload(HOTSPOT_SSID, hotspot["password"]),
        "setupUrl": HOTSPOT_ADDRESS,
        "setupQr": HOTSPOT_ADDRESS,
        "configUrl": CONFIG_URL,
        "configQr": CONFIG_URL,
        "clients": 0,
        "connectedSsid": "",
        "state": "unknown",
        "nmcli": nmcli_available(),
        "note": "",
    }
    if not payload["nmcli"]:
        payload["state"] = "unknown"
        payload["note"] = "NetworkManager (nmcli) is not available on this machine."
        return payload
    payload["devices"] = device_status()
    active = _active_wifi()
    hotspot_rows = [row for row in active if is_hotspot_name(row["name"])]
    home_rows = [row for row in active if not is_hotspot_name(row["name"])]
    if home_rows:
        payload["state"] = "connected"
        payload["connectedSsid"] = home_rows[0]["name"]
        return apply_service_urls(payload)
    if hotspot_rows:
        device = hotspot_rows[0]["device"]
        payload["clients"] = _stations(device)
        payload["state"] = "portal" if payload["clients"] else "hotspot"
        return apply_service_urls(payload)
    saved = _run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
    known = []
    if saved.returncode == 0:
        for line in saved.stdout.splitlines():
            parts = split_terse(line)
            if len(parts) >= 2 and parts[1] == "802-11-wireless" and not is_hotspot_name(parts[0]):
                known.append(parts[0])
    if known:
        payload["state"] = "failed"
        payload["note"] = f"Saved Wi-Fi is not connected ({', '.join(known[:3])})."
        return apply_service_urls(payload)
    # Do not report "hotspot" unless the AP is actually up; the join QR
    # card is only shown for hotspot/portal.
    payload["state"] = "offline"
    payload["note"] = "The setup network is not up yet."
    return apply_service_urls(payload)


WRAPPER = Path("/usr/local/sbin/flight-tracker-wifi")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def _helper() -> Path:
    if WRAPPER.is_file():
        return WRAPPER
    return Path(__file__).resolve().parent.parent / "scripts" / "wifi-ctl.sh"


def _run_input(args: list[str], data: str, timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, input=data, timeout=timeout, check=False, capture_output=True, text=True)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(args, 127, "", str(exc))


def split_terse(line: str) -> list[str]:
    """Split one `nmcli -t` row. nmcli escapes ':' and '\\' inside values."""
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    fields.append("".join(current))
    return fields


def parse_scan(text: str, limit: int = 30) -> list[dict[str, Any]]:
    """Parse IN-USE,SSID,SIGNAL,SECURITY (or SSID,SIGNAL,SECURITY) rows.

    Hidden networks (blank SSID) are skipped. Each SSID appears once with its
    strongest signal. Sorted by signal, strongest first.
    """
    best: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = split_terse(line)
        if len(parts) >= 4:
            in_use, ssid, signal_text, security = parts[0], parts[1], parts[2], ":".join(parts[3:])
        elif len(parts) == 3:
            in_use, ssid, signal_text, security = "", parts[0], parts[1], parts[2]
        else:
            continue
        if not ssid or len(ssid.encode("utf-8")) > 32:
            continue
        try:
            signal = max(0, min(100, int(signal_text)))
        except ValueError:
            signal = 0
        security = security.strip()
        if security in ("--", ""):
            security = ""
        row = {
            "ssid": ssid,
            "signal": signal,
            "security": security or "Open",
            "secured": bool(security),
            "inUse": in_use.strip() == "*",
        }
        old = best.get(ssid)
        if old is None or signal > old["signal"] or row["inUse"]:
            if old is not None and old["inUse"]:
                row["inUse"] = True
            best[ssid] = row
    rows = sorted(best.values(), key=lambda item: (-int(item["inUse"]), -item["signal"], item["ssid"].lower()))
    return rows[:limit]


def wifi_scan(rescan: bool = True) -> list[dict[str, Any]]:
    """Nearby networks. Rescans through the root helper when allowed."""
    if rescan:
        helper = _helper()
        if helper.is_file():
            result = _run(["sudo", "-n", str(helper), "scan"], timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                return parse_scan(result.stdout)
    result = _run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list"], timeout=20)
    if result.returncode != 0:
        return []
    return parse_scan(result.stdout)


def device_status() -> list[dict[str, str]]:
    """Wi-Fi and Ethernet devices with state, connection name, and IPv4."""
    result = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
    rows: list[dict[str, str]] = []
    if result.returncode != 0:
        return rows
    for line in result.stdout.splitlines():
        parts = split_terse(line)
        if len(parts) < 4 or parts[1] not in ("wifi", "ethernet"):
            continue
        row = {"device": parts[0], "type": parts[1], "state": parts[2], "connection": parts[3], "ip": ""}
        if parts[2].startswith("connected"):
            shown = _run(["nmcli", "-g", "IP4.ADDRESS", "device", "show", parts[0]])
            if shown.returncode == 0:
                first = shown.stdout.strip().split("|")[0].strip()
                row["ip"] = first.split("/")[0]
        rows.append(row)
    return rows


def validate_wifi(ssid: str, password: str) -> str:
    """Return an error message, or '' when the values can be sent to nmcli.

    The SSID is checked exactly as typed or picked: leading and trailing
    spaces are part of a network name ("Home Net ") and are never stripped.
    """
    if not ssid or len(ssid.encode("utf-8")) > 32:
        return "Enter the network name (1 to 32 characters)."
    if any(char in ssid for char in "\r\n\x00"):
        return "The network name has a character that is not allowed."
    if any(char in password for char in "\r\n\x00"):
        return "The password has a character that is not allowed."
    if password and not (8 <= len(password) <= 63 or re.fullmatch(r"[0-9A-Fa-f]{64}", password)):
        return "Wi-Fi passwords are 8 to 63 characters. Leave it blank for an open network."
    return ""


def _scrub(text: str, secret: str) -> str:
    cleaned = (text or "").strip()
    if secret:
        cleaned = cleaned.replace(secret, "••••")
    return cleaned


def connect_wifi(ssid: str, password: str, hidden: bool = False, country: str = "") -> tuple[bool, str]:
    """Join a network through the root helper. The password goes on stdin only.

    The helper stops the setup hotspot (and turns off its autoconnect) first,
    then joins ssid exactly as given, spaces included.
    """
    problem = validate_wifi(ssid, password)
    if problem:
        return False, problem
    country = country.strip().upper()
    if country and not COUNTRY_RE.fullmatch(country):
        country = ""
    helper = _helper()
    if not helper.is_file():
        return False, "The Wi-Fi helper is not installed. Run install.sh again."
    data = f"{ssid}\n{password}\n{'yes' if hidden else 'no'}\n{country}\n"
    result = _run_input(["sudo", "-n", str(helper), "connect"], data, timeout=60)
    if result.returncode == 0:
        return True, _scrub(result.stdout, password) or "Connected."
    detail = _scrub(result.stderr or result.stdout, password) or "Could not join that network."
    if "password is required" in detail.lower():
        detail = "This unit is missing its Wi-Fi permission. Run install.sh again."
    return False, detail


def set_country(country: str) -> tuple[bool, str]:
    country = country.strip().upper()
    if not COUNTRY_RE.fullmatch(country):
        return False, "Country must be two letters, like US."
    helper = _helper()
    if not helper.is_file():
        return False, "The Wi-Fi helper is not installed. Run install.sh again."
    result = _run(["sudo", "-n", str(helper), "country", country], timeout=30)
    if result.returncode == 0:
        return True, (result.stdout or f"Wi-Fi country set to {country}.").strip()
    return False, (result.stderr or result.stdout or "Could not set the Wi-Fi country.").strip()


def start_setup_hotspot(hotspot: dict[str, str]) -> tuple[bool, str]:
    """Start the FlightTracker-Setup AP through the root helper.

    Used when WI-FI SETUP is opened and the AP is not already up (saved
    Wi-Fi is down, or no profile exists). The helper takes over wlan0.
    """
    helper = _helper()
    if not helper.is_file():
        return False, "The Wi-Fi helper is not installed. Run install.sh again."
    password = str(hotspot.get("password") or "")
    result = _run(["sudo", "-n", str(helper), "hotspot", HOTSPOT_SSID, password], timeout=60)
    if result.returncode == 0:
        return True, _scrub(result.stdout, password) or "Setup network is up."
    detail = _scrub(result.stderr or result.stdout, password) or "Could not start the setup network."
    if "password is required" in detail.lower():
        detail = "This unit is missing its Wi-Fi permission. Run install.sh again."
    return False, detail


def forget_wifi() -> tuple[bool, str]:
    """Delete saved client Wi-Fi profiles through the root helper.

    The setup hotspot profile is not removed. After this, no saved home
    network remains for NetworkManager or the boot script to retry.
    """
    helper = _helper()
    if not helper.is_file():
        return False, "The Wi-Fi helper is not installed. Run install.sh again."
    result = _run(["sudo", "-n", str(helper), "forget"], timeout=30)
    if result.returncode == 0:
        names = [line for line in (result.stdout or "").splitlines() if line.strip()]
        if names:
            return True, "Forgot " + ", ".join(names) + "."
        return True, "No saved Wi-Fi networks to forget."
    detail = (result.stderr or result.stdout or "Could not forget saved networks.").strip()
    if "password is required" in detail.lower():
        detail = "This unit is missing its Wi-Fi permission. Run install.sh again."
    return False, detail
