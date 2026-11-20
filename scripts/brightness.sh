#!/bin/bash
# Waveshare 4inch DSI LCD (C) wiki, "Adjust Backlight Brightness Using Terminal":
#   echo X | sudo tee /sys/class/backlight/*/brightness
# X is an integer from 0 (darkest) to 255 (brightest).
# The wiki does not name the backlight device, so the published glob is used.
# TODO: the wiki does not say which node to write when more than one
# backlight device is present. This follows the published glob and writes
# every match.
set -euo pipefail
value="${1:-}"
if [[ ! "$value" =~ ^[0-9]+$ ]] || (( value < 0 || value > 255 )); then
  echo "brightness must be 0-255" >&2
  exit 1
fi
shopt -s nullglob
files=(/sys/class/backlight/*/brightness)
if (( ${#files[@]} == 0 )); then
  echo "No /sys/class/backlight/*/brightness node." >&2
  exit 1
fi
echo "$value" | tee "${files[@]}" >/dev/null
