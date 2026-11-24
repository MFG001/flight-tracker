#!/usr/bin/env bash
# Check, and if needed fix, a freshly flashed Flight Tracker microSD card
# before its first boot. Runs on the Mac (or Linux), not on the Pi.
#
#   bash prep-sd-card.sh [check|wifi] [BOOT_VOLUME]
#
#   check  (default) Read the card's boot partition and report whether
#          Raspberry Pi Imager's OS customisation is there: hostname,
#          user, SSH and Wi-Fi. Changes nothing.
#   wifi   Write the Wi-Fi settings onto the card yourself, with the
#          network name exactly as typed. Use it when the check shows a
#          wrong or missing network name, for example when Imager dropped
#          a trailing space ("Home Net " became "Home Net").
#
# BOOT_VOLUME defaults to /Volumes/bootfs on a Mac, the partition the Mac
# mounts when the card is inserted. On Linux pass the mount point.
#
# Why this exists: Raspberry Pi Imager 2.x trims spaces from the start and end
# of the Wi-Fi network name it writes, so a network whose name ends in a space
# can never be joined from Imager's settings. The Pi then never joins Wi-Fi,
# never appears in the router's client list, and flighttracker.local does
# not resolve.
#
# The password is read without echo and written only to the card. It is
# never printed, logged or passed on a command line. No keys or tokens are
# created. Works with the macOS default bash 3.2.
set -euo pipefail

mode="${1:-check}"
case "$mode" in
  check|wifi) shift || true ;;
  /*) mode="check" ;;
  -h|--help) sed -n '2,27p' "$0"; exit 0 ;;
  *) echo "Usage: bash prep-sd-card.sh [check|wifi] [BOOT_VOLUME]" >&2; exit 1 ;;
esac

boot="${1:-}"
if [[ -z "$boot" ]]; then
  for d in /Volumes/bootfs /Volumes/boot /media/"${USER:-}"/bootfs /run/media/"${USER:-}"/bootfs; do
    if [[ -f "$d/config.txt" && -f "$d/cmdline.txt" ]]; then boot="$d"; break; fi
  done
fi
if [[ -z "$boot" || ! -f "$boot/cmdline.txt" ]]; then
  echo "Could not find the card. Put the microSD card in the Mac and wait for" >&2
  echo "a disk named \"bootfs\" to appear in Finder, then run this again." >&2
  exit 1
fi

ok()   { printf '  OK    %s\n' "$*"; }
bad()  { printf '  FIX   %s\n' "$*"; problems=$((problems + 1)); }
info() { printf '  ..    %s\n' "$*"; }
problems=0

# Show a name with its edges visible: [Home Net ] and its length.
show_name() { printf '[%s] (%d characters)' "$1" "${#1}"; }

# Wi-Fi network names listed under access-points: in network-config.
# Each is printed on its own line, without the surrounding quotes, and
# with YAML \" and \\ unescaped.
list_ssids() {
  awk '
    /^[[:space:]]*access-points:[[:space:]]*$/ { inap=1; next }
    inap && /^[[:space:]]*"/ {
      line=$0
      sub(/^[[:space:]]*"/, "", line)
      sub(/":[[:space:]]*$/, "", line)
      gsub(/\\"/, "\"", line); gsub(/\\\\/, "\\", line)
      print line
      next
    }
    inap && /^[[:space:]]*[A-Za-z]/ && !/^[[:space:]]*(password|hidden|auth|key-management)/ { inap=0 }
  ' "$1"
}

check_card() {
  echo "Card: $boot"
  if [[ -f "$boot/user-data" || -f "$boot/network-config" ]]; then
    echo "Format: cloud-init (Raspberry Pi OS Trixie)"
    local ud="$boot/user-data" nc="$boot/network-config"
    if [[ -f "$ud" ]]; then
      if grep -Eq '^hostname:[[:space:]]*"?flighttracker"?[[:space:]]*$' "$ud"; then ok "hostname is flighttracker"
      else bad "hostname is not flighttracker. Set it in Imager."; fi
      if grep -Eq '^[[:space:]]+name:[[:space:]]*"?flighttracker"?[[:space:]]*$' "$ud"; then ok "user is flighttracker"
      else bad "user flighttracker is not set. Set it in Imager."; fi
      if grep -Eq '^[[:space:]]+passwd:[[:space:]]*"?\$' "$ud"; then ok "a login password is set (stored scrambled)"
      else bad "no login password. Set one in Imager."; fi
      if grep -Eq '^ssh_pwauth:[[:space:]]*true' "$ud" && grep -Eq 'enable, *--now, *ssh' "$ud"; then ok "SSH is on, with password login"
      else bad "SSH with password login is not on. Turn it on in Imager."; fi
    else
      bad "no user-data: Imager's customisation was skipped. Hostname, user and SSH are not set."
    fi
    if [[ -f "$nc" ]] && grep -q 'access-points:' "$nc"; then
      local s
      while IFS= read -r s; do
        info "Wi-Fi network on the card: $(show_name "$s")"
        if [[ "$s" =~ ^[[:space:]] || "$s" =~ [[:space:]]$ ]]; then
          info "  (that name starts or ends with a space; it must match the router exactly)"
        fi
      done < <(list_ssids "$nc")
      if grep -Eq 'regulatory-domain:[[:space:]]*"?[A-Z]{2}"?' "$nc"; then
        ok "Wi-Fi country: $(grep -Eo 'regulatory-domain:[[:space:]]*"?[A-Z]{2}' "$nc" | grep -Eo '[A-Z]{2}$')"
      else
        bad "no Wi-Fi country. Run: bash prep-sd-card.sh wifi"
      fi
      if grep -Eq '^[[:space:]]+password:' "$nc"; then ok "a Wi-Fi password is set (not shown)"
      else bad "no Wi-Fi password. Run: bash prep-sd-card.sh wifi"; fi
      info "Compare the name above with your router's network name, character for"
      info "character. If yours ends in a space and this one does not, run:"
      info "  bash prep-sd-card.sh wifi"
    else
      info "No Wi-Fi on the card. Use an Ethernet cable, or run: bash prep-sd-card.sh wifi"
    fi
    local mid cid
    mid="$(sed -n 's/^instance-id:[[:space:]]*//p' "$boot/meta-data" 2>/dev/null | head -n 1)"
    cid="$(grep -Eo 'ds=nocloud;i=[^ ]+' "$boot/cmdline.txt" | sed 's/^ds=nocloud;i=//' | head -n 1 || true)"
    if [[ -n "$mid" && -n "$cid" && "$mid" != "$cid" ]]; then
      bad "meta-data and cmdline.txt disagree on instance-id ($mid vs $cid)."
    fi
  elif [[ -f "$boot/firstrun.sh" ]]; then
    echo "Format: firstrun.sh (Raspberry Pi OS Bookworm, Legacy)"
    local fr="$boot/firstrun.sh"
    if grep -Eq "set_hostname +['\"]?flighttracker" "$fr" || grep -q 'IMAGER_HOSTNAME=.flighttracker' "$fr"; then ok "hostname is flighttracker"
    else bad "hostname is not flighttracker. Set it in Imager."; fi
    if grep -q 'flighttracker' "$fr" && grep -Eq 'FIRSTUSER|userconf' "$fr"; then ok "user setup present (check it is flighttracker)"
    else bad "user flighttracker is not set. Set it in Imager."; fi
    if grep -Eq 'enable_ssh|systemctl enable ssh' "$fr"; then ok "SSH is on"; else bad "SSH is not on."; fi
    # Print only the network name: the first quoted word after set_wlan and
    # its flags. The password on the same line is never printed.
    local s
    s="$(grep -m1 'imager_custom set_wlan' "$fr" | sed -E "s/.*set_wlan +(-[hp] +)*'([^']*)'.*/\2/" || true)"
    if [[ -n "$s" ]]; then info "Wi-Fi network on the card: $(show_name "$s")"; else info "No Wi-Fi on the card."; fi
    info "For Bookworm cards this script only checks. Flash Raspberry Pi OS (64-bit)"
    info "(Trixie) instead, or use an Ethernet cable."
  else
    bad "no user-data, network-config or firstrun.sh: Imager's customisation was not applied."
    info "Flash again and fill in every customisation step, or this card cannot be reached."
  fi
  echo
  if (( problems == 0 )); then echo "Looks ready, if the Wi-Fi name above matches your router exactly. Eject the card, put it in the tracker, and power on."
  else echo "$problems item(s) to fix before the first boot."; fi
}

# Escape a value for a YAML double-quoted scalar.
yaml_dq() { local v="$1"; v="${v//\\/\\\\}"; v="${v//\"/\\\"}"; printf '%s' "$v"; }

write_wifi() {
  if [[ -f "$boot/firstrun.sh" && ! -f "$boot/user-data" ]]; then
    echo "This is a Bookworm (firstrun.sh) card. Flash Raspberry Pi OS (64-bit), which is" >&2
    echo "Trixie, and run this again, or install over an Ethernet cable." >&2
    exit 1
  fi
  if [[ ! -f "$boot/user-data" ]]; then
    echo "Imager's customisation is missing (no user-data), so the tracker would have no" >&2
    echo "flighttracker login or SSH even on Wi-Fi. Flash again with hostname, user and SSH" >&2
    echo "set in Imager, then run this for Wi-Fi." >&2
    exit 1
  fi
  echo "Type your Wi-Fi network name exactly as it appears on your phone or router,"
  echo "including any space at the end, then press Return."
  local ssid pass pass2 cc ans
  printf 'Network name: '
  IFS= read -r ssid
  ssid="${ssid%$'\r'}"
  if [[ -z "$ssid" || ${#ssid} -gt 32 ]]; then echo "The name must be 1 to 32 characters." >&2; exit 1; fi
  if [[ "$ssid" == *[[:cntrl:]]* ]]; then echo "The name has a control character in it." >&2; exit 1; fi
  echo "You typed $(show_name "$ssid")."
  if [[ "$ssid" =~ [[:space:]]$ ]]; then echo "It ends with a space."; else echo "It does not end with a space."; fi
  printf 'Is that exactly right? [y/N] '
  IFS= read -r ans
  [[ "$ans" == y || "$ans" == Y ]] || { echo "Nothing changed."; exit 1; }

  printf 'Wi-Fi password (not shown as you type): '
  IFS= read -rs pass; echo
  printf 'Type it again: '
  IFS= read -rs pass2; echo
  if [[ "$pass" != "$pass2" ]]; then pass=""; pass2=""; echo "The two passwords differ. Nothing changed." >&2; exit 1; fi
  pass2=""
  if (( ${#pass} < 8 || ${#pass} > 63 )); then pass=""; echo "A WPA password is 8 to 63 characters. Nothing changed." >&2; exit 1; fi
  if [[ "$pass" == *[[:cntrl:]]* ]]; then pass=""; echo "The password has a control character in it." >&2; exit 1; fi

  printf 'Wi-Fi country, two letters [US]: '
  IFS= read -r cc
  cc="$(printf '%s' "${cc:-US}" | tr '[:lower:]' '[:upper:]')"
  [[ "$cc" =~ ^[A-Z]{2}$ ]] || { pass=""; echo "Country must be two letters, like US." >&2; exit 1; }

  local tmp; tmp="$boot/.network-config.tmp"
  ( umask 077
    {
      printf 'network:\n'
      printf '  version: 2\n'
      printf '  ethernets:\n'
      printf '    eth0:\n'
      printf '      dhcp4: true\n'
      printf '      dhcp6: true\n'
      printf '      optional: true\n'
      printf '  wifis:\n'
      printf '    wlan0:\n'
      printf '      dhcp4: true\n'
      printf '      regulatory-domain: "%s"\n' "$cc"
      printf '      access-points:\n'
      printf '        "%s":\n' "$(yaml_dq "$ssid")"
      printf '          password: "%s"\n' "$(yaml_dq "$pass")"
      printf '      optional: true\n'
    } > "$tmp" )
  pass=""
  mv -f "$tmp" "$boot/network-config"

  # A new instance-id makes cloud-init apply the settings again even if the
  # card has already been booted once. It must match in both files.
  local newid; newid="flighttracker-$(date +%s)"
  printf 'instance-id: %s\n' "$newid" > "$boot/meta-data"
  local cl; cl="$(tr -d '\n' < "$boot/cmdline.txt")"
  if [[ "$cl" == *"ds=nocloud;i="* ]]; then
    cl="$(printf '%s' "$cl" | sed -E "s/ds=nocloud;i=[^ ]+/ds=nocloud;i=$newid/")"
  else
    cl="$cl ds=nocloud;i=$newid"
  fi
  printf '%s\n' "$cl" > "$boot/cmdline.txt"
  sync
  echo "Wrote Wi-Fi for $(show_name "$ssid"), country $cc."
  echo
  problems=0
  check_card
}

case "$mode" in
  check) check_card ;;
  wifi)  write_wifi ;;
esac
