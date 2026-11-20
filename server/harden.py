"""One-time move of the Flight Tracker server to its own service account (1.0.7).

Before 1.0.7 the web server ran as the desktop login, which also owned
/opt/flight-tracker, /etc/flight-tracker and the update key file, while sudo
ran the updater from that tree as root. This moves the server to a
dedicated system account (``ft-server``, never the desktop login) and makes
the code and trust anchors root-owned:

* /opt/flight-tracker            root:root, not writable by the server
* /etc/flight-tracker-keys       root:root, pinned update keys
* /var/lib/flight-tracker        root:root, update trust state and backups
* /etc/flight-tracker            ft-server (config, status; readable by the kiosk)
* /var/cache/flight-tracker      ft-server
* sudoers helpers                for ft-server instead of the desktop login
* flight-tracker.service         User=ft-server via a drop-in

It runs as root from the update helper (``--harden``), the nightly timer, or
install.sh. The server is restarted under the new account and must answer
/api/health with the running version; if not, every step is undone (drop-in
removed, sudoers and ownership restored) and the server restarts as before.
"""
from __future__ import annotations

import json
import os
import pwd
import grp
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

SERVICE_USER = "ft-server"
SERVICE_UNIT = "flight-tracker.service"
EXTRA_GROUPS = ("video", "gpio", "i2c", "spi")
SUDO_COMMANDS = (
    "/usr/local/sbin/flight-tracker-brightness",
    "/usr/local/sbin/flight-tracker-wifi",
    "/usr/local/sbin/flight-tracker-update",
    "/usr/bin/systemctl restart flight-tracker-kiosk.service",
)


@dataclass
class Paths:
    opt: Path = Path("/opt/flight-tracker")
    etc: Path = Path("/etc/flight-tracker")
    cache: Path = Path("/var/cache/flight-tracker")
    keys: Path = Path("/etc/flight-tracker-keys")
    state: Path = Path("/var/lib/flight-tracker")
    unit_file: Path = Path("/etc/systemd/system/flight-tracker.service")
    dropin: Path = Path("/etc/systemd/system/flight-tracker.service.d/10-service-account.conf")
    sudoers: Path = Path("/etc/sudoers.d/flight-tracker-brightness")

    @property
    def marker(self) -> Path:
        return self.state / "service-account.json"


@dataclass
class System:
    """Everything that touches the real machine, swappable in tests."""
    run: Callable[..., subprocess.CompletedProcess] = field(default=lambda args, **kw: subprocess.run(args, check=False, capture_output=True, text=True, timeout=120, **kw))
    user_ids: Callable[[str], tuple[int, int] | None] = None  # type: ignore[assignment]
    group_exists: Callable[[str], bool] = None  # type: ignore[assignment]
    chown: Callable[[Path, int, int], None] = None  # type: ignore[assignment]
    healthy: Callable[[str, str, float], bool] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.user_ids is None:
            def ids(name: str) -> tuple[int, int] | None:
                try:
                    entry = pwd.getpwnam(name)
                except KeyError:
                    return None
                return entry.pw_uid, entry.pw_gid
            self.user_ids = ids
        if self.group_exists is None:
            def exists(name: str) -> bool:
                try:
                    grp.getgrnam(name)
                    return True
                except KeyError:
                    return False
            self.group_exists = exists
        if self.chown is None:
            self.chown = lambda path, uid, gid: os.lchown(path, uid, gid)
        if self.healthy is None:
            self.healthy = wait_healthy


def wait_healthy(url: str, version: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                body = json.loads(response.read(4096).decode("utf-8"))
            if isinstance(body, dict) and body.get("ok") is True and body.get("version") == version:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def unit_user(paths: Paths) -> str:
    """The account flight-tracker.service runs as (drop-in wins over the unit file)."""
    for source in (paths.dropin, paths.unit_file):
        try:
            text = source.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if line.strip().startswith("User="):
                return line.split("=", 1)[1].strip()
    return ""


def running_version(paths: Paths) -> str:
    try:
        return (paths.opt / "current" / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def sudoers_text(user: str) -> str:
    return "".join(f"{user} ALL=(root) NOPASSWD: {command}\n" for command in SUDO_COMMANDS)


def dropin_text(paths: Paths) -> str:
    # lgpio keeps notify pipes in LG_WD (default: the working directory, which is root-owned now).
    return f"[Service]\nUser={SERVICE_USER}\nGroup={SERVICE_USER}\nEnvironment=LG_WD={paths.cache}\n"


def chown_tree(system: System, top: Path, uid: int, gid: int, skip: tuple[Path, ...] = ()) -> None:
    """lchown every entry under ``top`` without following symlinks."""
    if not top.exists():
        return
    system.chown(top, uid, gid)
    for folder, dirs, files in os.walk(top, followlinks=False):
        for name in dirs + files:
            path = Path(folder) / name
            if path in skip:
                continue
            system.chown(path, uid, gid)


def strip_group_other_write(top: Path) -> None:
    if not top.exists():
        return
    for folder, dirs, files in os.walk(top, followlinks=False):
        for name in [None] + dirs + files:
            path = Path(folder) if name is None else Path(folder) / name
            if path.is_symlink():
                continue
            mode = path.stat().st_mode & 0o7777
            if mode & 0o022:
                path.chmod(mode & ~0o022)


def _write(path: Path, text: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.new")
    temporary.unlink(missing_ok=True)
    temporary.write_text(text, encoding="utf-8")
    temporary.chmod(mode)
    os.replace(temporary, path)


def pin_keys(paths: Paths, system: System) -> list[str]:
    """Copy the 1.0.6 key file into the root-owned key folder once."""
    try:
        from update_trust import key_id
    except ImportError:
        from server.update_trust import key_id
    paths.keys.mkdir(parents=True, exist_ok=True)
    paths.keys.chmod(0o755)
    system.chown(paths.keys, 0, 0)
    existing = sorted(paths.keys.glob("*.pem"))
    if existing:
        return [p.name for p in existing]
    for source in (paths.etc / "update-public.pem", paths.opt / "current" / "deploy" / "update-public.pem"):
        if source.is_file() and not source.is_symlink():
            kid = key_id(source)
            target = paths.keys / f"release-{kid}.pem"
            _write(target, source.read_text(encoding="ascii"), 0o644)
            system.chown(target, 0, 0)
            return [target.name]
    raise RuntimeError("No update public key to pin")


def harden_if_needed(**kwargs: Any) -> dict[str, Any] | None:
    paths = kwargs.get("paths") or Paths()
    if paths.marker.is_file() or not paths.unit_file.is_file():
        return None
    return harden(**kwargs)


def harden(
    *,
    paths: Paths | None = None,
    system: System | None = None,
    health_url: str = "http://127.0.0.1:8741/api/health",
    health_timeout: float = 60,
) -> dict[str, Any]:
    paths = paths or Paths()
    system = system or System()
    if paths == Paths() and os.geteuid() != 0:  # the real system needs root; tests pass their own paths
        return {"ok": False, "error": "Must run as root"}
    previous = unit_user(paths)
    version = running_version(paths)
    if previous == SERVICE_USER:
        _mark(paths, previous, "already")
        return {"ok": True, "user": SERVICE_USER, "changed": False}
    if not previous or previous == "root":
        return {"ok": False, "error": f"Unexpected service user {previous!r}; not changed"}
    prev_ids = system.user_ids(previous)
    if prev_ids is None:
        return {"ok": False, "error": f"Service user {previous} does not exist; not changed"}

    paths.state.mkdir(parents=True, exist_ok=True)
    paths.state.chmod(0o755)
    system.chown(paths.state, 0, 0)
    backup = paths.state / "harden-backup"
    backup.mkdir(exist_ok=True)
    old_sudoers = paths.sudoers.read_text(encoding="utf-8") if paths.sudoers.is_file() else ""
    (backup / "sudoers").write_text(old_sudoers, encoding="utf-8")
    (backup / "previous-user").write_text(previous + "\n", encoding="utf-8")

    steps: list[str] = []
    try:
        if system.user_ids(SERVICE_USER) is None:
            result = system.run(["useradd", "--system", "--user-group", "--no-create-home",
                                 "--home-dir", str(paths.state), "--shell", "/usr/sbin/nologin", SERVICE_USER])
            if result.returncode != 0 or system.user_ids(SERVICE_USER) is None:
                raise RuntimeError(f"useradd failed: {(result.stderr or '').strip()}")
            steps.append("created account")
        uid, gid = system.user_ids(SERVICE_USER)  # type: ignore[misc]
        for group in EXTRA_GROUPS:
            if system.group_exists(group):
                system.run(["usermod", "-aG", group, SERVICE_USER])
        steps.append("pinned keys: " + ", ".join(pin_keys(paths, system)))

        chown_tree(system, paths.opt, 0, 0)
        strip_group_other_write(paths.opt)
        legacy_key = paths.etc / "update-public.pem"
        chown_tree(system, paths.etc, uid, gid, skip=(legacy_key,))
        if legacy_key.exists():
            system.chown(legacy_key, 0, 0)
        paths.etc.chmod(0o755)
        chown_tree(system, paths.cache, uid, gid)
        steps.append("ownership")

        candidate = paths.sudoers.with_name(".flight-tracker-sudoers.new")
        _write(candidate, sudoers_text(SERVICE_USER), 0o440)
        check = system.run(["visudo", "-cf", str(candidate)])
        if check.returncode != 0:
            candidate.unlink(missing_ok=True)
            raise RuntimeError("visudo rejected the new sudoers file")
        os.replace(candidate, paths.sudoers)
        steps.append("sudoers")

        _write(paths.dropin, dropin_text(paths), 0o644)
        system.run(["systemctl", "daemon-reload"])
        system.run(["systemctl", "restart", SERVICE_UNIT])
        steps.append("restarted")
        if not system.healthy(health_url, version, health_timeout):
            raise RuntimeError(f"Flight Tracker did not come back as {SERVICE_USER}")
    except Exception as exc:
        _undo(paths, system, previous, prev_ids, old_sudoers, health_url, version, health_timeout)
        # Not retried every night (each try restarts the screen); `flight-tracker-update --harden` retries.
        _mark(paths, previous, f"failed: {exc}"[:300], previous)
        return {"ok": False, "error": str(exc), "rolledBack": True, "user": previous, "steps": steps}

    try:
        (paths.etc / "update-token").unlink(missing_ok=True)  # 1.0.7 is tokenless
    except OSError:
        pass
    _mark(paths, SERVICE_USER, "moved", previous)
    return {"ok": True, "user": SERVICE_USER, "previous": previous, "changed": True, "steps": steps}


def _undo(paths: Paths, system: System, previous: str, prev_ids: tuple[int, int], old_sudoers: str,
          health_url: str, version: str, timeout: float) -> None:
    """Put the service back exactly as 1.0.6 left it: desktop login, same files, same sudoers."""
    paths.dropin.unlink(missing_ok=True)
    try:
        if old_sudoers:
            _write(paths.sudoers, old_sudoers, 0o440)
        uid, gid = prev_ids
        legacy_key = paths.etc / "update-public.pem"
        for top in (paths.opt, paths.etc, paths.cache):
            chown_tree(system, top, uid, gid, skip=(legacy_key,))
        if legacy_key.exists():
            system.chown(legacy_key, 0, 0)
    finally:
        system.run(["systemctl", "daemon-reload"])
        system.run(["systemctl", "restart", SERVICE_UNIT])
        system.healthy(health_url, version, timeout)


def _mark(paths: Paths, user: str, how: str, previous: str = "") -> None:
    paths.state.mkdir(parents=True, exist_ok=True)
    body = {"user": user, "previous": previous, "how": how, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _write(paths.marker, json.dumps(body, indent=2) + "\n", 0o644)
