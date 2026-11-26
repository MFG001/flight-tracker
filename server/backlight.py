#!/usr/bin/env python3
"""Sysfs backlight writes, permission setup, and the sudo helper body.

The Waveshare 4inch DSI LCD (C) wiki publishes
``echo N | sudo tee /sys/class/backlight/*/brightness`` with N in 0–255.
The kernel driver (panel-waveshare-dsi / gpio-waveshare-dsi) registers a
BACKLIGHT_RAW device with max_brightness 255, usually named after the I2C
client (10-0045 or 11-0045 on a Pi 4). Other backlight nodes, when present,
may use a smaller max; each node is scaled and written on its own so one
failure does not block the panel.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_ROOT = Path("/sys/class/backlight")
UDEV_NAME = "99-flight-tracker-backlight.rules"
SUDOERS_PATH = Path("/etc/sudoers.d/flight-tracker-brightness")
UDEV_PATH = Path("/etc/udev/rules.d") / UDEV_NAME
BRIGHTNESS_SUDO_LINE = "ft-server ALL=(root) NOPASSWD: /usr/local/sbin/flight-tracker-brightness"


def backlight_root() -> Path:
    return Path(os.environ.get("FT_BACKLIGHT_ROOT") or DEFAULT_ROOT)


def list_nodes(root: Path | None = None) -> list[Path]:
    base = root if root is not None else backlight_root()
    return sorted(path for path in base.glob("*/brightness") if path.is_file() or path.is_symlink())


def scale_value(value_255: int, max_brightness: int) -> int:
    ceiling = max(1, int(max_brightness))
    level = min(255, max(0, int(value_255)))
    return int(round(level * ceiling / 255))


def _max_brightness(node: Path) -> int:
    path = node.parent / "max_brightness"
    try:
        return max(1, int(path.read_text(encoding="ascii").strip() or "255"))
    except (OSError, ValueError):
        return 255


def write_nodes(value_255: int, root: Path | None = None) -> list[str]:
    """Write a 0–255 wiki value to every backlight node. Returns paths written."""
    written: list[str] = []
    for node in list_nodes(root):
        level = scale_value(value_255, _max_brightness(node))
        try:
            node.write_text(str(level), encoding="ascii")
        except OSError:
            continue
        written.append(str(node))
    return written


def relax_node_permissions(root: Path | None = None) -> list[str]:
    """Make existing brightness nodes group-writable (video) so ft-server can write."""
    changed: list[str] = []
    for node in list_nodes(root):
        try:
            mode = node.stat().st_mode
            os.chmod(node, mode | 0o020 | 0o004)
        except OSError:
            continue
        try:
            shutil.chown(node, group="video")
        except (OSError, KeyError, LookupError, PermissionError):
            pass
        changed.append(str(node))
    return changed


def udev_rule_text() -> str:
    rule = Path(__file__).resolve().parents[1] / "deploy" / UDEV_NAME
    if rule.is_file():
        return rule.read_text(encoding="utf-8")
    return (
        "# Flight Tracker: let the video group (ft-server) write the panel backlight.\n"
        "ACTION==\"add\", SUBSYSTEM==\"backlight\", TEST==\"brightness\", "
        "RUN+=\"/bin/chgrp video /sys/class/backlight/%k/brightness\", "
        "RUN+=\"/bin/chmod g+w /sys/class/backlight/%k/brightness\"\n"
    )


def install_udev_rule(dest: Path = UDEV_PATH) -> bool:
    text = udev_rule_text()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.read_text(encoding="utf-8") == text:
        return False
    temporary = dest.with_name(f".{dest.name}.new")
    temporary.write_text(text, encoding="utf-8")
    temporary.chmod(0o644)
    os.replace(temporary, dest)
    return True


def ensure_sudoers(path: Path = SUDOERS_PATH, user: str = "ft-server") -> bool:
    """Install or append the brightness sudo line. Returns True when the file changed."""
    try:
        from harden import sudoers_text
    except ImportError:
        from server.harden import sudoers_text  # type: ignore
    line = f"{user} ALL=(root) NOPASSWD: /usr/local/sbin/flight-tracker-brightness"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if line in existing:
        return False
    text = sudoers_text(user) if not existing.strip() else existing.rstrip() + "\n" + line + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".flight-tracker-sudoers.new")
    temporary.write_text(text, encoding="utf-8")
    temporary.chmod(0o440)
    visudo = shutil.which("visudo")
    if visudo:
        check = subprocess.run([visudo, "-cf", str(temporary)], check=False, capture_output=True, text=True)
        if check.returncode != 0:
            temporary.unlink(missing_ok=True)
            raise RuntimeError((check.stderr or check.stdout or "visudo rejected the sudoers file").strip())
    os.replace(temporary, path)
    return True


def install_permissions(
    *,
    root: Path | None = None,
    udev_path: Path = UDEV_PATH,
    sudoers_path: Path = SUDOERS_PATH,
    user: str = "ft-server",
    reload_udev: bool = True,
) -> dict[str, object]:
    """Write the udev rule, sudoers line, and live node modes. Safe to re-run."""
    notes: dict[str, object] = {"udev": False, "sudoers": False, "nodes": []}
    try:
        notes["udev"] = install_udev_rule(udev_path)
    except OSError as exc:
        notes["udev_error"] = str(exc)
    try:
        notes["sudoers"] = ensure_sudoers(sudoers_path, user)
    except (OSError, RuntimeError) as exc:
        notes["sudoers_error"] = str(exc)
    notes["nodes"] = relax_node_permissions(root)
    if reload_udev and shutil.which("udevadm"):
        try:
            subprocess.run(["udevadm", "control", "--reload-rules"], check=False, capture_output=True, timeout=15)
            subprocess.run(["udevadm", "trigger", "--subsystem-match=backlight"], check=False, capture_output=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            pass
    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Flight Tracker panel backlight")
    parser.add_argument("--value", type=int, help="Brightness in the wiki 0–255 range")
    parser.add_argument("--install-permissions", action="store_true")
    parser.add_argument("--root", default=None, help="Override /sys/class/backlight (or set FT_BACKLIGHT_ROOT)")
    parser.add_argument("--udev", default=None)
    parser.add_argument("--sudoers", default=None)
    parser.add_argument("--user", default="ft-server")
    parser.add_argument("--no-udev-reload", action="store_true")
    args = parser.parse_args(argv)
    if args.root:
        os.environ["FT_BACKLIGHT_ROOT"] = args.root
    root = Path(args.root) if args.root else None
    if args.install_permissions:
        notes = install_permissions(
            root=root,
            udev_path=Path(args.udev) if args.udev else UDEV_PATH,
            sudoers_path=Path(args.sudoers) if args.sudoers else SUDOERS_PATH,
            user=args.user,
            reload_udev=not args.no_udev_reload,
        )
        print(notes, flush=True)
        return 0
    if args.value is None:
        # brightness.sh passes the value as a positional too.
        parser.error("pass --value 0-255 or --install-permissions")
    if not 0 <= args.value <= 255:
        print("brightness must be 0-255", file=sys.stderr)
        return 1
    written = write_nodes(args.value, root)
    if not written:
        print(f"No writable backlight node under {backlight_root()}.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    # brightness.sh calls: backlight.py 128
    argv = sys.argv[1:]
    if argv and argv[0].isdigit() and not any(a.startswith("-") for a in argv):
        argv = ["--value", argv[0]]
    raise SystemExit(main(argv))
