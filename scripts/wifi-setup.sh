#!/bin/bash
# Start the setup hotspot only on a unit with no saved Wi-Fi network.
# Once any client Wi-Fi profile exists (for example "Home Net "),
# NetworkManager reconnects to it by itself and this script leaves wlan0
# alone, even if that network is slow to come up after boot (1.0.3 fix: the
# hotspot used to take wlan0 whenever Wi-Fi was not up yet).
# TODO: not tested on a Raspberry Pi. NetworkManager's shared mode usually
# gives this machine 10.42.0.1; confirm that address before relying on it.
set -euo pipefail
if ! command -v nmcli >/dev/null 2>&1; then
  echo "nmcli is not installed; skipping the setup hotspot." >&2
  exit 0
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
known="$("$ROOT/scripts/wifi-ctl.sh" client-profiles || true)"
if [[ -n "$known" ]]; then
  "$ROOT/scripts/wifi-ctl.sh" boot-hotspot
  exit 0
fi
password="$(PYTHONPATH="$ROOT/server" python3 - << 'PY'
from pathlib import Path
from wifi_net import load_hotspot
for candidate in (Path("/etc/flight-tracker/hotspot.json"), Path("data/hotspot.json")):
    if candidate.parent.is_dir() or candidate.is_file():
        print(load_hotspot(candidate)["password"])
        break
PY
)"
exec "$ROOT/scripts/wifi-ctl.sh" boot-hotspot "FlightTracker-Setup" "$password"
