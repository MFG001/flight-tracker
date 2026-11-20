#!/usr/bin/env python3
"""Rotation and touch setup for the round panel on Raspberry Pi OS (labwc).

Raspberry Pi OS Bookworm/Trixie runs the labwc Wayland compositor. Its
autostart runs kanshi, and the Screen Configuration tool (raindrop) saves
output rotation to ``~/.config/kanshi/config`` and touch-to-screen mapping to
``~/.config/labwc/rc.xml`` as ``<touch deviceName=... mapToOutput=.../>``.
This module writes the same two files for the desktop user so the rotation
and touch mapping survive a reboot. kiosk.sh also applies the rotation with
wlr-randr before it starts Chromium.

Every step is idempotent. An existing rc.xml is edited only by inserting one
``<touch>`` element; if it already has a touch entry for the device, or the
file cannot be parsed safely, it is left alone with a message.

Confirmed on the first Pi 4 unit: ``wlr-randr --output DSI-1 --transform 270``
gives the right picture. The kanshi file, rc.xml touch mapping, and the
optional libinput calibration matrix were not verified on hardware.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROTATIONS = (0, 90, 180, 270)
DEFAULTS: dict[str, Any] = {
    "rotation": 270,
    "output": "DSI-1",
    "touchDevice": "10-0014 Goodix Capacitive TouchScreen",
    "touchMatrix": False,
}
OUTPUT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
MARK = "Flight Tracker"
UDEV_RULE = Path("/etc/udev/rules.d/99-flight-tracker-touch.rules")

# libinput calibration matrices that rotate touch with the picture. They are
# only written when display.touchMatrix is true, as a fallback if mapToOutput
# alone does not rotate touch on this labwc build. Unverified on hardware.
MATRICES = {
    0: "1 0 0 0 1 0",
    90: "0 -1 1 1 0 0",
    180: "-1 0 1 0 -1 1",
    270: "0 1 0 -1 0 1",
}


def display_settings(cfg: Any) -> dict[str, Any]:
    """Return clean display settings from a config object, with defaults."""
    out = dict(DEFAULTS)
    raw = cfg.get("display") if isinstance(cfg, dict) else None
    if isinstance(raw, dict):
        try:
            rotation = int(raw.get("rotation", out["rotation"]))
        except (TypeError, ValueError):
            rotation = out["rotation"]
        if rotation in ROTATIONS:
            out["rotation"] = rotation
        output = str(raw.get("output") or "")
        if OUTPUT_RE.fullmatch(output):
            out["output"] = output
        touch = raw.get("touchDevice")
        if isinstance(touch, str) and len(touch) <= 80 and all(c.isprintable() and c not in '<>&"' for c in touch):
            out["touchDevice"] = touch
        out["touchMatrix"] = bool(raw.get("touchMatrix", False))
    return out


def transform_name(rotation: int) -> str:
    if rotation not in ROTATIONS:
        raise ValueError("rotation must be 0, 90, 180, or 270")
    return "normal" if rotation == 0 else str(rotation)


def kanshi_config(existing: str | None, output: str, rotation: int) -> str:
    """Return kanshi config text with ``output`` set to the rotation.

    Lines that already name the output get their transform replaced or added.
    Other outputs and profiles are kept. With no file, or no line for the
    output, a profile for it is added.
    """
    transform = transform_name(rotation)
    text = existing or ""
    pattern = re.compile(r'^(\s*output\s+"?' + re.escape(output) + r'"?)(\s.*)?$')
    lines = text.splitlines()
    changed = False
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        head, rest = match.group(1), match.group(2) or ""
        has_brace = rest.rstrip().endswith("{")
        if has_brace:
            # Block form: output DSI-1 { ... } is rare; leave it and add a profile.
            continue
        if re.search(r"\btransform\s+\S+", rest):
            rest = re.sub(r"\btransform\s+\S+", f"transform {transform}", rest)
        else:
            rest = rest.rstrip() + f" transform {transform}"
        if not re.search(r"\b(enable|disable)\b", rest):
            rest = " enable" + rest
        lines[index] = head + rest
        changed = True
    if changed:
        return "\n".join(lines).rstrip("\n") + "\n"
    block = f"profile {{\n\toutput {output} enable transform {transform}\n}}\n"
    if text.strip():
        return text.rstrip("\n") + "\n\n# " + MARK + " round panel\n" + block
    return "# " + MARK + " round panel (display.rotation in /etc/flight-tracker/config.json)\n" + block


def touch_element(device: str, output: str) -> str:
    return f'<touch deviceName="{device}" mapToOutput="{output}" mouseEmulation="yes"/>'


def rc_xml_with_touch(existing: str | None, device: str, output: str) -> tuple[str | None, str]:
    """Return (new rc.xml text or None if unchanged, message)."""
    element = touch_element(device, output)
    if existing is None or not existing.strip():
        text = (
            '<?xml version="1.0"?>\n'
            "<labwc_config>\n"
            f"  <!-- {MARK}: keep touch on the rotated panel -->\n"
            f"  {element}\n"
            "</labwc_config>\n"
        )
        return text, f"Created labwc rc.xml with touch mapped to {output}."
    if re.search(r'<touch\b[^>]*deviceName="' + re.escape(device) + r'"', existing):
        return None, "labwc rc.xml already maps this touchscreen; left it unchanged."
    for closing in ("</labwc_config>", "</openbox_config>"):
        position = existing.rfind(closing)
        if position != -1:
            insert = f"  <!-- {MARK}: keep touch on the rotated panel -->\n  {element}\n"
            return existing[:position] + insert + existing[position:], f"Added touch mapping for {output} to labwc rc.xml."
    return None, "labwc rc.xml has no <labwc_config> root; left it unchanged. Map touch in Screen Configuration instead."


def udev_rule(rotation: int) -> str:
    return (
        f"# {MARK}: rotate touch with display.rotation={rotation}. Unverified on hardware.\n"
        f'ENV{{ID_INPUT_TOUCHSCREEN}}=="1", ENV{{LIBINPUT_CALIBRATION_MATRIX}}="{MATRICES[rotation]}"\n'
    )


def detect_touch_device(default: str, devices_file: Path = Path("/proc/bus/input/devices")) -> str:
    """Prefer the touchscreen name the kernel reports; fall back to config."""
    try:
        text = devices_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return default
    names = re.findall(r'^N: Name="([^"]*)"', text, flags=re.MULTILINE)
    if default in names:
        return default
    for name in names:
        if "touchscreen" in name.lower() or "goodix" in name.lower():
            if all(c.isprintable() and c not in '<>&"' for c in name):
                return name
    return default


def _write_if_changed(path: Path, text: str, owner: tuple[int, int] | None) -> bool:
    if path.is_file() and path.read_text(encoding="utf-8", errors="replace") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        backup = path.with_name(path.name + ".bak-flight-tracker")
        if not backup.exists():
            shutil.copy2(path, backup)
    tmp = path.with_name(path.name + ".tmp-flight-tracker")
    tmp.write_text(text, encoding="utf-8")
    if owner is not None:
        os.chown(tmp, *owner)
    tmp.replace(path)
    return True


def _chown_tree(home: Path, path: Path, owner: tuple[int, int] | None) -> None:
    if owner is None:
        return
    current = path
    while current != home and home in current.parents:
        try:
            os.chown(current, *owner)
        except OSError:
            pass
        current = current.parent


def apply(cfg: dict[str, Any], home: Path, owner: tuple[int, int] | None = None,
          udev_path: Path | None = UDEV_RULE, devices_file: Path = Path("/proc/bus/input/devices")) -> list[str]:
    """Write kanshi, labwc touch, and optional udev files. Returns messages."""
    settings = display_settings(cfg)
    messages: list[str] = []
    kanshi = home / ".config" / "kanshi" / "config"
    old = kanshi.read_text(encoding="utf-8", errors="replace") if kanshi.is_file() else None
    if _write_if_changed(kanshi, kanshi_config(old, settings["output"], settings["rotation"]), owner):
        messages.append(f"Rotation {settings['rotation']} saved for {settings['output']} in {kanshi}.")
    else:
        messages.append(f"Rotation {settings['rotation']} for {settings['output']} was already in {kanshi}.")
    _chown_tree(home, kanshi.parent, owner)

    device = detect_touch_device(settings["touchDevice"], devices_file)
    rc = home / ".config" / "labwc" / "rc.xml"
    old_rc = rc.read_text(encoding="utf-8", errors="replace") if rc.is_file() else None
    new_rc, note = rc_xml_with_touch(old_rc, device, settings["output"])
    if new_rc is not None:
        _write_if_changed(rc, new_rc, owner)
        _chown_tree(home, rc.parent, owner)
    messages.append(note)

    if udev_path is not None:
        if settings["touchMatrix"]:
            if _write_if_changed(udev_path, udev_rule(settings["rotation"]), None):
                messages.append(f"Wrote touch calibration rule {udev_path}.")
        elif udev_path.is_file() and MARK in udev_path.read_text(encoding="utf-8", errors="replace"):
            udev_path.unlink()
            messages.append(f"Removed {udev_path} (display.touchMatrix is off).")
    return messages


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Flight Tracker panel rotation and touch mapping")
    parser.add_argument("--config", default="/etc/flight-tracker/config.json")
    parser.add_argument("--user", default="", help="Desktop account; defaults to the config file owner")
    parser.add_argument("--home", default="", help="Home folder override (tests)")
    parser.add_argument("--no-udev", action="store_true")
    parser.add_argument("--print-transform", action="store_true", help="Print the wlr-randr output and transform, then exit")
    args = parser.parse_args()
    try:
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cfg = {}
    settings = display_settings(cfg)
    if args.print_transform:
        print(settings["output"], transform_name(settings["rotation"]))
        return
    owner: tuple[int, int] | None = None
    home = Path(args.home) if args.home else None
    user = args.user
    if not user and home is None:
        try:
            uid = Path(args.config).stat().st_uid
            user = pwd.getpwuid(uid).pw_name
        except (OSError, KeyError):
            user = ""
    if user:
        if not re.fullmatch(r"[a-z_][a-z0-9_-]*", user) or user == "root":
            raise SystemExit(f"Refusing display setup for account {user!r}")
        entry = pwd.getpwnam(user)
        home = home or Path(entry.pw_dir)
        if os.geteuid() == 0:
            owner = (entry.pw_uid, entry.pw_gid)
    if home is None:
        raise SystemExit("No desktop account found for display setup")
    udev = None if args.no_udev or os.geteuid() != 0 else UDEV_RULE
    for line in apply(cfg, home, owner, udev):
        print(line)
    if udev is not None and shutil.which("udevadm"):
        subprocess.run(["udevadm", "control", "--reload-rules"], check=False)
        subprocess.run(["udevadm", "trigger", "--subsystem-match=input"], check=False)


if __name__ == "__main__":
    main()
