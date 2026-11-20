#!/usr/bin/env python3
"""Fail the build if personal data is in the tree, a release tarball, or release notes.

What is checked:
  * personal names, account names and Wi-Fi names, stored only as SHA-256 of
    the lower-case word (so this file does not itself leak them). Add more with
    --extra-hashes FILE (one sha256 per line, kept outside the repo);
  * private LAN addresses (10/8, 172.16/12, 192.168/16) other than the
    NetworkManager hotspot address 10.42.0.1;
  * e-mail addresses outside example/placeholder domains;
  * phone numbers (NNN-NNN-NNNN, (NNN) NNN-NNNN, NNN.NNN.NNNN, +1 ...);
  * home folders other than /home/pi (e.g. a Mac /Users/<name>).

Binary files are scanned too (PNG text chunks, EXIF), as raw bytes.

Usage:
  python3 scripts/scrub_check.py                 # files git would publish
  python3 scripts/scrub_check.py --tarball X.tar.gz --text "release notes" --file manifest.json
  python3 scripts/scrub_check.py --git-log        # commit messages and authors too
Exit 1 with a list of findings (file:line and the rule, never the matched word).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
WORD_HASHES = frozenset({
    "0d2c690e7dd5f94780383e9dfa1f4def044319104ad16ab15e45eeb2a8dfc81b",
    "0d05845a31cfa01390dee7a91fb7c8ee2590fcee7875fa9a80583e307f10e4f7",
    "c0f6da4ec9febb8e417732967c5b70665a4c92a4d2cff0f64a257a367650b8bf",
    "980057a51c0050f4d2f3721aa5e52a57c23cfde6b54d6d526ff6e5985a23c18b",
    "71dc62b10c43a9fa596f502e776639542343a517c5b5cd88d2f3923564fc659d",
    "3790d613ff80b4a579a97015a85632b078039f7831c18ffb7468b91d82b3a66b",
})
WORD = re.compile(r"[a-z0-9]+")
PRIVATE_IP = re.compile(r"(?<![\d.])(10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}(?![\d.])")
ALLOWED_IPS = {"10.42.0.1"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "flighttracker.local", "github.com", "users.noreply.github.com"}
PHONE = re.compile(r"(?<![\w.])(?:\+1[ .-]?)?(?:\(\d{3}\)\s?|\d{3}[-. ])\d{3}[-. ]\d{4}(?![\w.])")
HOME_DIR = re.compile(r"(?:/Users/|/home/)([A-Za-z0-9_.-]+)")
ALLOWED_HOMES = {"pi", "box", "user", "runner", "<user>", "you"}
SKIP_PARTS = {"node_modules", ".git"}


def findings_in(text: str, extra: frozenset[str] = frozenset()) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    hashes = WORD_HASHES | extra
    for number, line in enumerate(text.splitlines(), 1):
        for word in set(WORD.findall(line.lower())):
            if hashlib.sha256(word.encode()).hexdigest() in hashes:
                hits.append((number, "personal name/account/Wi-Fi word"))
        for match in PRIVATE_IP.finditer(line):
            if match.group(0) not in ALLOWED_IPS:
                hits.append((number, "private LAN address"))
        for match in EMAIL.finditer(line):
            domain = match.group(1).lower()
            if domain not in ALLOWED_EMAIL_DOMAINS and not domain.endswith(".example.com"):
                hits.append((number, "e-mail address"))
        if PHONE.search(line):
            hits.append((number, "phone number"))
        for match in HOME_DIR.finditer(line):
            if match.group(1).lower() not in ALLOWED_HOMES:
                hits.append((number, "personal home folder"))
    return hits


PRINTABLE = re.compile(rb"[\x20-\x7e]{8,}")


def png_text(data: bytes) -> bytes:
    """tEXt/iTXt/zTXt/eXIf chunks: where a screenshot tool puts names, paths and hosts."""
    import struct
    import zlib
    out: list[bytes] = []
    pos = 8
    while pos + 8 <= len(data):
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + size]
        if kind in (b"tEXt", b"iTXt", b"eXIf"):
            out.append(chunk.replace(b"\x00", b" "))
        elif kind == b"zTXt":
            key, _, rest = chunk.partition(b"\x00")
            try:
                out.append(key + b" " + zlib.decompress(rest[1:]))
            except zlib.error:
                out.append(key)
        pos += 12 + size
    return b"\n".join(out)


def text_of(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return png_text(data).decode("utf-8", errors="replace")
    if b"\x00" in data[:8192]:
        # Other binaries: only readable runs, like `strings`, so compressed noise stays quiet.
        return "\n".join(m.group(0).decode("ascii") for m in PRINTABLE.finditer(data))
    return data.decode("utf-8", errors="replace")


def scan_bytes(label: str, data: bytes, extra: frozenset[str]) -> list[str]:
    return [f"{label}:{line}: {rule}" for line, rule in findings_in(text_of(data), extra)]


def publish_files(root: Path) -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root, capture_output=True, check=True,
        ).stdout.decode().split("\0")
    except (OSError, subprocess.CalledProcessError):  # unpacked tarball, no git
        out = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()]
    files = [root / p for p in out if p and not SKIP_PARTS & set(Path(p).parts)
             and not any(part.startswith("previews_") or part == "release-out" for part in Path(p).parts)]
    files += [p for p in (root / "dist").rglob("*") if p.is_file()] if (root / "dist").is_dir() else []
    return sorted({p for p in files if p.is_file()})


def scan_tree(root: Path, extra: frozenset[str]) -> list[str]:
    found: list[str] = []
    for path in publish_files(root):
        found += scan_bytes(str(path.relative_to(root)), path.read_bytes(), extra)
    return found


def scan_tarball(path: Path, extra: frozenset[str]) -> list[str]:
    found: list[str] = []
    with tarfile.open(path, "r:*") as archive:
        for member in archive.getmembers():
            found += scan_bytes(f"{path.name}!{member.name}", member.name.encode(), extra)
            if member.isreg():
                handle = archive.extractfile(member)
                if handle is not None:
                    found += scan_bytes(f"{path.name}!{member.name}", handle.read(), extra)
    return found


def scan_git_log(root: Path, extra: frozenset[str]) -> list[str]:
    log = subprocess.run(["git", "log", "--all", "--format=%H%n%an <%ae>%n%cn <%ce>%n%B"], cwd=root, capture_output=True, text=True, check=True).stdout
    return scan_bytes("git-log", log.encode(), extra)


def load_extra(path: str) -> frozenset[str]:
    if not path:
        return frozenset()
    return frozenset(l.strip().lower() for l in Path(path).read_text().splitlines() if re.fullmatch(r"[0-9a-fA-F]{64}", l.strip()))


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--tarball", action="append", default=[])
    parser.add_argument("--file", action="append", default=[], help="extra file to scan, e.g. manifest.json")
    parser.add_argument("--text", action="append", default=[], help="extra text to scan, e.g. release notes")
    parser.add_argument("--git-log", action="store_true")
    parser.add_argument("--no-tree", action="store_true")
    parser.add_argument("--extra-hashes", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = Path(args.root)
    extra = load_extra(args.extra_hashes)
    found: list[str] = []
    if not args.no_tree:
        found += scan_tree(root, extra)
    for tarball in args.tarball:
        found += scan_tarball(Path(tarball), extra)
    for name in args.file:
        found += scan_bytes(name, Path(name).read_bytes(), extra)
    for index, text in enumerate(args.text):
        found += scan_bytes(f"text#{index + 1}", text.encode(), extra)
    if args.git_log:
        found += scan_git_log(root, extra)
    if found:
        print("Personal data found (fix before release):", file=sys.stderr)
        for line in found:
            print("  " + line, file=sys.stderr)
        return 1
    print("Scrub check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
