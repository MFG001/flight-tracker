#!/bin/bash
# Supervise the FlightTracker-Setup hotspot.
#
# - No saved client Wi-Fi profile: start the hotspot immediately.
# - Saved client profiles: wait about two minutes for a Wi-Fi client
#   connection (Ethernet does not count). If none comes up, start the
#   hotspot, then periodically retry saved networks when no phone is
#   joined and setup is not in progress.
# Saving a network on the setup page still stops the hotspot and joins
# (wifi-ctl.sh connect). The self-reverting test-hotspot command is left
# alone.
# Unverified on hardware: grace and retry intervals; AP/STA switching on
# Raspberry Pi OS Trixie / brcmfmac.
set -euo pipefail
if ! command -v nmcli >/dev/null 2>&1; then
  echo "nmcli is not installed; skipping the setup hotspot." >&2
  exit 0
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
password="$(
  PYTHONPATH="$ROOT/server" FT_HOTSPOT_JSON="${FT_HOTSPOT_JSON:-}" python3 - << 'PY'
from pathlib import Path
import os
from wifi_net import load_hotspot
candidates = []
if os.environ.get("FT_HOTSPOT_JSON"):
    candidates.append(Path(os.environ["FT_HOTSPOT_JSON"]))
candidates.extend((Path("/etc/flight-tracker/hotspot.json"), Path("data/hotspot.json")))
for candidate in candidates:
    if candidate.parent.is_dir() or candidate.is_file():
        print(load_hotspot(candidate)["password"])
        break
PY
)"
exec "$ROOT/scripts/wifi-ctl.sh" boot-hotspot "FlightTracker-Setup" "$password"
