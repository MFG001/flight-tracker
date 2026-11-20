"""No personal data in the source tree, a freshly packed release, or release notes."""
from __future__ import annotations

import hashlib
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import scrub_check  # noqa: E402
from server.updater import pack_tree  # noqa: E402


class ScrubTests(unittest.TestCase):
    def test_tree_is_clean(self) -> None:
        self.assertEqual(scrub_check.scan_tree(ROOT, frozenset()), [])

    def test_packed_release_is_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tarball = Path(tmp) / "flight-tracker-test.tar.gz"
            pack_tree(ROOT, tarball)
            self.assertEqual(scrub_check.scan_tarball(tarball, frozenset()), [])

    def test_rules_catch_each_kind(self) -> None:
        # Built at run time so this file itself stays clean.
        word = "zz" + "personal"
        extra = frozenset({hashlib.sha256(word.encode()).hexdigest()})
        samples = {
            "personal name/account/Wi-Fi word": f"hello {word.upper()}'s Pi",
            "private LAN address": "ssh pi@" + "192.168." + "77.5",
            "e-mail address": "mail " + "someone" + "@" + "gmail.com",
            "phone number": "call (" + "321) 555-" + "0100",
            "personal home folder": "/Users/" + "someone/Downloads",
        }
        for rule, text in samples.items():
            self.assertIn(rule, [r for _, r in scrub_check.findings_in(text, extra)], text)
        for fine in ["http://10.42.0.1/", "pi@flighttracker.local", "/home/pi/x", "noreply@users.noreply.github.com",
                     "squawk 7700", "ICAO a1b2c3 1.0.6 2026-11-20"]:
            self.assertEqual(scrub_check.findings_in(fine), [], fine)

    def test_built_in_words_are_hashes_only(self) -> None:
        self.assertTrue(all(len(h) == 64 for h in scrub_check.WORD_HASHES))
        self.assertGreaterEqual(len(scrub_check.WORD_HASHES), 6)

    def test_png_text_chunks_are_read(self) -> None:
        import struct
        import zlib

        def chunk(kind: bytes, body: bytes) -> bytes:
            return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"tEXt", b"Author\x00" + b"/Users/" + b"someone") + chunk(b"IEND", b"")
        self.assertEqual(len(scrub_check.scan_bytes("x.png", png, frozenset())), 1)

    def test_release_tools_run_the_check(self) -> None:
        for name in ("scripts/release.py", "tools/sign_release"):
            self.assertIn("scrub_or_exit(", (ROOT / name).read_text(), name)


if __name__ == "__main__":
    unittest.main()
