#!/usr/bin/env python3
"""Signed updates for Flight Tracker.

A release is a JSON manifest plus a gzipped tarball. The manifest carries the
version, notes, tarball URL, sha256, and an Ed25519 signature. The signature
is checked with the public key copied into /etc at install time. Unsigned
bytes are never unpacked or executed.

Install layout::

    /opt/flight-tracker/releases/<version>/
    /opt/flight-tracker/current -> releases/<version>

``current`` is replaced with ``os.replace``, which is atomic on one filesystem.
The service is then restarted. If it does not report the new version within
the health window, ``current`` is pointed back at the previous release and the
service is started again. The two newest good releases are kept.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

try:
    import update_trust as trust
except ImportError:  # imported as server.updater (tests, tools)
    from server import update_trust as trust

PRODUCT = "flight-tracker"
MANIFEST_LIMIT = 64 * 1024
TARBALL_LIMIT = 200 * 1024 * 1024
VERSION_RE = re.compile(r"^\d+(?:\.\d+){1,3}$")
IDLE_SECONDS = 15 * 60
NIGHT_HOURS = range(1, 5)
# 1.0.7: tokenless. Releases come anonymously from the public repo; the
# private repo URL below is only recognised so old configs move off it.
PUBLIC_REPO = "MFG001/flight-tracker"
PUBLIC_MANIFEST_URL = f"https://github.com/{PUBLIC_REPO}/releases/latest/download/manifest.json"
LEGACY_PRIVATE_URL = "https://api.github.com/repos/MFG001/flight-tracker-updates/releases/latest"
GITHUB_RELEASES_URL = PUBLIC_MANIFEST_URL
PLACEHOLDER_URL = PUBLIC_MANIFEST_URL
TOKEN_NAME = "update-token"  # pre-1.0.7 file; removed by --harden
# Root-owned trust anchors and update state (not writable by the service account).
KEYS_DIR = Path("/etc/flight-tracker-keys")
STATE_DIR = Path("/var/lib/flight-tracker")
SYSTEM_CONFIG = Path("/etc/flight-tracker/config.json")
WRAPPER_PATH = Path("/usr/local/sbin/flight-tracker-update")
KIOSK_UNIT = "flight-tracker-kiosk.service"
INSTALL_STEPS = 4
MB = 1024 * 1024
# Progress callback for a download: (bytes received, Content-Length or None).
Progress = Callable[[int, "int | None"], None]


class UpdateError(Exception):
    """A check or install stopped before untrusted code could run."""


def parse_version(value: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not VERSION_RE.fullmatch(value.strip()):
        raise UpdateError("Version must look like 1.2.3")
    return tuple(int(part) for part in value.strip().split("."))


def version_text(value: str) -> str:
    parse_version(value)
    return value.strip()


def require_https(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise UpdateError("Update URLs must be HTTPS")
    if parts.username or parts.password:
        raise UpdateError("Update URLs must not contain credentials")


def canonical(version: str, url: str, sha256: str, notes: str) -> bytes:
    """Bytes the release key signs. Notes are hashed so newlines stay intact."""
    notes_hash = hashlib.sha256(notes.encode("utf-8")).hexdigest()
    text = (
        "flight-tracker-update-v1\n"
        f"product={PRODUCT}\n"
        f"version={version}\n"
        f"url={url}\n"
        f"sha256={sha256}\n"
        f"notes={notes_hash}\n"
    )
    return text.encode("utf-8")


def _openssl(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(args, check=False, capture_output=True)
    except FileNotFoundError as exc:
        raise UpdateError("openssl is required to verify update signatures") from exc


def sign_bytes(message: bytes, private_key: Path) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        message_path = folder / "message"
        signature_path = folder / "signature"
        message_path.write_bytes(message)
        result = _openssl(
            [
                "openssl", "pkeyutl", "-sign",
                "-inkey", str(private_key),
                "-rawin", "-in", str(message_path),
                "-out", str(signature_path),
            ]
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace").strip()
            raise UpdateError(detail or "Could not sign the manifest")
        return signature_path.read_bytes()


def verify_bytes(message: bytes, signature: bytes, public_key: Path) -> bool:
    if not public_key.is_file():
        raise UpdateError(f"Update public key is missing: {public_key}")
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        message_path = folder / "message"
        signature_path = folder / "signature"
        message_path.write_bytes(message)
        signature_path.write_bytes(signature)
        result = _openssl(
            [
                "openssl", "pkeyutl", "-verify",
                "-pubin", "-inkey", str(public_key),
                "-rawin", "-in", str(message_path),
                "-sigfile", str(signature_path),
            ]
        )
        return result.returncode == 0


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(version: str, notes: str, url: str, sha256: str, private_key: Path) -> dict[str, str]:
    version = version_text(version)
    require_https(url)
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise UpdateError("sha256 must be 64 hex characters")
    signature = sign_bytes(canonical(version, url, sha256, notes), private_key)
    return {
        "product": PRODUCT,
        "version": version,
        "notes": notes,
        "url": url,
        "sha256": sha256,
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def verify_manifest(document: Any, public_key: Path) -> dict[str, str]:
    if not isinstance(document, dict):
        raise UpdateError("Manifest must be a JSON object")
    if document.get("product") != PRODUCT:
        raise UpdateError("Manifest is not for Flight Tracker")
    version = version_text(str(document.get("version") or ""))
    notes = document.get("notes")
    url = str(document.get("url") or "")
    sha = str(document.get("sha256") or "")
    raw_sig = str(document.get("signature") or "")
    if not isinstance(notes, str):
        raise UpdateError("Manifest notes must be text")
    require_https(url)
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise UpdateError("Manifest sha256 is missing")
    try:
        signature = base64.b64decode(raw_sig, validate=True)
    except (ValueError, TypeError) as exc:
        raise UpdateError("Manifest signature is not valid base64") from exc
    message = canonical(version, url, sha, notes)
    if not verify_bytes(message, signature, public_key):
        raise UpdateError("Manifest signature does not match the installed public key")
    return {"product": PRODUCT, "version": version, "notes": notes, "url": url, "sha256": sha, "signature": raw_sig}


class _AllowlistRedirect(urllib.request.HTTPRedirectHandler):
    """Every redirect hop must stay on the GitHub release hosts over HTTPS."""

    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> urllib.request.Request | None:
        try:
            trust.check_url(newurl)
        except trust.TrustError as exc:
            raise UpdateError(str(exc)) from exc
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _HttpsRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> urllib.request.Request | None:
        require_https(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        host = urllib.parse.urlsplit(newurl).hostname or ""
        if host != "api.github.com":
            redirected.remove_header("Authorization")
        return redirected


def _github_http_error(url: str, exc: urllib.error.HTTPError) -> None:
    host = urllib.parse.urlsplit(url).hostname or ""
    if host not in trust.ALLOWED_HOSTS:
        return
    if exc.code == 404:
        raise UpdateError(f"No published release was found at {url}.") from exc
    raise UpdateError(f"GitHub returned HTTP {exc.code}") from exc


def fetch_bytes(
    url: str,
    limit: int,
    ca_file: str | None = None,
    timeout: float = 30,
    headers: dict[str, str] | None = None,
    progress: Progress | None = None,
    public: bool = False,
) -> bytes:
    """Download at most ``limit`` bytes. ``public``: GitHub release hosts only, no headers sent."""
    require_https(url)
    if public:
        try:
            trust.check_url(url)
        except trust.TrustError as exc:
            raise UpdateError(str(exc)) from exc
        headers = None
    context = ssl.create_default_context()
    if ca_file:
        context.load_verify_locations(ca_file)
    redirect = _AllowlistRedirect() if public else _HttpsRedirect()
    opener = urllib.request.build_opener(redirect, urllib.request.HTTPSHandler(context=context))
    request_headers = {"User-Agent": "FlightTracker-Updater"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with opener.open(request, timeout=timeout) as response:
            chunks: list[bytes] = []
            total = 0
            length: int | None = None
            try:
                length = int(response.headers.get("Content-Length") or 0) or None
            except (TypeError, ValueError, AttributeError):
                length = None
            if progress is not None:
                progress(0, length)
            while True:
                block = response.read(65536)
                if not block:
                    break
                total += len(block)
                if total > limit:
                    raise UpdateError("Download is larger than the allowed update size")
                chunks.append(block)
                if progress is not None:
                    progress(total, length)
    except UpdateError:
        raise
    except urllib.error.HTTPError as exc:
        _github_http_error(url, exc)
        raise UpdateError(f"Could not download {url}") from exc
    except Exception as exc:
        raise UpdateError(f"Could not download {url}") from exc
    return b"".join(chunks)


def token_path(config_path: Path) -> Path:
    """Where 1.0.0-1.0.6 kept a GitHub token. 1.0.7 never reads it; --harden deletes it."""
    return config_path.with_name(TOKEN_NAME)


def read_nofollow(path: Path, limit: int = 4 * MB) -> bytes:
    """Read a file without following a symlink planted in a writable folder."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as handle:
        return handle.read(limit)


def atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    """Write via a fresh O_EXCL temp file and rename, so a planted symlink is never followed.

    When root writes into a folder the service account owns, the file is
    handed to the folder's owner so the server can keep updating it.
    """
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(temporary, mode)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            folder = os.lstat(path.parent)
            os.chown(temporary, folder.st_uid, folder.st_gid)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def load_keyring(explicit: Path | None, root: Path, state: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Pinned public keys. Root-owned KEYS_DIR wins; before --harden the 1.0.6 key file is used."""
    revoked = (state or {}).get("revoked") or []
    nowhere = Path("/nonexistent-flight-tracker-keys")
    if explicit is not None and explicit.is_file():
        return trust.load_keyring(nowhere, legacy=explicit, revoked=revoked)
    if KEYS_DIR.is_dir() and any(KEYS_DIR.glob("*.pem")):
        ring = trust.load_keyring(KEYS_DIR, revoked=revoked)
    else:
        ring = trust.load_keyring(nowhere, legacy=load_public_key(None, root), revoked=revoked)
    if not ring:
        raise UpdateError("No update public key is installed")
    return ring


def ring_fingerprints(ring: dict[str, dict[str, Any]]) -> list[str]:
    return [trust.fingerprint(kid) for kid in sorted(ring) if "release" in ring[kid]["roles"]]


def read_trust_state(state_dir: Path | None = None) -> dict[str, Any]:
    path = (state_dir or STATE_DIR) / "update-trust.json"
    try:
        body = json.loads(read_nofollow(path, 256 * 1024).decode("utf-8"))
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def write_trust_state(state: dict[str, Any], state_dir: Path | None = None) -> bool:
    folder = state_dir or STATE_DIR
    if not folder.is_dir() or not os.access(folder, os.W_OK):
        return False
    atomic_write(folder / "update-trust.json", (json.dumps(state, indent=2) + "\n").encode("utf-8"))
    return True


def update_source(updates: dict[str, Any]) -> tuple[str, str, str]:
    """(repo, channel, manifest_url). Old private/default URLs move to the public repo."""
    url = str(updates.get("url") or "").strip()
    repo = str(updates.get("repo") or "").strip()
    channel = str(updates.get("channel") or trust.DEFAULT_CHANNEL)
    if not repo and (not url or url in (LEGACY_PRIVATE_URL, PUBLIC_MANIFEST_URL) or "/flight-tracker-updates/" in url):
        repo = PUBLIC_REPO
    if repo:
        return repo, channel, trust.latest_manifest_url(repo)
    return "", channel, url


def read_version_file(root: Path) -> str:
    path = root / "VERSION"
    if not path.is_file():
        return "0.0.0"
    text = path.read_text(encoding="utf-8").strip()
    try:
        return version_text(text)
    except UpdateError:
        return "0.0.0"


def installed_version(root: Path) -> str:
    current = root / "current"
    if current.is_symlink() or current.is_dir():
        return read_version_file(current)
    return read_version_file(root)


def pack_tree(source: Path, dest: Path) -> None:
    """Pack a release tree. Skips git metadata, caches, and local secrets."""
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "release-out"}
    skip_files = {"config.json", "hotspot.json", "auth.json", "activity", "update-status.json", "update-token", ".DS_Store"}
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, "w:gz") as archive:
        for path in sorted(source.rglob("*")):
            rel = path.relative_to(source)
            if any(part in skip_dirs or part.startswith("previews_") for part in rel.parts):
                continue
            if path.name in skip_files or path.suffix == ".key":
                continue
            archive.add(path, arcname=str(rel), recursive=False)


def safe_extract(archive_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        try:
            trust.check_members(archive.getmembers())
        except trust.TrustError as exc:
            raise UpdateError(str(exc)) from exc
        for member in archive.getmembers():
            name = member.name
            parts = Path(name).parts
            if name.startswith("/") or ".." in parts or member.issym() or member.islnk():
                raise UpdateError("Archive contains an unsafe path")
        archive.extractall(dest, filter="data")


def switch_current(root: Path, release: Path) -> None:
    link = root / "current"
    temporary = root / f".current-{os.getpid()}"
    if temporary.is_symlink() or temporary.exists():
        temporary.unlink()
    temporary.symlink_to(Path("releases") / release.name)
    os.replace(temporary, link)


def prune_releases(root: Path, keep: int = 2) -> None:
    folder = root / "releases"
    if not folder.is_dir():
        return
    current = (root / "current").resolve() if (root / "current").exists() else None
    found: list[Path] = []
    for child in folder.iterdir():
        if child.is_dir() and VERSION_RE.fullmatch(child.name):
            found.append(child)
    found.sort(key=lambda path: parse_version(path.name))
    retain: set[Path] = set()
    if current is not None:
        retain.add(current)
    for path in reversed(found):
        if len(retain) >= keep:
            break
        retain.add(path.resolve())
    for path in found:
        if path.resolve() not in retain:
            shutil.rmtree(path)


def _status_path(config_path: Path) -> Path:
    return config_path.with_name("update-status.json")


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_status(config_path: Path, body: dict[str, Any]) -> None:
    path = _status_path(config_path)
    body = dict(body)
    body.setdefault("updatedAt", _utc_now())
    body["updatedEpoch"] = time.time()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, (json.dumps(body, indent=2) + "\n").encode("utf-8"))


def read_status(config_path: Path) -> dict[str, Any]:
    path = _status_path(config_path)
    if not path.is_file():
        return {}
    try:
        body = json.loads(read_nofollow(path, 1024 * 1024).decode("utf-8"))
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def activity_age(config_path: Path, now: float | None = None) -> float | None:
    path = config_path.with_name("activity")
    if not path.is_file():
        return None
    moment = now if now is not None else time.time()
    return max(0.0, moment - path.stat().st_mtime)


def auto_decision(auto: bool, now: datetime, idle_for: float | None) -> str:
    """Return 'ok' when an unattended install is allowed."""
    if not auto:
        return "auto-off"
    if now.hour not in NIGHT_HOURS:
        return "not-night"
    if idle_for is not None and idle_for < IDLE_SECONDS:
        return "in-use"
    return "ok"


def load_public_key(explicit: Path | None, root: Path) -> Path:
    if explicit is not None and explicit.is_file():
        return explicit
    baked = Path("/etc/flight-tracker/update-public.pem")
    if baked.is_file():
        return baked
    shipped = root / "deploy" / "update-public.pem"
    if shipped.is_file():
        return shipped
    raise UpdateError("No update public key is installed")


def _ring_of(public_key: Any) -> dict[str, dict[str, Any]]:
    if isinstance(public_key, dict):
        return public_key
    return trust.load_keyring(Path("/nonexistent-flight-tracker-keys"), legacy=Path(public_key))


def check_public(
    repo: str,
    ring: dict[str, dict[str, Any]],
    current: str,
    *,
    channel: str = trust.DEFAULT_CHANNEL,
    state: dict[str, Any] | None = None,
    ca_file: str | None = None,
    fetch: Callable[..., bytes] | None = None,
) -> dict[str, Any]:
    """Anonymous check of the public repo's latest format-2 manifest (no API, no token)."""
    url = trust.latest_manifest_url(repo)
    if fetch is None:
        raw = fetch_bytes(url, MANIFEST_LIMIT, ca_file=ca_file, public=True)
    else:
        raw = fetch(url, MANIFEST_LIMIT)
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("Manifest is not JSON") from exc
    try:
        # Version order is judged below so "already current" is not an error.
        verified = trust.verify(document, ring, current="0.0", state=state, channel=channel, repo=repo)
    except trust.TrustError as exc:
        raise UpdateError(str(exc)) from exc
    return {
        "current": current,
        "version": verified["version"],
        "notes": verified["notes"],
        "available": parse_version(verified["version"]) > parse_version(current),
        "sha256": verified["sha256"],
        "size": verified["size"],
        "url": verified["url"],
        "downloadUrl": verified["url"],
        "source": "public",
        "manifest": verified,
    }


def check_for_update(
    manifest_url: str,
    public_key: Any,
    current: str,
    ca_file: str | None = None,
    token: str = "",
    *,
    repo: str = "",
    channel: str = trust.DEFAULT_CHANNEL,
    state: dict[str, Any] | None = None,
    fetch: Callable[..., bytes] | None = None,
) -> dict[str, Any]:
    """``repo`` set: the public GitHub channel (format 2 only). Otherwise a
    self-hosted HTTPS manifest URL (format 1, for development and private
    mirrors). ``token`` is accepted for old callers and ignored."""
    if repo:
        return check_public(repo, _ring_of(public_key), current, channel=channel, state=state, ca_file=ca_file, fetch=fetch)
    if urllib.parse.urlsplit(manifest_url).hostname == "api.github.com":
        raise UpdateError("Updates now come from the public repo. Set updates.repo (the setup page does this on save).")
    raw = fetch_bytes(manifest_url, MANIFEST_LIMIT, ca_file=ca_file)
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("Manifest is not JSON") from exc
    if isinstance(public_key, dict):
        keys = [entry["path"] for entry in public_key.values()]
    else:
        keys = [Path(public_key)]
    verified: dict[str, str] | None = None
    last: UpdateError | None = None
    for key in keys:
        try:
            verified = verify_manifest(document, key)
            break
        except UpdateError as exc:
            last = exc
    if verified is None:
        raise last or UpdateError("Manifest signature does not match the installed public key")
    newer = parse_version(verified["version"]) > parse_version(current)
    return {
        "current": current,
        "version": verified["version"],
        "notes": verified["notes"],
        "available": newer,
        "sha256": verified["sha256"],
        "url": verified["url"],
        "downloadUrl": verified["url"],
        "source": "url",
    }


def _run_migration(release: Path, config_path: Path) -> None:
    script = release / "server" / "migrate.py"
    if not script.is_file() or not config_path.is_file():
        return
    result = subprocess.run(
        [sys.executable, str(script), "--config", str(config_path)],
        check=False,
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise UpdateError(detail or "Config migration failed")


def _wait_healthy(health_url: str, version: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as response:
                body = json.loads(response.read(4096).decode("utf-8"))
            if isinstance(body, dict) and body.get("ok") is True and body.get("version") == version:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def systemd_restart(_current: Path) -> None:
    result = subprocess.run(
        ["systemctl", "restart", "flight-tracker.service"],
        check=False,
        capture_output=True,
        timeout=40,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise UpdateError(detail or "Could not restart flight-tracker.service")


def download_text(version: str, received: int, total: int | None) -> str:
    """'Downloading Version 1.0.4 (18 / 71 MB)...' for the Software card."""
    got = received // MB
    if total:
        return f"Downloading Version {version} ({got} / {max(1, round(total / MB))} MB)..."
    if received:
        return f"Downloading Version {version} ({got} MB)..."
    return f"Downloading Version {version}..."


class _Stages:
    """Writes the live install milestones to update-status.json."""

    def __init__(self, config_path: Path, current: str) -> None:
        self.config_path = config_path
        self.current = current
        self.target = ""
        self.notes = ""
        self._last_write = 0.0

    def write(self, stage: str, step: int, detail: str, **extra: Any) -> None:
        body: dict[str, Any] = {
            "state": "installing",
            "stage": stage,
            "step": step,
            "steps": INSTALL_STEPS,
            "target": self.target,
            "current": self.current,
            "version": self.target,
            "notes": self.notes,
            "available": True,
            "error": "",
            "detail": detail,
            "checkedAt": _utc_now(),
        }
        body.update(extra)
        write_status(self.config_path, body)
        self._last_write = time.monotonic()

    def downloading(self, received: int, total: int | None) -> None:
        done = total is not None and received >= total
        # Every half second is plenty for the card's 1.5 s poll.
        if received and not done and time.monotonic() - self._last_write < 0.5:
            return
        self.write("downloading", 2, download_text(self.target, received, total), received=received, total=total or 0)


def refresh_wrapper(release: Path, wrapper: Path = WRAPPER_PATH) -> bool:
    """Copy the new release's root update helper over the installed one (root only)."""
    source = release / "deploy" / "flight-tracker-update"
    try:
        if not source.is_file() or not wrapper.is_file() or not os.access(wrapper, os.W_OK) or not os.access(wrapper.parent, os.W_OK):
            return False
        temporary = wrapper.with_name(f".{wrapper.name}.new")
        shutil.copyfile(source, temporary)
        temporary.chmod(0o755)
        os.replace(temporary, wrapper)
        return True
    except OSError:
        return False


# Plain helpers in deploy/ that must exist in /usr/local/sbin after an OTA, even
# if this unit never ran install.sh for this version. The update wrapper itself
# is handled by refresh_wrapper (it must already be present).
SBIN_HELPERS = ("flight-tracker-wifi", "flight-tracker-brightness", "flight-tracker-wifi-test")


def install_helper(release: Path, name: str, dest: Path) -> bool:
    """Copy deploy/<name> to dest, creating it if it is missing."""
    source = release / "deploy" / name
    try:
        if not source.is_file() or not dest.parent.is_dir() or not os.access(dest.parent, os.W_OK):
            return False
        if dest.exists() and not os.access(dest, os.W_OK):
            return False
        temporary = dest.with_name(f".{dest.name}.new")
        shutil.copyfile(source, temporary)
        temporary.chmod(0o755)
        os.replace(temporary, dest)
        return True
    except OSError:
        return False


def refresh_helpers(release: Path, sbin: Path = Path("/usr/local/sbin")) -> list[str]:
    """Install or refresh non-update sbin wrappers from the new release."""
    installed: list[str] = []
    for name in SBIN_HELPERS:
        if install_helper(release, name, sbin / name):
            installed.append(name)
    return installed


SYSTEM_UNIT_DIR = Path("/etc/systemd/system")
# Copied to the system unit directory on OTA so existing units pick up the
# 1.0.13 09:00 check timer (install.sh only runs on a first install).
SYSTEMD_UNITS = (
    "flight-tracker-update.service",
    "flight-tracker-update.timer",
    "flight-tracker-auto-update.service",
    "flight-tracker-auto-update.timer",
)
TIMER_UNITS = (
    "flight-tracker-update.timer",
    "flight-tracker-auto-update.timer",
)


def install_unit(release: Path, name: str, dest_dir: Path) -> bool:
    """Copy deploy/<name> into a systemd unit directory (mode 0644)."""
    source = release / "deploy" / name
    dest = dest_dir / name
    try:
        if not source.is_file() or not dest_dir.is_dir() or not os.access(dest_dir, os.W_OK):
            return False
        if dest.exists() and not os.access(dest, os.W_OK):
            return False
        temporary = dest.with_name(f".{dest.name}.new")
        shutil.copyfile(source, temporary)
        temporary.chmod(0o644)
        os.replace(temporary, dest)
        return True
    except OSError:
        return False


def refresh_systemd_units(
    release: Path,
    unit_dir: Path = SYSTEM_UNIT_DIR,
    *,
    run_systemctl: bool = True,
    systemctl: str | None = None,
    runtime_dir: Path | None = None,
) -> list[str]:
    """Install updated timer/service units, then daemon-reload and restart timers."""
    installed: list[str] = []
    for name in SYSTEMD_UNITS:
        if install_unit(release, name, unit_dir):
            installed.append(name)
    if not installed or not run_systemctl:
        return installed
    ctl = systemctl or shutil.which("systemctl")
    runtime = Path("/run/systemd/system") if runtime_dir is None else runtime_dir
    if not ctl or not runtime.is_dir():
        return installed
    try:
        subprocess.run([ctl, "daemon-reload"], check=False, capture_output=True, timeout=30)
        for timer in TIMER_UNITS:
            subprocess.run([ctl, "enable", timer], check=False, capture_output=True, timeout=30)
            subprocess.run([ctl, "restart", timer], check=False, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass
    return installed


def restart_kiosk() -> bool:
    """Reload the round screen into the new release. Best effort; no-op off the Pi."""
    if not shutil.which("systemctl") or not Path("/run/systemd/system").is_dir():
        return False
    try:
        known = subprocess.run(["systemctl", "cat", KIOSK_UNIT], check=False, capture_output=True, timeout=10)
        if known.returncode != 0:
            return False
        result = subprocess.run(["systemctl", "restart", KIOSK_UNIT], check=False, capture_output=True, timeout=30)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def apply_update(
    *,
    root: Path,
    config_path: Path,
    public_key: Any,
    manifest_url: str,
    token: str = "",
    ca_file: str | None = None,
    health_url: str = "http://127.0.0.1:8741/api/health",
    health_timeout: float = 60,
    restart: Callable[[Path], None] = systemd_restart,
    wrapper: Path = WRAPPER_PATH,
    kiosk_restart: Callable[[], Any] = restart_kiosk,
    repo: str = "",
    channel: str = trust.DEFAULT_CHANNEL,
    state_dir: Path | None = None,
    keys_dir: Path | None = None,
    fetch: Callable[..., bytes] | None = None,
) -> dict[str, Any]:
    """Download a signed release, switch to it, and roll back if it stays down.

    Every step is written to update-status.json (state "installing", stage
    checking -> downloading -> verifying -> restarting, step 1-4 of 4) so the
    Software card can show live progress, then "installed"/"complete" or
    "rolled-back"/"failed" (or "error"/"failed" when nothing was switched).
    """
    root.mkdir(parents=True, exist_ok=True)
    current = installed_version(root)
    stages = _Stages(config_path, current)
    stages.target = str(read_status(config_path).get("version") or "")
    stages.write("checking", 1, "Checking signed manifest...")
    try:
        trust_state = read_trust_state(state_dir) if repo else {}
        found = check_for_update(manifest_url, public_key, current, ca_file=ca_file, repo=repo, channel=channel, state=trust_state, fetch=fetch)
    except UpdateError as exc:
        _fail_status(config_path, current, "", "", str(exc), rolled_back=False)
        raise _recorded(exc)
    if not found["available"]:
        body = {
            "current": found["current"],
            "version": found["version"],
            "notes": found["notes"],
            "available": False,
            "state": "current",
            "stage": "complete",
            "target": "",
            "error": "",
            "detail": f"Already running the latest version, Version {found['current']}.",
            "checkedAt": _utc_now(),
        }
        write_status(config_path, body)
        return body
    stages.target = found["version"]
    stages.notes = found["notes"]

    archive = root / f".download-{found['version']}.tar.gz"
    staging = root / "releases" / f".{found['version']}.partial"
    try:
        download = str(found.get("downloadUrl") or found["url"])
        stages.downloading(0, None)
        if found.get("source") == "public":
            size = int(found["size"])
            if fetch is None:
                data = fetch_bytes(download, size, ca_file=ca_file, timeout=120, progress=stages.downloading, public=True)
            else:
                data = fetch(download, size)
            if len(data) != size:
                raise UpdateError("Download size does not match the signed manifest")
        else:
            data = fetch_bytes(download, TARBALL_LIMIT, ca_file=ca_file, timeout=120, progress=stages.downloading)
        archive.write_bytes(data)
        del data
        stages.write("verifying", 3, f"Verifying signature and checksum, unpacking Version {found['version']}...")
        digest = file_sha256(archive)
        if digest != found["sha256"]:
            raise UpdateError("Tarball sha256 does not match the signed manifest")
        releases = root / "releases"
        releases.mkdir(parents=True, exist_ok=True)
        final = releases / found["version"]
        if final.exists():
            raise UpdateError(f"Release {found['version']} is already unpacked")
        staging = releases / f".{found['version']}.partial"
        if staging.exists():
            shutil.rmtree(staging)
        safe_extract(archive, staging)
        if read_version_file(staging) != found["version"]:
            raise UpdateError("VERSION inside the tarball does not match the manifest")
        staging.rename(final)

        stages.write("restarting", 4, f"Switching to Version {found['version']} and restarting Flight Tracker...")
        previous = (root / "current").resolve() if (root / "current").exists() else None
        backup = _backup_path(config_path, state_dir)
        if config_path.is_file():
            atomic_write(backup, read_nofollow(config_path), 0o600)
        try:
            _run_migration(final, config_path)
            switch_current(root, final)
            restart(root / "current")
            if not _wait_healthy(health_url, found["version"], health_timeout):
                raise UpdateError(f"Update to Version {found['version']} failed.")
        except Exception as exc:
            if backup.is_file() and config_path.parent.is_dir():
                atomic_write(config_path, read_nofollow(backup), 0o644)
            if previous is not None and previous.exists():
                switch_current(root, previous)
                try:
                    restart(root / "current")
                    _wait_healthy(health_url, read_version_file(previous), health_timeout)
                except Exception:
                    pass
            elif (root / "current").is_symlink():
                (root / "current").unlink()
            if final.exists():
                shutil.rmtree(final, ignore_errors=True)
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            reason = str(exc) if isinstance(exc, UpdateError) else f"Update failed: {exc}"
            _fail_status(config_path, installed_version(root), found["version"], found["notes"], reason, rolled_back=True)
            raise _recorded(UpdateError(reason)) from exc

        prune_releases(root, keep=2)
        if found.get("source") == "public":
            _after_public_install(found["manifest"], state_dir, keys_dir)
        # The new release is healthy: take its root helper and reload the round screen.
        refresh_wrapper(final, wrapper)
        refresh_helpers(final, wrapper.parent)
        refresh_systemd_units(final)
        installed = {
            "current": found["version"],
            "version": found["version"],
            "notes": found["notes"],
            "available": False,
            "state": "installed",
            "stage": "complete",
            "target": "",
            "error": "",
            "installedAt": _utc_now(),
            "detail": f"Update complete. Now running Version {found['version']}.",
            "checkedAt": _utc_now(),
        }
        write_status(config_path, installed)
        try:
            kiosk_restart()
        except Exception:  # never undo a healthy install over the screen reload
            pass
        return installed
    except Exception as exc:
        if isinstance(exc, UpdateError) and getattr(exc, "recorded", False):
            raise
        # Download, checksum, or unpack failed before anything was switched.
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        reason = str(exc) if isinstance(exc, UpdateError) else f"Update failed: {exc}"
        _fail_status(config_path, installed_version(root), found["version"], found["notes"], reason, rolled_back=False)
        raise _recorded(UpdateError(reason)) from exc
    finally:
        archive.unlink(missing_ok=True)


def _backup_path(config_path: Path, state_dir: Path | None) -> Path:
    """Root keeps the pre-update config copy in its own folder, not the service account's."""
    folder = state_dir or STATE_DIR
    if config_path == SYSTEM_CONFIG and folder.is_dir() and os.access(folder, os.W_OK):
        return folder / "config.json.pre-update"
    return config_path.with_suffix(".json.pre-update")


def _after_public_install(verified: dict[str, Any], state_dir: Path | None, keys_dir: Path | None) -> None:
    """Raise the replay mark and rollback floor; apply a root-signed key change."""
    state = trust.record_seen(read_trust_state(state_dir), verified)
    write_trust_state(state, state_dir)
    folder = keys_dir or KEYS_DIR
    changes = verified.get("keys") or {}
    if not changes or not folder.is_dir() or not os.access(folder, os.W_OK):
        return
    for entry in changes.get("add") or []:
        role = str((entry or {}).get("role") or "")
        pem = str((entry or {}).get("pem") or "")
        if role not in ("release", "root") or "BEGIN PUBLIC KEY" not in pem:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "key.pem"
            probe.write_text(pem, encoding="ascii")
            try:
                kid = trust.key_id(probe)
            except trust.TrustError:
                continue
        atomic_write(folder / f"{role}-{kid}.pem", pem.encode("ascii"), 0o644)
    for kid in changes.get("revoke") or []:
        for path in folder.glob(f"*-{kid}.pem"):
            path.unlink(missing_ok=True)


def _recorded(exc: UpdateError) -> UpdateError:
    """Mark an error whose failure status is already written, so main() keeps it."""
    setattr(exc, "recorded", True)
    return exc


def _fail_status(config_path: Path, running: str, target: str, notes: str, reason: str, *, rolled_back: bool) -> None:
    detail = (
        f"Update failed and rolled back to Version {running}."
        if rolled_back
        else f"Update failed. Still running Version {running}."
    )
    write_status(
        config_path,
        {
            "current": running,
            "version": target,
            "notes": notes,
            "available": bool(target) and parse_version(target) > parse_version(running),
            "state": "rolled-back" if rolled_back else "error",
            "stage": "failed",
            "target": "",
            "error": reason,
            "detail": detail,
            "checkedAt": _utc_now(),
        },
    )


def record_check(config_path: Path, found: dict[str, Any], error: str = "") -> dict[str, Any]:
    body = {
        "current": found.get("current", ""),
        "version": found.get("version", ""),
        "notes": found.get("notes", ""),
        "available": bool(found.get("available")),
        "state": "available" if found.get("available") else "current",
        "stage": "",
        "target": "",
        "detail": "",
        "error": error,
        "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if error:
        body["state"] = "error"
        body["available"] = False
    write_status(config_path, body)
    return body


def run_auto(config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    updates = config.get("updates") if isinstance(config, dict) else None
    auto = bool(updates.get("auto")) if isinstance(updates, dict) else False
    decision = auto_decision(auto, datetime.now(), activity_age(kwargs["config_path"]))
    if decision != "ok":
        status = read_status(kwargs["config_path"])
        status["state"] = decision
        write_status(kwargs["config_path"], status)
        return status
    repo, channel, url = update_source(updates if isinstance(updates, dict) else {})
    kwargs.pop("token", None)
    return apply_update(manifest_url=url, repo=repo, channel=channel, **kwargs)


def _harden_module() -> Any:
    try:
        import harden
    except ImportError:
        from server import harden
    return harden


def main() -> None:
    parser = argparse.ArgumentParser(description="Check or install a signed Flight Tracker update")
    parser.add_argument("--root", default=os.environ.get("FLIGHT_TRACKER_ROOT", "/opt/flight-tracker"))
    parser.add_argument("--config", default=os.environ.get("FLIGHT_TRACKER_CONFIG", "/etc/flight-tracker/config.json"))
    parser.add_argument("--public-key", default=os.environ.get("FLIGHT_TRACKER_UPDATE_KEY", ""))
    parser.add_argument("--ca", default=os.environ.get("FLIGHT_TRACKER_UPDATE_CA", ""))
    parser.add_argument("--health-url", default="http://127.0.0.1:8741/api/health")
    parser.add_argument("--health-timeout", type=float, default=60)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--install", action="store_true")
    group.add_argument("--auto", action="store_true")
    group.add_argument("--harden", action="store_true", help="Move the server to its own service account (root, once)")
    args = parser.parse_args()

    root = Path(args.root)
    config_path = Path(args.config)
    if args.harden:
        result = _harden_module().harden(health_url=args.health_url, health_timeout=args.health_timeout)
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result.get("ok") else 1)
    try:
        config = json.loads(read_nofollow(config_path).decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Could not read config: {exc}") from exc
    updates = config.get("updates") if isinstance(config, dict) else None
    if not isinstance(updates, dict):
        updates = {}
    repo, channel, manifest_url = update_source(updates)
    if not manifest_url:
        raise SystemExit("updates.url is not set")
    key_arg = Path(args.public_key) if args.public_key else None
    try:
        if args.auto and hasattr(os, "geteuid") and os.geteuid() == 0 and config_path == SYSTEM_CONFIG:
            # 1.0.7: the nightly run finishes the one-time service-account move if it is still due.
            try:
                hardened = _harden_module().harden_if_needed(health_url=args.health_url, health_timeout=args.health_timeout)
                if hardened:
                    print(json.dumps(hardened, indent=2))
            except Exception as exc:  # never block updates on it
                print(f"Service account move skipped: {exc}", file=sys.stderr)
        state = read_trust_state()
        ring = load_keyring(key_arg, root if (root / "deploy").is_dir() else Path(__file__).resolve().parent.parent, state)
        ca = args.ca or None
        common = dict(root=root, config_path=config_path, public_key=ring, ca_file=ca,
                      health_url=args.health_url, health_timeout=args.health_timeout)
        if args.auto:
            result = run_auto(config, **common)
        elif args.install:
            result = apply_update(manifest_url=manifest_url, repo=repo, channel=channel, **common)
        else:
            current = installed_version(root)
            found = check_for_update(manifest_url, ring, current, ca_file=ca, repo=repo, channel=channel, state=state)
            found.pop("manifest", None)
            result = record_check(config_path, found)
    except UpdateError as exc:
        if not getattr(exc, "recorded", False):
            record_check(config_path, {"current": installed_version(root), "available": False}, str(exc))
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
