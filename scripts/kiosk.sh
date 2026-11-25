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
health_url="${FLIGHT_TRACKER_HEALTH_URL:-http://127.0.0.1:8741/api/health}"
health_wait="${FLIGHT_TRACKER_HEALTH_WAIT:-90}"
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

have_display() {
  [[ -S "${XDG_RUNTIME_DIR}/wayland-0" || -n "${DISPLAY:-}" || -S /tmp/.X11-unix/X0 ]]
}

# If the compositor is not up yet, do not fall through to a missing X11
# display. Exit so systemd can try again once labwc is running.
displayed=0
for _ in $(seq 1 "$wait_seconds"); do
  if have_display; then
    displayed=1
    break
  fi
  sleep 1
done
if [[ "$displayed" -eq 0 ]]; then
  echo "The desktop session is not up yet." >&2
  exit 1
fi

# After a power loss Chromium can refuse to start (stale SingletonLock) or
# show the "Restore pages?" / start page instead of the radar. Clear those.
chrome_config="${XDG_CONFIG_HOME:-$HOME/.config}"
for profile in chromium chromium-browser google-chrome; do
  dir="${chrome_config}/${profile}"
  [[ -d "$dir" ]] || continue
  rm -f "$dir/SingletonLock" "$dir/SingletonSocket" "$dir/SingletonCookie"
  pref="$dir/Default/Preferences"
  if [[ -f "$pref" ]] && command -v python3 >/dev/null 2>&1; then
    python3 - "$pref" << 'PY' || true
import json, os, sys
path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
except Exception:
    sys.exit(0)
profile = data.get("profile")
if not isinstance(profile, dict):
    profile = {}
    data["profile"] = profile
changed = False
if profile.get("exited_cleanly") is not True:
    profile["exited_cleanly"] = True
    changed = True
if profile.get("exit_type") != "Normal":
    profile["exit_type"] = "Normal"
    changed = True
if not changed:
    sys.exit(0)
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as handle:
    json.dump(data, handle)
os.replace(tmp, path)
PY
  fi
done

health_ok() {
  python3 - "$health_url" << 'PY'
import sys, urllib.error, urllib.request
url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=1) as response:
        sys.exit(0 if getattr(response, "status", 200) == 200 else 1)
except Exception:
    sys.exit(1)
PY
}

# Do not open Chromium until the local display server answers. Otherwise it
# stays on "This site can't be reached" (or the desktop) and never reloads.
if [[ "$health_wait" != "0" ]]; then
  healthy=0
  for _ in $(seq 1 "$health_wait"); do
    if health_ok; then
      healthy=1
      break
    fi
    sleep 1
  done
  if [[ "$healthy" -eq 0 ]]; then
    # 1.0.16 exited here, so Chromium never opened and the panel stayed
    # white (compositor/backlight only) after an OTA when /api/health was
    # late or the display server was still waiting for network-online.
    # Open the glass anyway; loadDisplay() retries until the server answers.
    echo "The display server is not answering at ${health_url}; opening the glass anyway so it can retry." >&2
  fi
fi

args=(
  --kiosk
  --noerrdialogs
  --disable-infobars
  --disable-session-crashed-bubble
  --hide-crash-restore-bubble
  --no-first-run
  --no-default-browser-check
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
