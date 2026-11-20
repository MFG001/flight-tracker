"""Tokenless update channel prototype: every property of a format-2 manifest."""
from __future__ import annotations

import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import update_trust as ut  # noqa: E402

REPO = "MFG001/flight-tracker"
NOW = datetime(2026, 12, 2, tzinfo=timezone.utc)


def _key(folder: Path, name: str) -> tuple[Path, Path]:
    priv = folder / f"{name}.key"
    pub = folder / f"{name}.pub.pem"
    subprocess.check_call(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(priv)], stdout=subprocess.DEVNULL)
    subprocess.check_call(["openssl", "pkey", "-in", str(priv), "-pubout", "-out", str(pub)], stdout=subprocess.DEVNULL)
    return priv, pub


class TrustTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.rel_priv, cls.rel_pub = _key(base, "release")  # throwaway test keys only
        cls.root_priv, cls.root_pub = _key(base, "root")
        cls.evil_priv, cls.evil_pub = _key(base, "evil")
        cls.ring_dir = base / "update-keys"
        cls.ring_dir.mkdir()
        (cls.ring_dir / f"release-{ut.key_id(cls.rel_pub)}.pem").write_bytes(cls.rel_pub.read_bytes())
        (cls.ring_dir / f"root-{ut.key_id(cls.root_pub)}.pem").write_bytes(cls.root_pub.read_bytes())
        cls.ring = ut.load_keyring(cls.ring_dir)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def doc(self, **over):
        body = {
            "format": 2, "product": "flight-tracker", "channel": "stable", "version": "1.0.8",
            "url": f"https://github.com/{REPO}/releases/download/v1.0.8/flight-tracker-1.0.8.tar.gz",
            "sha256": "a" * 64, "size": 5_000_000, "published": "2026-12-01T15:00:00Z",
            "expires": "", "minVersion": "", "notes": "Notes.",
        }
        body.update(over)
        return body

    def signed(self, body, *keys):
        keys = keys or ((self.rel_priv, self.rel_pub),)
        for priv, pub in keys:
            body = ut.sign_document(body, priv, pub)
        return body

    def check(self, doc, **kw):
        kw.setdefault("current", "1.0.7")
        kw.setdefault("repo", REPO)
        kw.setdefault("now", NOW)
        return ut.verify(doc, self.ring, **kw)

    def test_good_manifest(self):
        self.assertEqual(self.check(self.signed(self.doc()))["version"], "1.0.8")

    def test_every_field_is_signed(self):
        good = self.signed(self.doc())
        for field, value in [("version", "1.0.9"), ("url", good["url"].replace("1.0.8.tar", "1.0.8x.tar")),
                             ("sha256", "b" * 64), ("size", 6), ("notes", "x"), ("channel", "stable"),
                             ("published", "2026-12-01T15:00:01Z"), ("expires", "2027-01-01T00:00:00Z"),
                             ("minVersion", "1.0.0")]:
            tampered = dict(good, **{field: value})
            if tampered == good:
                continue
            with self.assertRaises(ut.TrustError, msg=field):
                self.check(tampered)

    def test_unknown_key_and_unsigned(self):
        with self.assertRaisesRegex(ut.TrustError, "pinned key"):
            self.check(self.signed(self.doc(), (self.evil_priv, self.evil_pub)))
        with self.assertRaisesRegex(ut.TrustError, "not signed"):
            self.check(self.doc())

    def test_rollback_equal_and_floor(self):
        for current in ("1.0.8", "1.0.9"):
            with self.assertRaisesRegex(ut.TrustError, "not newer"):
                self.check(self.signed(self.doc()), current=current)
        with self.assertRaisesRegex(ut.TrustError, "minimum"):
            self.check(self.signed(self.doc()), current="1.0.0", state={"floor": "1.0.9"})

    def test_replay_and_expiry(self):
        doc = self.signed(self.doc())
        with self.assertRaisesRegex(ut.TrustError, "replay"):
            self.check(doc, state={"lastPublished": "2026-12-05T00:00:00Z"})
        old = self.signed(self.doc(expires="2026-12-01T20:00:00Z"))
        with self.assertRaisesRegex(ut.TrustError, "expired"):
            self.check(old)
        # A Pi with no RTC that still thinks it is 1970 is not locked out.
        self.check(old, now=datetime(1970, 1, 1, tzinfo=timezone.utc))

    def test_product_channel_binding(self):
        with self.assertRaises(ut.TrustError):
            self.check(self.signed(self.doc(product="other")))
        with self.assertRaisesRegex(ut.TrustError, "channel"):
            self.check(self.signed(self.doc(channel="beta")))

    def test_url_allowlist_and_repo_pin(self):
        for url in ["http://github.com/x", "https://evil.example/f.tar.gz", "https://user:pw@github.com/x",
                    "https://github.com:8443/x", "https://api.github.com/repos/x"]:
            with self.assertRaises(ut.TrustError, msg=url):
                ut.check_url(url)
        ut.check_url("https://release-assets.githubusercontent.com/github-production-release-asset/1")
        with self.assertRaisesRegex(ut.TrustError, "pinned GitHub repo"):
            self.check(self.signed(self.doc(url="https://github.com/someone/fork/releases/download/v1.0.8/f.tar.gz")))
        self.assertEqual(ut.latest_manifest_url(REPO), f"https://github.com/{REPO}/releases/latest/download/manifest.json")
        with self.assertRaises(ut.TrustError):
            ut.latest_manifest_url("../evil")

    def test_size_limit(self):
        for size in (0, -1, ut.TARBALL_LIMIT + 1, "5", True):
            with self.assertRaises(ut.TrustError):
                self.check(self.signed(self.doc(size=size)))

    def test_key_changes_need_root(self):
        rotate = self.doc(keys={"add": [], "revoke": ["c" * 64]})
        with self.assertRaisesRegex(ut.TrustError, "root key"):
            self.check(self.signed(rotate))
        both = self.signed(rotate, (self.rel_priv, self.rel_pub), (self.root_priv, self.root_pub))
        verified = self.check(both)
        state = ut.record_seen({}, verified)
        self.assertEqual(state["revoked"], ["c" * 64])
        self.assertEqual(state["lastPublished"], "2026-12-01T15:00:00Z")

    def test_revoked_key_is_dropped(self):
        ring = ut.load_keyring(self.ring_dir, revoked=[ut.key_id(self.rel_pub)])
        with self.assertRaises(ut.TrustError):
            ut.verify(self.signed(self.doc()), ring, current="1.0.7", now=NOW)

    def test_legacy_single_key_counts_as_both_roles(self):
        ring = ut.load_keyring(Path(self.tmp.name) / "missing", legacy=self.rel_pub)
        self.assertEqual(ring[ut.key_id(self.rel_pub)]["roles"], {"release", "root"})

    def test_shipped_key_fingerprint(self):
        pem = Path(__file__).resolve().parents[2] / "deploy" / "update-public.pem"
        self.assertEqual(ut.fingerprint(ut.key_id(pem)), "2D7C 0580 0B69 E5EA")

    def test_tar_members(self):
        def info(name, kind=tarfile.REGTYPE, mode=0o644, size=1):
            item = tarfile.TarInfo(name)
            item.type, item.mode, item.size = kind, mode, size
            return item
        ut.check_members([info("VERSION"), info("server", tarfile.DIRTYPE, 0o755, 0)])
        for bad in [info("/etc/passwd"), info("../x"), info("a/../../x"), info("l", tarfile.SYMTYPE),
                    info("h", tarfile.LNKTYPE), info("d", tarfile.CHRTYPE), info("f", tarfile.FIFOTYPE),
                    info("s", mode=0o4755), info("big", size=ut.UNPACKED_LIMIT + 1)]:
            with self.assertRaises(ut.TrustError, msg=bad.name):
                ut.check_members([bad])

    def test_real_release_tarball_passes(self):
        tarball = Path(__file__).resolve().parents[2] / "release-out" / "flight-tracker-1.0.6.tar.gz"
        if not tarball.is_file():
            self.skipTest("no local 1.0.6 tarball")
        with tarfile.open(tarball, "r:gz") as archive:
            ut.check_members(archive.getmembers())


if __name__ == "__main__":
    unittest.main()
