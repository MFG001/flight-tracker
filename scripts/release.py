#!/usr/bin/env python3
"""Build a signed Flight Tracker release.

The private key stays off the Pi and out of this repository. Pass it with
``--key`` or ``FLIGHT_TRACKER_RELEASE_KEY``. The script writes a tarball and
a manifest you can upload to the HTTPS host named by ``--base-url``.

Generate a key once, on a machine that is not the Pi::

    openssl genpkey -algorithm ED25519 -out flight-tracker-release.key
    chmod 600 flight-tracker-release.key
    openssl pkey -in flight-tracker-release.key -pubout -out deploy/update-public.pem

Install devices only after ``deploy/update-public.pem`` is your public key.
The copy baked into ``/etc/flight-tracker/update-public.pem`` is what every
later update must match.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.updater import build_manifest, file_sha256, pack_tree, read_version_file  # noqa: E402


def scrub_or_exit(tarball: Path, notes: str) -> None:
    """Refuse to sign a release that carries personal data (scripts/scrub_check.py)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import scrub_check  # noqa: E402

    found = scrub_check.scan_tarball(tarball, frozenset()) + scrub_check.scan_bytes("release notes", notes.encode(), frozenset())
    if found:
        raise SystemExit("Personal data found; not signing:\n  " + "\n  ".join(found))


def main() -> None:
    parser = argparse.ArgumentParser(description="Pack and sign a Flight Tracker update")
    parser.add_argument("--key", default=os.environ.get("FLIGHT_TRACKER_RELEASE_KEY", ""))
    parser.add_argument("--base-url", required=True, help="HTTPS directory where the tarball will be published, with no trailing file name")
    parser.add_argument("--notes", default="", help="Release notes. Defaults to NOTES.md or a one-line summary")
    parser.add_argument("--notes-file", default="")
    parser.add_argument("--out", default=str(ROOT / "release-out"))
    parser.add_argument("--version", default="")
    args = parser.parse_args()
    if not args.key:
        raise SystemExit("Set --key or FLIGHT_TRACKER_RELEASE_KEY to the Ed25519 private key. It must not live in the repo.")
    key = Path(args.key).expanduser().resolve()
    if not key.is_file():
        raise SystemExit(f"Private key not found: {key}")
    try:
        key.relative_to(ROOT)
    except ValueError:
        inside = False
    else:
        inside = True
    if inside:
        raise SystemExit("Refusing to sign with a private key stored inside the repository.")
    version = args.version.strip() or read_version_file(ROOT)
    if args.notes_file:
        notes = Path(args.notes_file).read_text(encoding="utf-8").strip()
    elif args.notes:
        notes = args.notes.strip()
    else:
        notes = f"Flight Tracker {version} by Maverick Field Gear."
    base = args.base_url.rstrip("/")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"flight-tracker-{version}.tar.gz"
    pack_tree(ROOT, archive)
    scrub_or_exit(archive, notes)
    digest = file_sha256(archive)
    url = f"{base}/flight-tracker-{version}.tar.gz"
    manifest = build_manifest(version, notes, url, digest, key)
    manifest_path = out / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {archive}")
    print(f"sha256 {digest}")
    print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()
