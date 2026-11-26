#!/bin/bash
# Waveshare 4inch DSI LCD (C) wiki, "Adjust Backlight Brightness Using Terminal":
#   echo X | sudo tee /sys/class/backlight/*/brightness
# X is an integer from 0 (darkest) to 255 (brightest).
# Each node is scaled to its own max_brightness and written independently.
set -euo pipefail
value="${1:-}"
if [[ ! "$value" =~ ^[0-9]+$ ]] || (( value < 0 || value > 255 )); then
  echo "brightness must be 0-255" >&2
  exit 1
fi
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$here/server/backlight.py" --value "$value"
