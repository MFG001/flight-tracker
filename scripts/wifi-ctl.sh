#!/bin/bash
# Privileged NetworkManager helper. The display server runs it with
# `sudo -n /usr/local/sbin/flight-tracker-wifi ...` (see install.sh sudoers).
#
#   scan                 rescan and print `nmcli -t` IN-USE,SSID,SIGNAL,SECURITY rows
#   connect              read four lines on stdin: SSID, password, hidden yes/no,
#                        country code. The password never appears in argv of
#                        sudo, so it is not written to the sudo/auth log.
#                        After a successful join, this network is preferred
#                        (autoconnect-priority 100). Other saved client
#                        profiles stay autoconnect-yes at a lower priority
#                        so the unit can join home or shop when in range.
#   saved                print saved client profiles (uuid, name, ssid,
#                        active, autoconnect, priority). Never prints secrets.
#   forget               delete all saved client (non-hotspot) profiles
#   forget uuid|id REF   delete one saved client profile
#   prefer uuid|id REF   make one saved client profile preferred
#   password uuid|id REF
#                        set that profile's PSK (password on stdin only).
#                        If it is the connected network, reconnect.
#   country CC           set the Wi-Fi regulatory country (two letters)
#   hotspot [ssid] [pw] [iface]
#   client-profiles      print saved client (non-hotspot) Wi-Fi profile names
#   boot-hotspot [ssid] [pw] [iface]
#                        start the setup hotspot when no client Wi-Fi
#                        profile is saved, or when saved profiles exist but
#                        none connects within a grace period (~2 minutes).
#                        Ethernet does not count. The setup AP then stays
#                        up (no retry loop that tears it down).
#   test-hotspot [minutes]
#                        brief, self-reverting setup-hotspot test (default 10,
#                        max 30). Records the active client profile exactly,
#                        runs under systemd so SSH can drop, then restores
#                        that profile. --stop ends the test early.
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
  harden_hotspot_security "$ssid"
}

# Force WPA2-PSK (RSN, CCMP) and PMF not required. iPhones can fail to join
# when NetworkManager's `dev wifi hotspot` on Raspberry Pi OS Trixie / brcmfmac
# asks for WPA3 or requires PMF.
# Unverified on hardware: settings and whether the connection must be brought
# up again for the AP to apply them were not confirmed on a Pi.
harden_hotspot_security() {
  local ssid="$1"
  nmcli connection modify id "$ssid" \
    connection.autoconnect no \
    ipv4.method shared \
    ipv4.addresses 10.42.0.1/24 \
    802-11-wireless-security.key-mgmt wpa-psk \
    802-11-wireless-security.proto rsn \
    802-11-wireless-security.pairwise ccmp \
    802-11-wireless-security.group ccmp \
    802-11-wireless-security.pmf disable >/dev/null 2>&1 || \
    nmcli connection modify id "$ssid" connection.autoconnect no >/dev/null 2>&1 || true
  nmcli connection up id "$ssid" >/dev/null 2>&1 || true
}

client_wifi_connected() {
  active_client_profile >/dev/null 2>&1
}

# Associated stations on the setup AP. If `iw` is missing, treat as busy so
# a retry does not tear the hotspot down when we cannot tell.
# Unverified on hardware: `iw dev wlan0 station dump` on brcmfmac.
hotspot_station_count() {
  local iface="${FT_WIFI_IFACE:-wlan0}" out
  if ! command -v iw >/dev/null 2>&1; then
    printf '%s\n' "-1"
    return 0
  fi
  out="$(iw dev "$iface" station dump 2>/dev/null)" || { printf '%s\n' "-1"; return 0; }
  printf '%s\n' "$(grep -c '^Station ' <<<"$out" || true)"
}

wifi_test_running() {
  local dir
  dir="$(test_dir)"
  [[ -f "$dir/running" ]]
}

# True when dropping the hotspot would kick a phone or interrupt setup.
hotspot_busy() {
  local count
  wifi_test_running && return 0
  [[ -f "${FT_WIFI_CONNECTING:-/run/flight-tracker-wifi/connecting}" ]] && return 0
  count="$(hotspot_station_count)"
  # -1 means we could not query stations; do not drop the AP.
  [[ "$count" != "0" ]]
}

# Active connection UUIDs, one per line (unescaped).
active_uuids() {
  local line
  while IFS= read -r line; do
    nm_unescape "$line"
    printf '\n'
  done < <(nmcli -t -f UUID connection show --active 2>/dev/null || true)
}

# Wi-Fi connections as "uuid<US>name". NAME is last so it may contain colons.
wifi_connection_ids() {
  local line uuid typ name
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    uuid="$(nm_unescape "${line%%:*}")"
    typ="${line#*:}"
    name="$(nm_unescape "${typ#*:}")"
    typ="$(nm_unescape "${typ%%:*}")"
    [[ "$typ" == "802-11-wireless" ]] || continue
    printf '%s%s%s\n' "$uuid" "$SEP" "$name"
  done < <(nmcli -t -f UUID,TYPE,NAME connection show 2>/dev/null || true)
}

profile_mode() {
  nmcli -g 802-11-wireless.mode connection show uuid "$1" 2>/dev/null || true
}

profile_ssid() {
  nmcli -g 802-11-wireless.ssid connection show uuid "$1" 2>/dev/null || true
}

# Resolve uuid|id to "uuid<US>name". Refuses the setup AP. The id value is
# used exactly as given (spaces, including trailing spaces, are kept).
resolve_client() {
  local kind="$1" value="$2" uuid name mode
  if [[ -z "$value" ]]; then
    echo "Say which saved network." >&2
    return 1
  fi
  if [[ "$kind" == "uuid" ]]; then
    if [[ ! "$value" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
      echo "That saved network id is not valid." >&2
      return 1
    fi
    uuid="$value"
    name="$(nmcli -g connection.id connection show uuid "$uuid" 2>/dev/null || true)"
    if [[ -z "$name" ]]; then
      echo "That saved network was not found." >&2
      return 1
    fi
  elif [[ "$kind" == "id" ]]; then
    name="$value"
    uuid="$(nmcli -g connection.uuid connection show id "$name" 2>/dev/null || true)"
    if [[ -z "$uuid" ]]; then
      echo "That saved network was not found." >&2
      return 1
    fi
  else
    echo "Say which saved network." >&2
    return 1
  fi
  mode="$(profile_mode "$uuid")"
  if is_hotspot_profile "$mode" "$name"; then
    echo "The setup network cannot be changed this way." >&2
    return 1
  fi
  printf '%s%s%s\n' "$uuid" "$SEP" "$name"
}

# Mark the given client UUIDs preferred (autoconnect yes, priority 100).
# Every other client profile stays autoconnect-yes so known networks at
# another location still join automatically; a priority of 100 or more is
# lowered so the preferred network wins when more than one is in range.
set_preferred_uuids() {
  local uuid name mode prio pref
  declare -A want=()
  for pref in "$@"; do
    [[ -n "$pref" ]] || continue
    want["$pref"]=1
  done
  if [[ ${#want[@]} -eq 0 ]]; then
    return 0
  fi
  while IFS="$SEP" read -r uuid name; do
    [[ -n "$uuid" ]] || continue
    mode="$(profile_mode "$uuid")"
    is_hotspot_profile "$mode" "$name" && continue
    if [[ -n "${want[$uuid]:-}" ]]; then
      nmcli connection modify uuid "$uuid" \
        connection.autoconnect yes \
        connection.autoconnect-priority 100 >/dev/null 2>&1 || true
    else
      prio="$(nmcli -g connection.autoconnect-priority connection show uuid "$uuid" 2>/dev/null || true)"
      prio="${prio:-0}"
      [[ "$prio" =~ ^-?[0-9]+$ ]] || prio=0
      if (( prio >= 100 )); then
        nmcli connection modify uuid "$uuid" \
          connection.autoconnect yes \
          connection.autoconnect-priority 50 >/dev/null 2>&1 || true
      else
        nmcli connection modify uuid "$uuid" connection.autoconnect yes >/dev/null 2>&1 || true
      fi
    fi
  done < <(wifi_connection_ids)
}

# After a successful join, prefer this SSID. Other saved client profiles
# keep autoconnect on, at a lower priority. Match on the wireless SSID,
# including any spaces, not only the NetworkManager connection name.
promote_client_network() {
  local ssid="$1" uuid name mode prof_ssid
  local -a matches=()
  while IFS="$SEP" read -r uuid name; do
    [[ -n "$uuid" ]] || continue
    mode="$(profile_mode "$uuid")"
    is_hotspot_profile "$mode" "$name" && continue
    prof_ssid="$(profile_ssid "$uuid")"
    if [[ "$prof_ssid" == "$ssid" ]]; then
      matches+=("$uuid")
    fi
  done < <(wifi_connection_ids)
  set_preferred_uuids "${matches[@]}"
}

# Saved client rows: uuid, name, ssid, active, autoconnect, priority.
# Secrets (psk and so on) are never queried or printed.
saved_client_profiles() {
  local uuid name mode ssid auto prio active_list active
  active_list="$(active_uuids)"
  while IFS="$SEP" read -r uuid name; do
    [[ -n "$uuid" ]] || continue
    mode="$(profile_mode "$uuid")"
    is_hotspot_profile "$mode" "$name" && continue
    ssid="$(profile_ssid "$uuid")"
    [[ -n "$ssid" ]] || ssid="$name"
    auto="$(nmcli -g connection.autoconnect connection show uuid "$uuid" 2>/dev/null || true)"
    prio="$(nmcli -g connection.autoconnect-priority connection show uuid "$uuid" 2>/dev/null || true)"
    prio="${prio:-0}"
    active=no
    if grep -Fxq -- "$uuid" <<<"$active_list"; then
      active=yes
    fi
    printf '%s%s%s%s%s%s%s%s%s%s%s\n' "$uuid" "$SEP" "$name" "$SEP" "$ssid" "$SEP" "$active" "$SEP" "${auto:-no}" "$SEP" "$prio"
  done < <(wifi_connection_ids)
}

forget_one_client() {
  local kind="$1" value="$2" uuid name
  IFS="$SEP" read -r uuid name < <(resolve_client "$kind" "$value") || return 1
  if nmcli connection delete uuid "$uuid" >/dev/null 2>&1; then
    printf '%s\n' "$name"
    return 0
  fi
  echo "Could not forget that saved network." >&2
  return 1
}

prefer_one_client() {
  local kind="$1" value="$2" uuid name
  IFS="$SEP" read -r uuid name < <(resolve_client "$kind" "$value") || return 1
  set_preferred_uuids "$uuid"
  echo "Preferred $name."
}

# The new password is read from stdin only, never from argv, and is never
# printed. The existing PSK is never read back. On a reconnect failure the
# profile (and the new PSK) is kept so the user can try again.
set_client_password() {
  local kind="$1" value="$2" password="" uuid name active_list
  IFS= read -r password || true
  if [[ -z "$password" || ${#password} -lt 8 || ${#password} -gt 64 ]]; then
    echo "Wi-Fi passwords are 8 to 63 characters." >&2
    return 1
  fi
  IFS="$SEP" read -r uuid name < <(resolve_client "$kind" "$value") || return 1
  if ! nmcli connection modify uuid "$uuid" \
      802-11-wireless-security.key-mgmt wpa-psk \
      802-11-wireless-security.psk "$password" >/dev/null 2>&1; then
    echo "Could not update the saved password." >&2
    return 1
  fi
  active_list="$(active_uuids)"
  if grep -Fxq -- "$uuid" <<<"$active_list"; then
    if nmcli --wait 45 connection up uuid "$uuid" >/dev/null 2>&1; then
      echo "Password updated and reconnected."
      return 0
    fi
    echo "Password was saved, but the unit could not reconnect. Check the password and try again." >&2
    return 1
  fi
  echo "Password updated."
}


# Remove saved client networks so the unit stops retrying them. The setup
# hotspot profile is left alone. Prints the names it deleted.
forget_client_profiles() {
  local mode name
  while IFS="$SEP" read -r mode name; do
    [[ -n "$name" ]] || continue
    is_hotspot_profile "$mode" "$name" && continue
    if nmcli connection delete id "$name" >/dev/null 2>&1; then
      printf '%s\n' "$name"
    fi
  done < <(wifi_profiles)
}

wait_for_client_wifi() {
  local seconds="$1"
  local start now
  start="$(date +%s)"
  while true; do
    client_wifi_connected && return 0
    now="$(date +%s)"
    (( now - start >= seconds )) && return 1
    sleep "${FT_WIFI_POLL:-2}"
  done
}

# Brief attempt to join a saved client profile. Caller must have already
# confirmed the hotspot is not busy. Returns 0 if a saved network is up.
# Unverified on hardware: stopping the AP, scanning, and bringing a saved
# profile up on the same brcmfmac radio.
try_saved_networks() {
  local profile
  stop_hotspot >/dev/null || true
  sleep "${FT_WIFI_SETTLE:-2}"
  nmcli dev wifi list --rescan yes >/dev/null 2>&1 || true
  while IFS= read -r profile; do
    [[ -n "$profile" ]] || continue
    if nmcli connection up id "$profile" >/dev/null 2>&1; then
      if grep -Fxq -- "$profile" <<<"$(active_names)"; then
        echo "Joined saved Wi-Fi ($profile)."
        return 0
      fi
    fi
  done < <(client_profiles)
  return 1
}

# Saved profiles: wait ~2 minutes for a Wi-Fi client connection (Ethernet
# does not count), then start the setup hotspot and retry saved networks
# every few minutes unless a phone is joined or setup/test is in progress.
# No saved profile: start the hotspot immediately and return (same as 1.0.13).
# Unverified on hardware: grace and retry intervals; AP/STA switching.
boot_hotspot_cmd() {
  local ssid="${1:-$HOTSPOT_SSID}" password="${2:-}" iface="${3:-${FT_WIFI_IFACE:-wlan0}}"
  local grace retry_every known attempts
  grace="${FT_WIFI_GRACE_SECONDS:-120}"
  retry_every="${FT_WIFI_RETRY_SECONDS:-180}"

  if wifi_test_running; then
    echo "A Wi-Fi test is running; not changing the setup hotspot."
    return 0
  fi

  if [[ -z "$password" ]]; then
    password="$(hotspot_password)" || { echo "Could not read the setup hotspot password." >&2; return 1; }
  fi

  known="$(client_profiles)"
  if [[ -z "$known" ]]; then
    start_hotspot "$ssid" "$password" "$iface"
    echo "Started the setup hotspot (no saved Wi-Fi profile)."
    return 0
  fi

  if wait_for_client_wifi "$grace"; then
    echo "Connected to saved Wi-Fi ($(active_client_profile)); not starting the setup hotspot."
    return 0
  fi

  start_hotspot "$ssid" "$password" "$iface"
  echo "No saved Wi-Fi came up; started the setup hotspot."
  # Do not periodically stop the AP to retry a failing saved profile.
  # That loop (every ~3 minutes in 1.0.14-1.0.17) made the setup network
  # disappear and look like the unit was "still trying the old Wi-Fi".
  # Saved profiles stay on disk; a later reboot still waits the grace
  # period and will join if the network is valid again.
  return 0
}


test_log() {
  logger -t flight-tracker-wifi-test -- "$*" 2>/dev/null || true
  printf '%s\n' "$*"
}

# Currently active client (non-hotspot) Wi-Fi profile, name exactly as saved.
active_client_profile() {
  local active name mode
  active="$(active_names)"
  while IFS="$SEP" read -r mode name; do
    [[ -n "$name" ]] || continue
    is_hotspot_profile "$mode" "$name" && continue
    if grep -Fxq -- "$name" <<<"$active"; then
      printf '%s\n' "$name"
      return 0
    fi
  done < <(wifi_profiles)
  return 1
}

hotspot_password() {
  local server
  server="${FT_SERVER_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../server" && pwd)}"
  FT_SERVER_DIR="$server" FT_HOTSPOT_JSON="${FT_HOTSPOT_JSON:-/etc/flight-tracker/hotspot.json}" \
    python3 -c 'import os, sys
from pathlib import Path
sys.path.insert(0, os.environ["FT_SERVER_DIR"])
from wifi_net import load_hotspot
print(load_hotspot(Path(os.environ["FT_HOTSPOT_JSON"]))["password"], end="")'
}

test_dir() {
  printf '%s' "${FT_WIFI_TEST_DIR:-/run/flight-tracker-wifi-test}"
}

restore_client_profile() {
  local profile="$1" dir="$2"
  local i sleep_s="${FT_WIFI_TEST_RETRY_SLEEP:-2}"
  test_log "Taking the setup hotspot down and bringing the original Wi-Fi profile back."
  stop_hotspot >/dev/null || true
  if [[ -z "$profile" ]]; then
    test_log "No original Wi-Fi profile was recorded."
    rm -f "$dir/running" "$dir/stop" "$dir/portal-saved"
    return 1
  fi
  for i in 1 2 3 4 5; do
    if nmcli connection up id "$profile" >/dev/null 2>&1; then
      if grep -Fxq -- "$profile" <<<"$(active_names)"; then
        test_log "Restored the original Wi-Fi profile."
        rm -f "$dir/running" "$dir/stop" "$dir/portal-saved"
        return 0
      fi
    fi
    sleep "$sleep_s"
  done
  test_log "Could not restore the original Wi-Fi profile. NetworkManager should reconnect it on its own. If it does not, wait, then power-cycle the Pi."
  rm -f "$dir/running" "$dir/stop" "$dir/portal-saved"
  return 1
}

hotspot_is_up() {
  local active
  active="$(active_names)"
  grep -Fxq -- "$HOTSPOT_SSID" <<<"$active" || grep -Fxq -- "Hotspot" <<<"$active"
}

portal_saved_network() {
  local dir="$1" active name mode
  [[ -f "$dir/portal-saved" ]] && return 0
  hotspot_is_up && return 1
  active="$(active_names)"
  while IFS="$SEP" read -r mode name; do
    [[ -n "$name" ]] || continue
    is_hotspot_profile "$mode" "$name" && continue
    if grep -Fxq -- "$name" <<<"$active"; then
      return 0
    fi
  done < <(wifi_profiles)
  return 1
}

test_hotspot_stop() {
  local dir profile
  dir="$(test_dir)"
  mkdir -p "$dir"
  : > "$dir/stop"
  if command -v systemctl >/dev/null 2>&1; then
    systemctl stop flight-tracker-wifi-test >/dev/null 2>&1 || true
  fi
  # If no supervised loop is running, revert from the recorded profile here.
  if [[ ! -f "$dir/running" && -f "$dir/profile" ]]; then
    IFS= read -r profile < "$dir/profile" || true
    restore_client_profile "$profile" "$dir" || true
  fi
  test_log "Stop requested."
}

test_hotspot_run() {
  local minutes="$1"
  local dir profile password duration start now
  dir="$(test_dir)"
  mkdir -p "$dir"
  profile="${FT_WIFI_TEST_PROFILE-}"
  if [[ -z "$profile" && -f "$dir/profile" ]]; then
    IFS= read -r profile < "$dir/profile" || true
  fi
  if [[ -z "$profile" ]]; then
    test_log "No active client Wi-Fi profile to restore. Not starting the test."
    return 1
  fi
  printf '%s\n' "$profile" > "$dir/profile"
  FT_WIFI_TEST_PROFILE="$profile"
  export FT_WIFI_TEST_PROFILE
  : > "$dir/running"
  rm -f "$dir/stop" "$dir/portal-saved"

  # Profile and test dir are exported / looked up by name so this trap is safe
  # after the function's local variables go out of scope on EXIT.
  trap 'rc=$?; trap - EXIT INT TERM; restore_client_profile "${FT_WIFI_TEST_PROFILE}" "$(test_dir)" || true; exit $rc' EXIT INT TERM

  password="$(hotspot_password)" || { test_log "Could not read the setup hotspot password."; return 1; }
  test_log "Starting the FlightTracker-Setup hotspot for a ${minutes}-minute test."
  start_hotspot "$HOTSPOT_SSID" "$password" "${FT_WIFI_IFACE:-wlan0}"
  password=""
  unset password

  duration="${FT_WIFI_TEST_SECONDS:-$((minutes * 60))}"
  start="$(date +%s)"
  # Wait until the hotspot is up before watching for a portal save, so a
  # still-active home profile at the first instant is not treated as done.
  while ! hotspot_is_up; do
    [[ -f "$dir/stop" ]] && break
    now="$(date +%s)"
    (( now - start >= duration )) && break
    # Give up waiting for the AP after 15 seconds and continue the timer.
    (( now - start >= ${FT_WIFI_TEST_HOTSPOT_WAIT:-15} )) && break
    sleep "${FT_WIFI_TEST_POLL:-1}"
  done
  while true; do
    [[ -f "$dir/stop" ]] && { test_log "Stop requested."; break; }
    now="$(date +%s)"
    if (( now - start >= duration )); then
      test_log "Test timer ended."
      break
    fi
    if portal_saved_network "$dir"; then
      test_log "A network was saved from the setup portal."
      break
    fi
    sleep "${FT_WIFI_TEST_POLL:-1}"
  done
  trap - EXIT INT TERM
  restore_client_profile "$profile" "$dir"
}

test_hotspot_cmd() {
  local arg="${1:-10}" minutes self server
  if [[ "$arg" == "--stop" || "$arg" == "stop" ]]; then
    test_hotspot_stop
    return 0
  fi
  if [[ ! "$arg" =~ ^[0-9]+$ ]] || (( arg < 1 || arg > 30 )); then
    echo "Usage: sudo flight-tracker-wifi-test [minutes]   (1-30, default 10)" >&2
    echo "       sudo flight-tracker-wifi-test --stop" >&2
    return 1
  fi
  minutes="$arg"

  if [[ "${FT_WIFI_TEST_SUPERVISED:-}" == "1" ]]; then
    test_hotspot_run "$minutes"
    return
  fi

  local profile dir
  profile="$(active_client_profile)" || {
    echo "No active client Wi-Fi profile. Connect to home Wi-Fi first, then retry." >&2
    return 1
  }
  dir="$(test_dir)"
  mkdir -p "$dir"
  printf '%s\n' "$profile" > "$dir/profile"
  FT_WIFI_TEST_PROFILE="$profile"
  export FT_WIFI_TEST_PROFILE

  if [[ "${FT_WIFI_TEST_FOREGROUND:-}" == "1" ]]; then
    test_hotspot_run "$minutes"
    return
  fi

  if ! command -v systemd-run >/dev/null 2>&1; then
    echo "systemd-run is not available; cannot start a test that survives a dropped SSH session." >&2
    return 1
  fi
  if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet flight-tracker-wifi-test 2>/dev/null; then
      echo "A Wi-Fi test is already running. Stop it first: sudo flight-tracker-wifi-test --stop" >&2
      return 1
    fi
    systemctl reset-failed flight-tracker-wifi-test >/dev/null 2>&1 || true
  fi

  self="$(readlink -f "$0" 2>/dev/null || true)"
  [[ -n "$self" ]] || self="$0"
  server="${FT_SERVER_DIR:-$(cd "$(dirname "$self")/../server" && pwd)}"

  test_log "Starting a ${minutes}-minute FlightTracker-Setup hotspot test."
  echo "This unit will leave home Wi-Fi, so this SSH session may drop. The test keeps running."
  echo "The original Wi-Fi profile will be restored when the timer ends, when you save a network on the setup page, or when you run: sudo flight-tracker-wifi-test --stop"
  echo "If the Pi does not come back, wait the full ${minutes} minutes, then power-cycle. NetworkManager will reconnect the saved home profile."

  systemd-run --unit=flight-tracker-wifi-test --collect \
    --setenv=FT_WIFI_TEST_SUPERVISED=1 \
    --setenv=FT_WIFI_TEST_PROFILE="$profile" \
    --setenv=FT_WIFI_TEST_DIR="$dir" \
    --setenv=FT_SERVER_DIR="$server" \
    --setenv=FT_HOTSPOT_JSON="${FT_HOTSPOT_JSON:-/etc/flight-tracker/hotspot.json}" \
    --setenv=PATH="${PATH:-/usr/sbin:/usr/bin:/sbin:/bin}" \
    -- "$self" test-hotspot "$minutes"
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
    connecting_dir="$(dirname "${FT_WIFI_CONNECTING:-/run/flight-tracker-wifi/connecting}")"
    mkdir -p "$connecting_dir" 2>/dev/null || true
    : > "${FT_WIFI_CONNECTING:-/run/flight-tracker-wifi/connecting}" || true
    trap 'rm -f "${FT_WIFI_CONNECTING:-/run/flight-tracker-wifi/connecting}"' EXIT
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
    if nmcli "${args[@]}"; then
      promote_client_network "$ssid"
      test_dir="${FT_WIFI_TEST_DIR:-/run/flight-tracker-wifi-test}"
      if [[ -f "$test_dir/running" ]]; then
        : > "$test_dir/portal-saved"
      fi
    else
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
  saved)
    saved_client_profiles
    ;;
  client-profiles)
    client_profiles
    ;;
  forget)
    if [[ -z "${1:-}" ]]; then
      forget_client_profiles
    else
      forget_one_client "${1}" "${2:-}"
    fi
    ;;
  prefer)
    prefer_one_client "${1:-}" "${2:-}"
    ;;
  password)
    set_client_password "${1:-}" "${2:-}"
    ;;
  boot-hotspot)
    boot_hotspot_cmd "${1:-}" "${2:-}" "${3:-}"
    ;;
  test-hotspot)
    test_hotspot_cmd "$@"
    ;;
  *)
    echo "Use scan, connect, saved, forget, prefer, password, country, hotspot, client-profiles, boot-hotspot, or test-hotspot." >&2
    exit 1
    ;;
esac
