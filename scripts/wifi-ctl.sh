#!/bin/bash
# Privileged NetworkManager helper. The display server runs it with
# `sudo -n /usr/local/sbin/flight-tracker-wifi ...` (see install.sh sudoers).
#
#   scan                 rescan and print `nmcli -t` IN-USE,SSID,SIGNAL,SECURITY rows
#   connect              read four lines on stdin: SSID, password, hidden yes/no,
#                        country code. The password never appears in argv of
#                        sudo, so it is not written to the sudo/auth log.
#   country CC           set the Wi-Fi regulatory country (two letters)
#   hotspot [ssid] [pw] [iface]
#   client-profiles      print saved client (non-hotspot) Wi-Fi profile names
#   boot-hotspot [ssid] [pw] [iface]
#                        start the setup hotspot only when no client Wi-Fi
#                        profile is saved (flight-tracker-wifi.service)
#
# SSIDs are used exactly as given: leading and trailing spaces are part of
# the name ("Home Net " is not "Home Net") and are never trimmed.
#
# Only the Wi-Fi device changes; Ethernet keeps its own connection.
# Unverified on hardware: written for Raspberry Pi OS Trixie NetworkManager.
set -euo pipefail
cmd="${1:-}"
shift || true

set_country() {
  local cc="$1" force="${2:-no}" current=""
  [[ "$cc" =~ ^[A-Z]{2}$ ]] || { echo "Country must be two letters, like US." >&2; return 1; }
  if command -v raspi-config >/dev/null 2>&1; then
    current="$(raspi-config nonint get_wifi_country 2>/dev/null || true)"
    if [[ "$force" == "yes" || -z "$current" ]] && [[ "$current" != "$cc" ]]; then
      raspi-config nonint do_wifi_country "$cc" >/dev/null 2>&1 || true
    fi
  elif command -v iw >/dev/null 2>&1; then
    current="$(iw reg get 2>/dev/null | awk '/^country/{sub(":","",$2); print $2; exit}')"
    if [[ "$force" == "yes" || -z "$current" || "$current" == "00" ]]; then
      iw reg set "$cc" || true
    fi
  fi
  if command -v rfkill >/dev/null 2>&1; then
    rfkill unblock wifi || true
  fi
  if command -v nmcli >/dev/null 2>&1; then
    nmcli radio wifi on >/dev/null 2>&1 || true
  fi
}

HOTSPOT_SSID="FlightTracker-Setup"

# Undo nmcli -t escaping ('\:' and '\\') in one field. Spaces are kept.
nm_unescape() {
  local in="$1" out="" i ch
  for ((i = 0; i < ${#in}; i++)); do
    ch="${in:i:1}"
    if [[ "$ch" == "\\" && $((i + 1)) -lt ${#in} ]]; then
      i=$((i + 1))
      ch="${in:i:1}"
    fi
    out+="$ch"
  done
  printf '%s' "$out"
}

# Saved Wi-Fi profiles, one "mode<US>name" row each (US = \x1f, which is not
# whitespace, so a blank mode and the spaces in a name both survive `read`).
# mode is "ap" for a hotspot profile, "infrastructure" or blank for a client.
SEP=$'\x1f'
wifi_profiles() {
  local line name mode
  while IFS= read -r line; do
    [[ "$line" == *":802-11-wireless" ]] || continue
    name="$(nm_unescape "${line%:802-11-wireless}")"
    mode="$(nmcli -g 802-11-wireless.mode connection show id "$name" 2>/dev/null || true)"
    printf '%s%s%s\n' "$mode" "$SEP" "$name"
  done < <(nmcli -t -f NAME,TYPE connection show 2>/dev/null || true)
}

is_hotspot_profile() {
  local mode="$1" name="$2"
  [[ "$mode" == "ap" || "$name" == "$HOTSPOT_SSID" || "$name" == "Hotspot" ]]
}

client_profiles() {
  local mode name
  while IFS="$SEP" read -r mode name; do
    [[ -n "$name" ]] || continue
    is_hotspot_profile "$mode" "$name" && continue
    printf '%s\n' "$name"
  done < <(wifi_profiles)
}

active_names() {
  local line
  while IFS= read -r line; do
    nm_unescape "$line"
    printf '\n'
  done < <(nmcli -t -f NAME connection show --active 2>/dev/null || true)
}

# Take the setup hotspot down and stop it coming back on its own, so wlan0 is
# free for the client network. Prints the names it took down.
stop_hotspot() {
  local mode name active
  active="$(active_names)"
  while IFS="$SEP" read -r mode name; do
    [[ -n "$name" ]] || continue
    is_hotspot_profile "$mode" "$name" || continue
    nmcli connection modify id "$name" connection.autoconnect no >/dev/null 2>&1 || true
    if grep -Fxq -- "$name" <<<"$active"; then
      if ! nmcli connection down id "$name" >/dev/null 2>&1; then
        echo "Could not stop the setup hotspot ($name)." >&2
      fi
      printf '%s\n' "$name"
    fi
  done < <(wifi_profiles)
}

start_hotspot() {
  local ssid="$1" password="$2" iface="$3"
  if [[ ${#password} -lt 8 ]]; then
    echo "Hotspot password must be at least 8 characters." >&2
    return 1
  fi
  # Name the profile after the SSID (nmcli's default name is "Hotspot") and
  # never autoconnect it: it is only started on purpose.
  nmcli dev wifi hotspot ifname "$iface" con-name "$ssid" ssid "$ssid" password "$password" || \
    nmcli connection up id "$ssid"
  nmcli connection modify id "$ssid" connection.autoconnect no >/dev/null 2>&1 || true
}

case "$cmd" in
  scan)
    if ! nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY dev wifi list --rescan yes 2>/dev/null; then
      nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY dev wifi list --rescan no
    fi
    ;;
  connect)
    ssid=""; password=""; hidden="no"; country=""
    IFS= read -r ssid || true
    IFS= read -r password || true
    IFS= read -r hidden || true
    IFS= read -r country || true
    if [[ -z "$ssid" || ${#ssid} -gt 32 ]]; then
      echo "Enter the network name (1 to 32 characters)." >&2
      exit 1
    fi
    if [[ -n "$password" && ( ${#password} -lt 8 || ${#password} -gt 64 ) ]]; then
      echo "Wi-Fi passwords are 8 to 63 characters." >&2
      exit 1
    fi
    if [[ -n "$country" ]]; then
      set_country "$country" no || true
    fi
    # The setup hotspot holds wlan0; a client connect fails while it is up.
    was_up="$(stop_hotspot || true)"
    if [[ -n "$was_up" ]]; then
      # wlan0 was an access point; give it a fresh scan as a client.
      sleep "${FT_WIFI_SETTLE:-2}"
      nmcli dev wifi list --rescan yes >/dev/null 2>&1 || true
    fi
    args=(--wait 45 dev wifi connect "$ssid")
    if [[ -n "$password" ]]; then
      args+=(password "$password")
    fi
    if [[ "$hidden" == "yes" ]]; then
      args+=(hidden yes)
    fi
    # nmcli prints the SSID and device on success; it does not print the password.
    if ! nmcli "${args[@]}"; then
      echo "Could not join \"$ssid\". Check the name (spaces count) and password." >&2
      if [[ -n "$was_up" ]]; then
        # Put the setup hotspot back so the phone can try again.
        nmcli connection up id "$(head -n 1 <<<"$was_up")" >/dev/null 2>&1 || true
      fi
      exit 1
    fi
    ;;
  country)
    set_country "${1:-}" yes
    echo "Wi-Fi country set to ${1:-}."
    ;;
  hotspot)
    start_hotspot "${1:-$HOTSPOT_SSID}" "${2:-}" "${3:-wlan0}"
    ;;
  client-profiles)
    client_profiles
    ;;
  boot-hotspot)
    # Once any client Wi-Fi profile is saved, NetworkManager owns wlan0: it
    # reconnects on its own. Do not hijack the radio with the hotspot, even
    # when that network is slow to come up after boot.
    known="$(client_profiles)"
    if [[ -n "$known" ]]; then
      stop_hotspot >/dev/null || true
      echo "Wi-Fi profile saved ($(head -n 1 <<<"$known")); not starting the setup hotspot."
      exit 0
    fi
    start_hotspot "${1:-$HOTSPOT_SSID}" "${2:-}" "${3:-wlan0}"
    ;;
  *)
    echo "Use scan, connect, country, hotspot, client-profiles, or boot-hotspot." >&2
    exit 1
    ;;
esac
