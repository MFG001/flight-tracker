"""Tokenless signed update channel (1.0.7 prototype, not wired in yet).

Releases come anonymously from a public GitHub repo. Nothing about the
download path is trusted: TLS and the host allowlist only keep the noise down.
Trust comes from Ed25519 signatures checked against keys pinned on the device.

Manifest format 2 (``manifest.json`` asset on each release)::

    {
      "format": 2,
      "product": "flight-tracker",
      "channel": "stable",
      "version": "1.0.8",
      "url": "https://github.com/MFG001/flight-tracker/releases/download/v1.0.8/flight-tracker-1.0.8.tar.gz",
      "sha256": "<64 hex>",
      "size": 1234567,
      "published": "2026-12-01T15:00:00Z",
      "expires": "",            # optional; empty = never
      "minVersion": "",         # optional signed rollback floor
      "notes": "What changed.",
      "keys": {"add": [{"role": "release", "pem": "..."}], "revoke": ["<keyId>"]},   # optional
      "signatures": [{"keyId": "<sha256 of the public key DER>", "sig": "<base64>"}]
    }

Signed bytes: ``flight-tracker-update-v2\\n`` + canonical JSON of every field
except ``signatures`` (sorted keys, no spaces, ASCII). So every field,
including notes and any key change, is covered.

Pinned keys live in a root-owned folder, ``/etc/flight-tracker-keys``:
``release-<keyId>.pem`` signs releases, ``root-<keyId>.pem`` (kept offline,
used only for key changes) must also sign any manifest that carries ``keys``.
The pre-1.0.7 ``/etc/flight-tracker/update-public.pem`` counts as both roles
until a root key is added.

Device state (root-owned ``/var/lib/flight-tracker/update-trust.json``):
highest ``published`` seen, rollback floor, revoked key ids.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import tarfile
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PRODUCT = "flight-tracker"
FORMAT = 2
PREFIX = b"flight-tracker-update-v2\n"
DEFAULT_CHANNEL = "stable"
# github.com serves releases/latest/download/<file> and releases/download/<tag>/<file>
# as 302s to the asset CDN. None of these count against the 60/hour API limit.
ALLOWED_HOSTS = frozenset({"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"})
TARBALL_LIMIT = 200 * 1024 * 1024
UNPACKED_LIMIT = 400 * 1024 * 1024
MEMBER_LIMIT = 20000
VERSION_RE = re.compile(r"^\d+(?:\.\d+){1,3}$")
KEYID_RE = re.compile(r"^[0-9a-f]{64}$")
REPO_RE = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
# A Pi 4 has no RTC: before NTP it can think it is 1970 or the last shutdown.
# Expiry is only enforced once the clock is past this.
SANE_CLOCK = datetime(2026, 11, 1, tzinfo=timezone.utc)


class TrustError(Exception):
    """The release was refused. Nothing was unpacked or run."""


def parse_version(value: Any) -> tuple[int, ...]:
    if not isinstance(value, str) or not VERSION_RE.fullmatch(value):
        raise TrustError("Version must look like 1.2.3")
    return tuple(int(part) for part in value.split("."))


def parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
        raise TrustError(f"Manifest {field} must look like 2026-12-01T15:00:00Z")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def latest_manifest_url(repo: str) -> str:
    """Anonymous direct download of the newest release's manifest (no API)."""
    if not REPO_RE.fullmatch(repo or ""):
        raise TrustError("Update repo must look like OWNER/NAME")
    return f"https://github.com/{repo}/releases/latest/download/manifest.json"


def check_url(url: str) -> None:
    """HTTPS, no credentials, no odd port, and only GitHub release hosts."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password:
        raise TrustError("Update URLs must be plain HTTPS")
    if parts.port not in (None, 443):
        raise TrustError("Update URLs must use the standard HTTPS port")
    if (parts.hostname or "").lower() not in ALLOWED_HOSTS:
        raise TrustError(f"Update host is not allowed: {parts.hostname}")


def release_url_ok(url: str, repo: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.hostname == "github.com" and parts.path.startswith(f"/{repo}/releases/download/v")


def key_id(pem_path: Path) -> str:
    result = subprocess.run(
        ["openssl", "pkey", "-pubin", "-in", str(pem_path), "-outform", "DER"],
        check=False, capture_output=True,
    )
    if result.returncode != 0 or not result.stdout:
        raise TrustError(f"Not a public key: {pem_path.name}")
    return hashlib.sha256(result.stdout).hexdigest()


def fingerprint(keyid: str) -> str:
    """Short form for the setup page and README: 2D7C 0580 0B69 E5EA."""
    return " ".join(keyid[i:i + 4].upper() for i in range(0, 16, 4))


def load_keyring(folder: Path, legacy: Path | None = None, revoked: Iterable[str] = ()) -> dict[str, dict[str, Any]]:
    """keyId -> {"path", "roles"}. Revoked ids are dropped."""
    ring: dict[str, dict[str, Any]] = {}
    gone = set(revoked)
    if folder.is_dir():
        for path in sorted(folder.glob("*.pem")):
            role = path.name.split("-", 1)[0]
            if role not in ("release", "root"):
                continue
            kid = key_id(path)
            ring.setdefault(kid, {"path": path, "roles": set()})["roles"].add(role)
    if legacy is not None and legacy.is_file():
        kid = key_id(legacy)
        entry = ring.setdefault(kid, {"path": legacy, "roles": set()})
        entry["roles"].add("release")
        if not any("root" in e["roles"] for e in ring.values() if e is not entry):
            entry["roles"].add("root")
    return {kid: entry for kid, entry in ring.items() if kid not in gone}


def signed_bytes(document: dict[str, Any]) -> bytes:
    body = {k: v for k, v in document.items() if k != "signatures"}
    return PREFIX + json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _verify(message: bytes, signature: bytes, pem: Path) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        msg, sig = Path(tmp) / "m", Path(tmp) / "s"
        msg.write_bytes(message)
        sig.write_bytes(signature)
        result = subprocess.run(
            ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(pem), "-rawin", "-in", str(msg), "-sigfile", str(sig)],
            check=False, capture_output=True,
        )
        return result.returncode == 0


def sign_document(document: dict[str, Any], private_key: Path, pub_pem: Path) -> dict[str, Any]:
    """Add one signature. Used by tools/sign_release with the existing offline key."""
    with tempfile.TemporaryDirectory() as tmp:
        msg, sig = Path(tmp) / "m", Path(tmp) / "s"
        msg.write_bytes(signed_bytes(document))
        result = subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-inkey", str(private_key), "-rawin", "-in", str(msg), "-out", str(sig)],
            check=False, capture_output=True,
        )
        if result.returncode != 0:
            raise TrustError("Signing failed")
        entry = {"keyId": key_id(pub_pem), "sig": base64.b64encode(sig.read_bytes()).decode("ascii")}
    signed = dict(document)
    signed["signatures"] = [s for s in document.get("signatures", []) if s.get("keyId") != entry["keyId"]] + [entry]
    return signed


def verify(
    document: Any,
    keyring: dict[str, dict[str, Any]],
    *,
    current: str,
    state: dict[str, Any] | None = None,
    channel: str = DEFAULT_CHANNEL,
    repo: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Check every property. Returns the verified manifest or raises TrustError."""
    state = state or {}
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise TrustError("Manifest is not format 2")
    if document.get("product") != PRODUCT:
        raise TrustError("Manifest is not for Flight Tracker")
    if document.get("channel") != channel:
        raise TrustError(f"Manifest is for channel {document.get('channel')!r}, not {channel!r}")

    # Signatures first: nothing else in the document is believed before this.
    message = signed_bytes(document)
    sigs = document.get("signatures")
    if not isinstance(sigs, list) or not sigs:
        raise TrustError("Manifest is not signed")
    roles: set[str] = set()
    for entry in sigs:
        if not isinstance(entry, dict):
            continue
        key = keyring.get(str(entry.get("keyId") or ""))
        if key is None:
            continue
        try:
            raw = base64.b64decode(str(entry.get("sig") or ""), validate=True)
        except (ValueError, TypeError):
            continue
        if _verify(message, raw, key["path"]):
            roles |= key["roles"]
    if "release" not in roles:
        raise TrustError("Manifest signature does not match a pinned key")
    if document.get("keys") not in (None, {}) and "root" not in roles:
        raise TrustError("Key changes must also be signed by the root key")

    version = str(document.get("version") or "")
    if parse_version(version) <= parse_version(current):
        raise TrustError(f"Refusing Version {version}: not newer than Version {current}")
    floor = str(state.get("floor") or "")
    if floor and parse_version(version) < parse_version(floor):
        raise TrustError(f"Refusing Version {version}: below the signed minimum {floor}")
    minimum = str(document.get("minVersion") or "")
    if minimum:
        parse_version(minimum)

    url = str(document.get("url") or "")
    check_url(url)
    if repo and not release_url_ok(url, repo):
        raise TrustError("Release file is not on the pinned GitHub repo")
    if not re.fullmatch(r"[0-9a-f]{64}", str(document.get("sha256") or "")):
        raise TrustError("Manifest sha256 is missing")
    size = document.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= TARBALL_LIMIT:
        raise TrustError("Manifest size is missing or too large")

    moment = now or datetime.now(timezone.utc)
    published = parse_time(document.get("published"), "published")
    last = state.get("lastPublished")
    if last and published < parse_time(last, "lastPublished"):
        raise TrustError("Manifest is older than one already seen (replay)")
    expires = document.get("expires") or ""
    if expires and moment >= SANE_CLOCK and moment > parse_time(expires, "expires"):
        raise TrustError("Manifest has expired")
    if not isinstance(document.get("notes"), str):
        raise TrustError("Manifest notes must be text")
    return dict(document)


def record_seen(state: dict[str, Any], verified: dict[str, Any]) -> dict[str, Any]:
    """After a verified install: raise the replay mark and rollback floor, note revocations."""
    out = dict(state)
    out["lastPublished"] = max(filter(None, [state.get("lastPublished"), verified["published"]]))
    floors = [v for v in (state.get("floor"), verified.get("minVersion")) if v]
    if floors:
        out["floor"] = max(floors, key=parse_version)
    revoked = set(state.get("revoked") or [])
    revoked |= {k for k in (verified.get("keys") or {}).get("revoke", []) if KEYID_RE.fullmatch(str(k))}
    out["revoked"] = sorted(revoked)
    return out


def check_members(members: Iterable[tarfile.TarInfo]) -> None:
    """Only plain files and folders, inside the release, no special bits, bounded size."""
    count = 0
    total = 0
    for member in members:
        count += 1
        if count > MEMBER_LIMIT:
            raise TrustError("Archive has too many files")
        name = member.name
        parts = Path(name).parts
        if not name or name.startswith(("/", "\\")) or ".." in parts or "\x00" in name or "\\" in name:
            raise TrustError("Archive contains an unsafe path")
        if not (member.isreg() or member.isdir()):
            raise TrustError("Archive contains a link or special file")
        if member.mode & 0o7000:
            raise TrustError("Archive contains setuid/setgid/sticky bits")
        total += max(0, member.size)
        if total > UNPACKED_LIMIT:
            raise TrustError("Archive unpacks too large")
