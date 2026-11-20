#!/usr/bin/env bash
# Push a Flight Tracker release tarball to the Pi over the local network
# (Wi-Fi or Ethernet) and install it. Runs on macOS or Linux.
#
#   bash push-update.sh [TARBALL] [USER@HOST]
#
# TARBALL  flight-tracker-X.Y.Z.tar.gz, or the .tar Safari leaves after it
#          unzips a download. Default: the newest flight-tracker-*.tar* in
#          ~/Downloads, then in the current folder.
# USER@HOST  Default flighttracker@flighttracker.local. Also settable with
#          FLIGHT_TRACKER_HOST, e.g. FLIGHT_TRACKER_HOST=pi@flighttracker.local
#
# Run this on the Mac (or Linux computer), not on the Pi.
# You type the Pi's password (ssh, then sudo). The tarball is copied to a
# temporary folder on the Pi, unpacked with `tar xf` (works for .tar.gz and
# .tar), installed with `sudo bash install.sh`, and the folder is removed.
# No keys or tokens are created or copied.
set -euo pipefail

tarball="${1:-}"
target="${2:-${FLIGHT_TRACKER_HOST:-flighttracker@flighttracker.local}}"

if [[ -z "$tarball" ]]; then
  for dir in "$HOME/Downloads" "$PWD"; do
    [[ -d "$dir" ]] || continue
    newest="$(ls -t "$dir"/flight-tracker-*.tar* 2>/dev/null | head -n 1 || true)"
    if [[ -n "$newest" ]]; then
      tarball="$newest"
      break
    fi
  done
fi
if [[ -z "$tarball" || ! -f "$tarball" ]]; then
  echo "No release tarball found. Pass its path: bash push-update.sh ~/Downloads/flight-tracker-1.0.3.tar.gz" >&2
  exit 1
fi
case "$tarball" in
  *.tar.gz|*.tgz|*.tar) ;;
  *) echo "Expected a .tar.gz or .tar file, got: $tarball" >&2; exit 1 ;;
esac
if [[ ! "$target" =~ ^[A-Za-z0-9._-]+@[A-Za-z0-9._:-]+$ ]]; then
  echo "Target must look like user@host, e.g. flighttracker@flighttracker.local" >&2
  exit 1
fi

name="$(basename "$tarball")"
echo "Pushing $name to $target ..."

# One ssh connection for every step, so the password is asked once.
control="${TMPDIR:-/tmp}/ft-push-$$"
ssh_opts=(-o ControlMaster=auto -o "ControlPath=$control" -o ControlPersist=120 -o ConnectTimeout=15)
remote_dir=""
local_script=""
cleanup_local() {
  # The remote script removes its own folder; this covers a failure before it ran.
  if [[ -n "$remote_dir" ]]; then
    ssh "${ssh_opts[@]}" "$target" "rm -rf '$remote_dir'" >/dev/null 2>&1 || true
  fi
  ssh "${ssh_opts[@]}" -O exit "$target" >/dev/null 2>&1 || true
  rm -f "$control"
  [[ -n "$local_script" ]] && rm -f "$local_script"
}
trap cleanup_local EXIT

remote_dir="$(ssh "${ssh_opts[@]}" "$target" 'mktemp -d /tmp/flight-tracker-push.XXXXXX')"
if [[ ! "$remote_dir" =~ ^/tmp/flight-tracker-push\.[A-Za-z0-9]+$ ]]; then
  echo "Could not make a temporary folder on the Pi." >&2
  remote_dir=""
  exit 1
fi

# The install step runs from a script file on the Pi, not from stdin: sudo
# needs the terminal (ssh -t) to ask for the Pi password. 1.0.3-1.0.5 piped a
# heredoc into ssh -t, so sudo had no terminal and failed with "a terminal is
# required to read the password".
local_script="$(mktemp "${TMPDIR:-/tmp}/ft-remote-install.XXXXXX")"
cat > "$local_script" <<'REMOTE'
set -euo pipefail
dir="$1"; name="$2"
trap 'rm -rf "$dir"' EXIT
cd "$dir"
mkdir release
tar xf "$name" -C release
cd release
if [[ ! -f install.sh || ! -f VERSION ]]; then
  echo "That tarball is not a Flight Tracker release (no install.sh/VERSION)." >&2
  exit 1
fi
want="$(cat VERSION)"
echo "Installing Flight Tracker $want (type the Pi password if sudo asks) ..."
sudo bash install.sh
echo "Checking the display service ..."
ok=""
for _ in $(seq 1 30); do
  if systemctl is-active --quiet flight-tracker.service; then
    for url in http://127.0.0.1:8741/api/health http://127.0.0.1/api/health; do
      got="$(curl -fsS --max-time 3 "$url" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version",""))' 2>/dev/null || true)"
      if [[ "$got" == "$want" ]]; then
        ok=1
        break 2
      fi
    done
  fi
  sleep 1
done
if [[ -z "$ok" ]]; then
  echo "The service did not come back as $want. Recent log:" >&2
  sudo journalctl -u flight-tracker.service -n 30 --no-pager >&2 || true
  exit 1
fi
echo "flight-tracker.service is running $want."
REMOTE

# Fixed name on the Pi, so a Safari copy like "flight-tracker-1.0.6 (1).tar" needs no quoting.
scp "${ssh_opts[@]}" -q "$tarball" "$target:$remote_dir/upload.tar"
scp "${ssh_opts[@]}" -q "$local_script" "$target:$remote_dir/remote-install.sh"
echo "Copied. Installing on the Pi (it asks for the Pi password for sudo) ..."

# Unpack, install, check the service, and always remove the temporary folder.
# No stdin redirection here, so sudo can prompt on the terminal.
ssh "${ssh_opts[@]}" -t "$target" "bash '$remote_dir/remote-install.sh' '$remote_dir' upload.tar"
remote_dir=""
echo "Done. Open http://flighttracker.local/ to check settings."
