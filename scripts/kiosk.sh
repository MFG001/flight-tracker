#!/bin/bash
# Open Flight Tracker fullscreen on the round display.
# Wayland (Bookworm/Trixie labwc) and X11 are both attempted.
# Pi 4 / Trixie / Waveshare 4inch DSI LCD (C): Chromium drew a plain white
# page with GPU rendering on, so GPU and GPU compositing are off by default.
# Set FLIGHT_TRACKER_GPU=1 to turn them back on.
set -euo pipefail
url="${FLIGHT_TRACKER_URL:-http://127.0.0.1:8741/?kiosk=1}"
config="${FLIGHT_TRACKER_CONFIG:-/etc/flight-tracker/config.json}"
wait_seconds="${FLIGHT_TRACKER_DISPLAY_WAIT:-40}"
uid="$(id -u)"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/${uid}}"
# Chromium logs "Failed to connect to the bus" when no session bus address is
# set. Point it at the user bus when that socket exists.
if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" && -S "${XDG_RUNTIME_DIR}/bus" ]]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
fi

chrome=""
for candidate in chromium chromium-browser chromium-browser-stable google-chrome google-chrome-stable; do
  if command -v "$candidate" >/dev/null 2>&1; then
    chrome="$candidate"
    break
  fi
done
if [[ -z "$chrome" ]]; then
  echo "Chromium is not installed." >&2
  exit 1
fi

for _ in $(seq 1 "$wait_seconds"); do
  if [[ -S "${XDG_RUNTIME_DIR}/wayland-0" || -n "${DISPLAY:-}" || -S /tmp/.X11-unix/X0 ]]; then
    break
  fi
  sleep 1
done

args=(
  --kiosk
  --noerrdialogs
  --disable-infobars
  --disable-session-crashed-bubble
  --disable-features=TranslateUI
  --check-for-update-interval=31536000
  --autoplay-policy=no-user-gesture-required
  --password-store=basic
  --touch-events=enabled
)
if [[ "${FLIGHT_TRACKER_GPU:-0}" != "1" ]]; then
  args+=(--disable-gpu --disable-gpu-compositing)
fi

if [[ -S "${XDG_RUNTIME_DIR}/wayland-0" ]]; then
  export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
  args+=(--ozone-platform=wayland --enable-features=UseOzonePlatform)
  # Rotate the panel (display.rotation, default 270 for the 4inch DSI LCD C).
  # kanshi normally does this at login; this covers a missing kanshi config.
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  if command -v wlr-randr >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
    read -r out_name transform < <(python3 "$here/server/display_setup.py" --config "$config" --print-transform 2>/dev/null || echo "DSI-1 270") || true
    if [[ "$out_name" =~ ^[A-Za-z0-9_.-]+$ && "$transform" =~ ^(normal|90|180|270)$ ]]; then
      wlr-randr --output "$out_name" --transform "$transform" || echo "wlr-randr could not rotate ${out_name}." >&2
    fi
  fi
else
  export DISPLAY="${DISPLAY:-:0}"
  if command -v xset >/dev/null 2>&1; then
    xset s off || true
    xset -dpms || true
    xset s noblank || true
  fi
fi

exec "$chrome" "${args[@]}" "$url"
