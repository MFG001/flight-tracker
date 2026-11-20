#!/bin/bash
# Idempotent Raspberry Pi boot config edits for Flight Tracker.
# Usage: boot-config.sh CONFIG_TXT PANEL(c|touch-c) [FAN_PIN FAN_TEMP_MILLIC]
# Each line is added only when missing, so re-running install.sh never
# duplicates config.txt lines. A first-run backup is kept.
set -euo pipefail
BOOT="$1"
PANEL="${2:-c}"
FAN_PIN="${3:-}"
FAN_TEMP="${4:-}"
[[ -f "$BOOT" ]] || { echo "No boot config at ${BOOT}." >&2; exit 1; }

backup() {
  if [[ ! -f "${BOOT}.bak-flight-tracker" ]]; then
    cp "$BOOT" "${BOOT}.bak-flight-tracker"
  fi
}

if [[ "$PANEL" == "touch-c" ]]; then
  OVERLAY="dtoverlay=vc4-kms-dsi-waveshare-panel-v2,4_0_inch_c"
else
  OVERLAY="dtoverlay=vc4-kms-dsi-waveshare-panel,4_0_inchC"
fi
if grep -q 'vc4-kms-dsi-waveshare-panel' "$BOOT"; then
  echo "A Waveshare DSI overlay is already in ${BOOT}; it was left unchanged."
else
  backup
  printf '\n# Flight Tracker — 4inch DSI LCD (C), Pi 4 DSI port\n%s\n' "$OVERLAY" >> "$BOOT"
  echo "Added ${OVERLAY} to ${BOOT}. Reboot to bring the panel up."
fi
if ! grep -q '^dtoverlay=vc4-kms-v3d' "$BOOT"; then
  backup
  printf '\ndtoverlay=vc4-kms-v3d\n' >> "$BOOT"
fi
if [[ -n "$FAN_PIN" && -n "$FAN_TEMP" ]]; then
  LINE="dtoverlay=gpio-fan,gpiopin=${FAN_PIN},temp=${FAN_TEMP}"
  if grep -q '^dtoverlay=gpio-fan' "$BOOT"; then
    echo "A gpio-fan overlay is already present; it was left unchanged."
  else
    backup
    printf '\n# Flight Tracker cooling fan\n%s\n' "$LINE" >> "$BOOT"
    echo "Added ${LINE}. Reboot so the fan overlay loads."
  fi
fi
