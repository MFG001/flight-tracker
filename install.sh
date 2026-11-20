#!/bin/bash
# One-command install for Flight Tracker on a Raspberry Pi.
# Safe to re-run. On a machine without a Waveshare panel it still installs
# the service and skips boot-config edits.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PANEL="c"
ENABLE_FAN=0
ADMIN_PASSWORD=""

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo bash "$0" "$@"
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --panel)
      PANEL="${2:-}"
      shift 2
      ;;
    --fan)
      ENABLE_FAN=1
      shift
      ;;
    --admin-password)
      ADMIN_PASSWORD="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: sudo bash install.sh [--panel c|touch-c] [--fan] [--admin-password SECRET]" >&2
      exit 1
      ;;
  esac
done

if [[ "$PANEL" != "c" && "$PANEL" != "touch-c" ]]; then
  echo "Panel must be 'c' (4inch DSI LCD C) or 'touch-c' (4-DSI-TOUCH-C)." >&2
  exit 1
fi

if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
  TARGET_USER="$SUDO_USER"
elif id pi >/dev/null 2>&1; then
  TARGET_USER="pi"
else
  TARGET_USER="$(id -un)"
fi
if [[ ! "$TARGET_USER" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
  echo "Refusing unusual account name: $TARGET_USER" >&2
  exit 1
fi
# 1.0.7: the web server runs as its own system account, never the desktop
# login (which keeps the kiosk). It cannot write the code or the update keys.
SERVICE_USER="ft-server"
if [[ "$TARGET_USER" == "$SERVICE_USER" ]]; then
  echo "Run install.sh from the desktop login, not from ${SERVICE_USER}." >&2
  exit 1
fi

if [[ "$PANEL" == "touch-c" ]]; then
  echo "Optional panel: 4-DSI-TOUCH-C. The Pi 4 default is 4inch DSI LCD (C)."
else
  PANEL="c"
  echo "Panel: Waveshare 4inch DSI LCD (C), the Pi 4 default."
fi
echo "Installing Flight Tracker for ${TARGET_USER}"

if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  apt-get install -y python3 ca-certificates fonts-dejavu-core avahi-daemon
  systemctl enable avahi-daemon || true
  systemctl restart avahi-daemon || true
  apt-get install -y chromium || apt-get install -y chromium-browser || echo "Chromium was not installed; kiosk mode needs it."
  apt-get install -y python3-gpiozero || echo "python3-gpiozero is unavailable; GPIO stays off until it is installed."
  # wlr-randr rotates the panel from kiosk.sh; Raspberry Pi OS desktop ships it.
  apt-get install -y wlr-randr || echo "wlr-randr is unavailable; kanshi still applies the rotation at login."
fi

if [[ ! -f "$ROOT/dist/index.html" ]]; then
  if command -v npm >/dev/null 2>&1; then
    (cd "$ROOT" && npm install && npm run build)
  else
    echo "dist/index.html is missing and npm is not available." >&2
    exit 1
  fi
fi

VER="$(tr -d '[:space:]' < "$ROOT/VERSION")"
if [[ ! "$VER" =~ ^[0-9]+(\.[0-9]+){1,3}$ ]]; then
  echo "VERSION must look like 1.2.3 (found: ${VER})." >&2
  exit 1
fi
REL="/opt/flight-tracker/releases/${VER}"
install -d "$REL" /etc/flight-tracker /var/cache/flight-tracker
# Copy only the files that make up a release. The tarball unpacks loose into
# whatever folder it is extracted in (often the home folder), so copying the
# whole folder would also copy ~/.ssh, ~/.config, ~/Downloads, and old
# tarballs into /opt (1.0.0/1.0.1 did that).
RELEASE_ITEMS=(VERSION LICENSE THIRD_PARTY_NOTICES.md README.md index.html install.sh package.json package-lock.json
  tsconfig.json vite.config.ts .gitignore data deploy dist docs scripts server setup src tools)
rm -rf "${REL}.partial"
install -d "${REL}.partial"
for item in "${RELEASE_ITEMS[@]}"; do
  if [[ -e "$ROOT/$item" ]]; then
    tar -C "$ROOT" \
      --exclude '__pycache__' \
      --exclude 'node_modules' \
      --exclude 'data/cache' \
      --exclude 'data/config.json' \
      --exclude 'data/auth.json' \
      --exclude 'data/hotspot.json' \
      --exclude 'data/update-token' \
      --exclude '*.key' \
      -cf - "$item" | tar -C "${REL}.partial" -xf -
  fi
done
if [[ "$(readlink -f /opt/flight-tracker/current 2>/dev/null || true)" == "$(readlink -f "$REL")" ]]; then
  # Re-running the same version: swap the folder under the live link.
  rm -rf "${REL}.old"
  mv "$REL" "${REL}.old"
  mv "${REL}.partial" "$REL"
  rm -rf "${REL}.old"
else
  rm -rf "$REL"
  mv "${REL}.partial" "$REL"
fi
ln -sfn "releases/${VER}" /opt/flight-tracker/current

if [[ ! -f /etc/flight-tracker/config.json ]]; then
  install -m 0644 "$ROOT/data/config.example.json" /etc/flight-tracker/config.json
else
  # Bring an existing config up to this release (1.0.2: sweep 4 s -> 8 s,
  # weather on, display.rotation and wifi.country defaults). Keeps a backup.
  cp -p /etc/flight-tracker/config.json /etc/flight-tracker/config.json.pre-install
  python3 "$REL/server/migrate.py" --config /etc/flight-tracker/config.json --no-system || \
    echo "Config migration failed; the server migrates it on start instead."
fi

FLIGHT_TRACKER_ADMIN_PASSWORD="$ADMIN_PASSWORD" python3 - << 'PY'
import hashlib, json, os
from pathlib import Path
auth = Path("/etc/flight-tracker/auth.json")
password = os.environ.get("FLIGHT_TRACKER_ADMIN_PASSWORD", "")
if not password and auth.is_file():
    # Re-running install.sh keeps an existing setup-page password.
    print("Left the setup page password setting unchanged.")
elif password:
    salt = __import__("secrets").token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt) if False else salt.encode(), 120000).hex()
    auth.write_text(json.dumps({"salt": salt, "hash": digest}, indent=2) + "\n")
    print("Admin password enabled for the setup page.")
else:
    auth.write_text("{}\n")
    print("Setup page password is off.")
PY
chmod 0600 /etc/flight-tracker/auth.json

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --user-group --no-create-home --home-dir /var/lib/flight-tracker \
    --shell /usr/sbin/nologin "$SERVICE_USER"
  echo "Created the ${SERVICE_USER} service account."
fi
for group in video gpio i2c spi; do
  if getent group "$group" >/dev/null; then
    usermod -aG "$group" "$SERVICE_USER" || true
  fi
done
install -d -m 0755 -o root -g root /var/lib/flight-tracker /etc/flight-tracker-keys

if [[ ! -f /etc/flight-tracker/update-public.pem ]]; then
  install -m 0644 "$ROOT/deploy/update-public.pem" /etc/flight-tracker/update-public.pem
  echo "Baked in deploy/update-public.pem."
  echo "The private key stays off the Pi. Later updates are checked against this copy, not against a key shipped in a release."
else
  echo "Left the existing update public key in place."
fi

if [[ "$ENABLE_FAN" -eq 1 ]]; then
  python3 - << 'PY'
import json
from pathlib import Path
path = Path("/etc/flight-tracker/config.json")
cfg = json.loads(path.read_text())
cfg.setdefault("fan", {})["gpioControl"] = True
path.write_text(json.dumps(cfg, indent=2) + "\n")
PY
fi

# Pin the update key in the root-owned key folder (first install or a 1.0.6 unit).
if ! compgen -G "/etc/flight-tracker-keys/*.pem" >/dev/null; then
  KID="$(openssl pkey -pubin -in /etc/flight-tracker/update-public.pem -outform DER | sha256sum | cut -d' ' -f1)"
  install -m 0644 -o root -g root /etc/flight-tracker/update-public.pem "/etc/flight-tracker-keys/release-${KID}.pem"
  echo "Pinned update key ${KID:0:4} ${KID:4:4} ${KID:8:4} ${KID:12:4} in /etc/flight-tracker-keys."
fi
# Code is root's; config and cache are the server account's (the kiosk can still read the config).
chown -R root:root /opt/flight-tracker
chmod -R go-w /opt/flight-tracker
chown -R "$SERVICE_USER:$SERVICE_USER" /var/cache/flight-tracker /etc/flight-tracker
chmod 0755 /etc/flight-tracker
chown root:root /etc/flight-tracker/update-public.pem
chmod 0644 /etc/flight-tracker/update-public.pem
# 1.0.7 is tokenless: an access key saved by 1.0.0-1.0.6 is no longer needed.
rm -f /etc/flight-tracker/update-token
chmod 0755 \
  "/opt/flight-tracker/current/scripts/kiosk.sh" \
  "/opt/flight-tracker/current/scripts/brightness.sh" \
  "/opt/flight-tracker/current/scripts/wifi-ctl.sh" \
  "/opt/flight-tracker/current/scripts/wifi-setup.sh" \
  "/opt/flight-tracker/current/install.sh" \
  "/opt/flight-tracker/current/server/updater.py" \
  "/opt/flight-tracker/current/scripts/release.py"
install -d /usr/local/sbin
install -m 0755 "$ROOT/deploy/flight-tracker-brightness" /usr/local/sbin/flight-tracker-brightness
install -m 0755 "$ROOT/deploy/flight-tracker-wifi" /usr/local/sbin/flight-tracker-wifi
install -m 0755 "$ROOT/deploy/flight-tracker-update" /usr/local/sbin/flight-tracker-update

if getent group video >/dev/null; then
  usermod -aG video "$TARGET_USER" || true
fi

SUDOERS=/etc/sudoers.d/flight-tracker-brightness
cat > "$SUDOERS" << EOF
${SERVICE_USER} ALL=(root) NOPASSWD: /usr/local/sbin/flight-tracker-brightness
${SERVICE_USER} ALL=(root) NOPASSWD: /usr/local/sbin/flight-tracker-wifi
${SERVICE_USER} ALL=(root) NOPASSWD: /usr/local/sbin/flight-tracker-update
${SERVICE_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl restart flight-tracker-kiosk.service
EOF
chmod 0440 "$SUDOERS"
if command -v visudo >/dev/null 2>&1; then
  visudo -cf "$SUDOERS"
fi

sed "s/@USER@/${SERVICE_USER}/g" /opt/flight-tracker/current/deploy/flight-tracker.service > /etc/systemd/system/flight-tracker.service
# The unit names the service account itself; the --harden drop-in is not needed.
rm -f /etc/systemd/system/flight-tracker.service.d/10-service-account.conf
printf '{"user": "%s", "previous": "%s", "how": "install.sh"}\n' "$SERVICE_USER" "$TARGET_USER" > /var/lib/flight-tracker/service-account.json
sed "s/@USER@/${TARGET_USER}/g" /opt/flight-tracker/current/deploy/flight-tracker-kiosk.service > /etc/systemd/system/flight-tracker-kiosk.service
install -m 0644 /opt/flight-tracker/current/deploy/flight-tracker-update.service /etc/systemd/system/flight-tracker-update.service
install -m 0644 /opt/flight-tracker/current/deploy/flight-tracker-update.timer /etc/systemd/system/flight-tracker-update.timer
install -m 0644 /opt/flight-tracker/current/deploy/flight-tracker-wifi.service /etc/systemd/system/flight-tracker-wifi.service

BOOT=""
if [[ -f /boot/firmware/config.txt ]]; then
  BOOT=/boot/firmware/config.txt
elif [[ -f /boot/config.txt ]]; then
  BOOT=/boot/config.txt
fi

if [[ -n "$BOOT" ]]; then
  # Pi 4 default: Waveshare 4inch DSI LCD (C).
  # Bookworm/Trixie wiki: dtoverlay=vc4-kms-v3d and
  # dtoverlay=vc4-kms-dsi-waveshare-panel,4_0_inchC
  # Pi 4 has one DSI port (15-pin FPC). The wiki's ,dsi0 form is only for
  # boards with two MIPI ports, so it is not written here.
  # Touch: the same page says touch works after that overlay. It does not
  # add a separate touch dtoverlay on Bookworm/Trixie. The rotation steps
  # name the device "10-0014 Goodix Capacitive TouchScreen".
  # TODO: Bullseye/Buster use a different driver (WS_xinchDSI_MAIN.sh 40C I2C0,
  # or WS_xinchDSI_Touch). The wiki's preinstalled snippet also shows
  # I2C_bus=10. Those are not installed automatically.
  FAN_ON="$(python3 -c 'import json; print(json.load(open("/etc/flight-tracker/config.json"))["fan"]["gpioControl"])')"
  if [[ "$FAN_ON" == "True" ]]; then
    PIN="$(python3 -c 'import json; print(int(json.load(open("/etc/flight-tracker/config.json"))["fan"]["gpio"]))')"
    TEMP="$(python3 -c 'import json; print(int(json.load(open("/etc/flight-tracker/config.json"))["fan"]["onTempC"]) * 1000)')"
    bash "$REL/scripts/boot-config.sh" "$BOOT" "$PANEL" "$PIN" "$TEMP"
  else
    bash "$REL/scripts/boot-config.sh" "$BOOT" "$PANEL"
  fi
else
  echo "No Raspberry Pi boot config found. Display and fan overlays were not written."
fi

if [[ -f /proc/device-tree/model ]] && tr -d '\0' < /proc/device-tree/model | grep -q Raspberry; then
  hostnamectl set-hostname flighttracker
  if ! grep -q '[[:space:]]flighttracker$' /etc/hosts; then
    echo "127.0.1.1 flighttracker" >> /etc/hosts
  fi
  echo "Hostname set to flighttracker. Avahi publishes flighttracker.local."
else
  echo "Not a Raspberry Pi. Hostname was left unchanged. On the Pi it becomes flighttracker.local."
fi

# Panel rotation (display.rotation, default 270) and touch mapping for the
# desktop user: ~/.config/kanshi/config and ~/.config/labwc/rc.xml.
if [[ -f "$REL/server/display_setup.py" ]]; then
  python3 "$REL/server/display_setup.py" --config /etc/flight-tracker/config.json --user "$TARGET_USER" || \
    echo "Display rotation setup failed; kiosk.sh still rotates with wlr-randr."
fi

# Wi-Fi country: Raspberry Pi OS keeps Wi-Fi blocked until one is set. Set it
# from wifi.country (default US) only when none is set, so an Imager choice stays.
WIFI_COUNTRY="$(python3 -c 'import json; print(str((json.load(open("/etc/flight-tracker/config.json")).get("wifi") or {}).get("country") or "US").upper())' 2>/dev/null || echo US)"
if [[ "$WIFI_COUNTRY" =~ ^[A-Z]{2}$ ]] && command -v raspi-config >/dev/null 2>&1; then
  if [[ -z "$(raspi-config nonint get_wifi_country 2>/dev/null || true)" ]]; then
    raspi-config nonint do_wifi_country "$WIFI_COUNTRY" >/dev/null 2>&1 && echo "Wi-Fi country set to ${WIFI_COUNTRY}." || true
  fi
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload
  systemctl enable flight-tracker.service
  systemctl restart flight-tracker.service || true
  systemctl enable flight-tracker-kiosk.service || true
  systemctl restart flight-tracker-kiosk.service || true
  systemctl enable flight-tracker-wifi.service || true
  systemctl restart flight-tracker-wifi.service || true
  systemctl enable flight-tracker-update.timer || true
  systemctl restart flight-tracker-update.timer || true
else
  echo "systemd is not available; start the server with: python3 /opt/flight-tracker/current/server/flighttracker.py"
fi

echo "Flight Tracker ${VER} is installed."
echo "Reboot once (sudo reboot) so the screen rotation and touch mapping load at login."
echo "Setup page: http://flighttracker.local/    Config: /etc/flight-tracker/config.json"
echo "Backlight follows the 4inch DSI LCD (C) wiki: echo N | sudo tee /sys/class/backlight/*/brightness"
