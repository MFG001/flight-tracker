"""Signed update install, health check, and automatic rollback."""

from __future__ import annotations

import json
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from server.updater import (
    UpdateError,
    apply_update,
    auto_decision,
    build_manifest,
    check_for_update,
    file_sha256,
    pack_tree,
    require_https,
    switch_current,
    verify_manifest,
)

GOOD_SERVE = """
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ver = Path(__file__).resolve().parents[1].joinpath("VERSION").read_text().strip()
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"ok": True, "version": ver}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, fmt, *args):
        return
ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
"""

BAD_SERVE = "import sys\nsys.exit(1)\n"

GOOD_MIGRATE = """
import json, sys
from pathlib import Path
path = Path(sys.argv[sys.argv.index("--config") + 1])
cfg = json.loads(path.read_text())
cfg["schema"] = 2
path.write_text(json.dumps(cfg))
"""

BAD_MIGRATE = """
import json, sys
from pathlib import Path
path = Path(sys.argv[sys.argv.index("--config") + 1])
cfg = json.loads(path.read_text())
cfg["schema"] = 9
cfg["home"]["name"] = "BROKEN"
path.write_text(json.dumps(cfg))
"""


class Store:
    files: dict[str, bytes] = {}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = Store.files.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class Supervisor:
    def __init__(self, port: int) -> None:
        self.port = port
        self.proc: subprocess.Popen[bytes] | None = None

    def restart(self, current: Path) -> None:
        self.stop()
        script = current / "bin" / "serve.py"
        self.proc = subprocess.Popen([sys.executable, str(script), str(self.port)])

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class UpdateFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.base = base
        cls.key = base / "release.key"
        cls.pub = base / "release.pub"
        cls.other_key = base / "other.key"
        subprocess.check_call(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(cls.key)], stdout=subprocess.DEVNULL)
        subprocess.check_call(["openssl", "pkey", "-in", str(cls.key), "-pubout", "-out", str(cls.pub)], stdout=subprocess.DEVNULL)
        subprocess.check_call(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(cls.other_key)], stdout=subprocess.DEVNULL)
        cert = base / "tls.crt"
        tls_key = base / "tls.key"
        subprocess.check_call(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", str(tls_key), "-out", str(cert),
                "-days", "2", "-nodes", "-subj", "/CN=127.0.0.1",
                "-addext", "subjectAltName=IP:127.0.0.1",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, tls_key)
        cls.httpd.socket = context.wrap_socket(cls.httpd.socket, server_side=True)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.health_port = _free_port()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def setUp(self) -> None:
        self.install = self.base / f"opt-{time.time_ns()}"
        self.install.mkdir()
        self.config_path = self.install / "config.json"
        self.supervisor = Supervisor(self.health_port)
        self.addCleanup(self.supervisor.stop)

    def manifest_url(self) -> str:
        return f"https://127.0.0.1:{self.port}/manifest.json"

    def publish(self, version: str, serve: str, migrate: str, notes: str) -> None:
        tree = self.base / f"tree-{version}-{time.time_ns()}"
        (tree / "bin").mkdir(parents=True)
        (tree / "server").mkdir()
        (tree / "VERSION").write_text(version + "\n", encoding="utf-8")
        (tree / "bin" / "serve.py").write_text(serve, encoding="utf-8")
        (tree / "server" / "migrate.py").write_text(migrate, encoding="utf-8")
        archive = self.base / f"flight-tracker-{version}.tar.gz"
        pack_tree(tree, archive)
        url = f"https://127.0.0.1:{self.port}/flight-tracker-{version}.tar.gz"
        manifest = build_manifest(version, notes, url, file_sha256(archive), self.key)
        Store.files["/manifest.json"] = (json.dumps(manifest) + "\n").encode("utf-8")
        Store.files[url.removeprefix(f"https://127.0.0.1:{self.port}")] = archive.read_bytes()

    def apply(self, timeout: float = 4) -> dict:
        return apply_update(
            root=self.install,
            config_path=self.config_path,
            public_key=self.pub,
            manifest_url=self.manifest_url(),
            ca_file=str(self.base / "tls.crt"),
            health_url=f"http://127.0.0.1:{self.health_port}/api/health",
            health_timeout=timeout,
            restart=self.supervisor.restart,
        )

    def write_config(self) -> None:
        self.config_path.write_text(
            json.dumps(
                {
                    "home": {"name": "HANGAR", "lat": 47.45, "lon": -122.3},
                    "schema": 1,
                    "updates": {"url": self.manifest_url(), "auto": False},
                }
            ),
            encoding="utf-8",
        )

    def test_install_keeps_config_then_broken_release_rolls_back(self) -> None:
        self.write_config()
        self.publish("1.0.0", GOOD_SERVE, GOOD_MIGRATE, "First release")
        first = self.apply()
        self.assertEqual(first["state"], "installed")
        self.assertEqual(json.loads(self.config_path.read_text())["home"]["name"], "HANGAR")
        self.assertEqual(json.loads(self.config_path.read_text())["schema"], 2)

        self.publish("1.1.0", GOOD_SERVE, GOOD_MIGRATE, "Range rings")
        second = self.apply()
        self.assertEqual(second["current"], "1.1.0")

        self.publish("1.2.0", GOOD_SERVE, GOOD_MIGRATE, "Night check")
        third = self.apply()
        self.assertEqual(third["state"], "installed")
        names = sorted(path.name for path in (self.install / "releases").iterdir() if path.is_dir())
        self.assertEqual(names, ["1.1.0", "1.2.0"])
        self.assertEqual((self.install / "current").resolve().name, "1.2.0")

        self.publish("1.3.0", BAD_SERVE, BAD_MIGRATE, "This build does not start")
        with self.assertRaises(UpdateError):
            self.apply(timeout=2)
        self.assertEqual((self.install / "current").resolve().name, "1.2.0")
        restored = json.loads(self.config_path.read_text())
        self.assertEqual(restored["home"]["name"], "HANGAR")
        self.assertEqual(restored["schema"], 2)
        self.assertFalse((self.install / "releases" / "1.3.0").exists())
        with urllib.request.urlopen(f"http://127.0.0.1:{self.health_port}/api/health", timeout=2) as response:
            health = json.loads(response.read().decode("utf-8"))
        self.assertEqual(health["version"], "1.2.0")
        status = json.loads((self.install / "update-status.json").read_text())
        self.assertEqual(status["state"], "rolled-back")

    def test_rejects_unsigned_wrong_key_http_and_bad_hash(self) -> None:
        with self.assertRaises(UpdateError):
            require_https("http://updates.example.com/manifest.json")
        with self.assertRaises(UpdateError):
            require_https("https://user:secret@updates.example.com/manifest.json")

        self.publish("1.4.0", GOOD_SERVE, GOOD_MIGRATE, "Notes stay signed")
        document = json.loads(Store.files["/manifest.json"])
        document["notes"] = "Tampered notes"
        with self.assertRaises(UpdateError):
            verify_manifest(document, self.pub)
        document = json.loads(Store.files["/manifest.json"])
        other = build_manifest(document["version"], document["notes"], document["url"], document["sha256"], self.other_key)
        with self.assertRaises(UpdateError):
            verify_manifest(other, self.pub)

        self.write_config()
        switch_current(self.install, _seed_release(self.install, "1.0.0"))
        self.publish("1.4.0", GOOD_SERVE, GOOD_MIGRATE, "Hash must match")
        path = "/flight-tracker-1.4.0.tar.gz"
        Store.files[path] = Store.files[path][:-1] + bytes([Store.files[path][-1] ^ 0x01])
        before = (self.install / "current").resolve().name
        with self.assertRaises(UpdateError) as caught:
            self.apply(timeout=2)
        self.assertIn("sha256", str(caught.exception))
        self.assertEqual((self.install / "current").resolve().name, before)

    def test_check_reports_newer_version_without_installing(self) -> None:
        self.publish("2.0.0", GOOD_SERVE, GOOD_MIGRATE, "Ready when you are")
        found = check_for_update(self.manifest_url(), self.pub, "1.0.0", ca_file=str(self.base / "tls.crt"))
        self.assertTrue(found["available"])
        self.assertEqual(found["notes"], "Ready when you are")
        self.assertFalse((self.install / "releases").exists())

    def test_sign_release_matches_the_manifest_the_updater_checks(self) -> None:
        archive = self.base / "flight-tracker-9.9.9.tar.gz"
        tree = self.base / "sign-tree"
        tree.mkdir()
        (tree / "VERSION").write_text("9.9.9\n", encoding="utf-8")
        pack_tree(tree, archive)
        script = Path(__file__).resolve().parents[2] / "tools" / "sign_release"
        subprocess.check_call(
            [sys.executable, str(script), "--key", str(self.key), "--public-key", str(self.pub),
             "--notes", "Signed in the test.", "--published", "2026-11-20T16:00:00Z", str(archive)],
            stdout=subprocess.DEVNULL,
        )
        # Format 1 for the private repo (what 1.0.6 units read).
        private = json.loads((archive.parent / "private" / "manifest.json").read_text(encoding="utf-8"))
        verified = verify_manifest(private, self.pub)
        self.assertEqual(verified["version"], "9.9.9")
        self.assertEqual(verified["notes"], "Signed in the test.")
        self.assertEqual(
            verified["url"],
            "https://github.com/MFG001/flight-tracker-updates/releases/download/v9.9.9/flight-tracker-9.9.9.tar.gz",
        )
        # Format 2 for the public repo (what 1.0.7+ units read).
        from server import update_trust as trust
        public = json.loads((archive.parent / "public" / "manifest.json").read_text(encoding="utf-8"))
        ring = trust.load_keyring(Path("/nonexistent"), legacy=self.pub)
        checked = trust.verify(public, ring, current="1.0.7", repo="MFG001/flight-tracker")
        self.assertEqual((checked["size"], checked["sha256"]), (archive.stat().st_size, file_sha256(archive)))
        self.assertEqual(checked["url"], "https://github.com/MFG001/flight-tracker/releases/download/v9.9.9/flight-tracker-9.9.9.tar.gz")
        self.assertEqual(checked["published"], "2026-11-20T16:00:00Z")
        refused = subprocess.run(
            [sys.executable, str(script), "--key", str(Path(__file__).resolve().parents[2] / "deploy" / "update-public.pem"), str(archive)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("inside the repository", refused.stderr)

    def test_old_private_api_url_is_not_used_and_no_token_is_read(self) -> None:
        # 1.0.7 is tokenless: the private releases API is never called, even with a token file present.
        self.config_path.with_name("update-token").write_text("github_pat_examplevalue1234\n")
        with self.assertRaises(UpdateError) as caught:
            check_for_update(
                "https://api.github.com/repos/MFG001/flight-tracker-updates/releases/latest",
                self.pub,
                "1.0.0",
                token="github_pat_examplevalue1234",
            )
        message = str(caught.exception)
        self.assertIn("public repo", message)
        self.assertNotIn("github_pat", message)
        from server import updater as up
        for gone in ("read_token", "write_token", "mask_token", "load_github_release", "download_github_asset"):
            self.assertFalse(hasattr(up, gone), gone)

    def test_shipped_public_key_is_the_release_key(self) -> None:
        pem = Path(__file__).resolve().parents[2].joinpath("deploy", "update-public.pem").read_text(encoding="utf-8")
        self.assertIn("MCowBQYDK2VwAyEAXkVMm1xYhCjPgtPJYGqmoGTyx6npCs0w32R2OGZXduU=", pem)

    def test_auto_update_waits_for_night_and_an_idle_display(self) -> None:
        self.assertEqual(auto_decision(False, datetime(2026, 11, 15, 3, 0), 3600), "auto-off")
        self.assertEqual(auto_decision(True, datetime(2026, 11, 15, 15, 0), 3600), "not-night")
        self.assertEqual(auto_decision(True, datetime(2026, 11, 15, 3, 10), 30), "in-use")
        self.assertEqual(auto_decision(True, datetime(2026, 11, 15, 3, 10), 3600), "ok")
        self.assertEqual(auto_decision(True, datetime(2026, 11, 15, 3, 10), None), "ok")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _seed_release(root: Path, version: str) -> Path:
    release = root / "releases" / version
    release.mkdir(parents=True)
    (release / "VERSION").write_text(version + "\n", encoding="utf-8")
    return release


if __name__ == "__main__":
    unittest.main()


class PublicUpdateFlowTest(UpdateFlowTest):
    """1.0.7: tokenless format-2 install from the public repo (downloads injected)."""

    REPO = "MFG001/flight-tracker"

    def setUp(self) -> None:
        super().setUp()
        self.files: dict[str, bytes] = {}
        self.fetched: list[tuple[str, int]] = []
        self.state_dir = self.install / "state"
        self.keys_dir = self.install / "keys"
        self.state_dir.mkdir()
        self.keys_dir.mkdir()

    def fetch(self, url: str, limit: int) -> bytes:
        self.fetched.append((url, limit))
        if url not in self.files:
            raise UpdateError(f"404 {url}")
        body = self.files[url]
        if len(body) > limit:
            raise UpdateError("Download is larger than allowed")
        return body

    def publish_public(self, version: str, serve: str = GOOD_SERVE, *, published: str, extra: dict | None = None, pad: bytes = b"") -> dict:
        from server import update_trust as trust
        tree = self.base / f"ptree-{version}-{time.time_ns()}"
        (tree / "bin").mkdir(parents=True)
        (tree / "server").mkdir()
        (tree / "VERSION").write_text(version + "\n", encoding="utf-8")
        (tree / "bin" / "serve.py").write_text(serve, encoding="utf-8")
        (tree / "server" / "migrate.py").write_text(GOOD_MIGRATE, encoding="utf-8")
        archive = self.base / f"pub-flight-tracker-{version}-{time.time_ns()}.tar.gz"
        pack_tree(tree, archive)
        url = f"https://github.com/{self.REPO}/releases/download/v{version}/flight-tracker-{version}.tar.gz"
        doc = {
            "format": 2, "product": "flight-tracker", "channel": "stable", "version": version, "url": url,
            "sha256": file_sha256(archive), "size": archive.stat().st_size, "published": published,
            "expires": "", "minVersion": "", "notes": f"Version {version}",
        }
        doc.update(extra or {})
        doc = trust.sign_document(doc, self.key, self.pub)
        self.files[trust.latest_manifest_url(self.REPO)] = json.dumps(doc).encode("utf-8")
        self.files[url] = archive.read_bytes() + pad
        return doc

    def apply_public(self, timeout: float = 4) -> dict:
        return apply_update(
            root=self.install, config_path=self.config_path, public_key=self.pub, manifest_url="",
            health_url=f"http://127.0.0.1:{self.health_port}/api/health", health_timeout=timeout,
            restart=self.supervisor.restart, repo=self.REPO, state_dir=self.state_dir,
            keys_dir=self.keys_dir, fetch=self.fetch, wrapper=self.install / "wrapper", kiosk_restart=lambda: None,
        )

    def test_public_install_records_state_refuses_replay_and_size_mismatch(self) -> None:
        self.write_config()
        self.publish_public("1.0.7", published="2026-11-20T12:00:00Z")
        result = self.apply_public()
        self.assertEqual(result["state"], "installed")
        self.assertEqual((self.install / "current").resolve().name, "1.0.7")
        state = json.loads((self.state_dir / "update-trust.json").read_text())
        self.assertEqual(state["lastPublished"], "2026-11-20T12:00:00Z")
        self.assertEqual(self.fetched[0][0], "https://github.com/MFG001/flight-tracker/releases/latest/download/manifest.json")
        self.assertEqual(self.fetched[1][1], len(self.files[self.fetched[1][0]]))  # limited to the signed size

        # Older (replayed) manifest for a newer version: refused before any download.
        self.publish_public("1.0.8", published="2026-11-19T12:00:00Z")
        self.fetched.clear()
        with self.assertRaises(UpdateError):
            self.apply_public()
        self.assertEqual(len(self.fetched), 1)
        self.assertEqual((self.install / "current").resolve().name, "1.0.7")

        # Extra bytes after the signed size: refused, nothing switched.
        self.publish_public("1.0.8", published="2026-11-21T12:00:00Z", pad=b"x")
        with self.assertRaises(UpdateError):
            self.apply_public()
        self.assertEqual((self.install / "current").resolve().name, "1.0.7")
        self.assertFalse((self.install / "releases" / "1.0.8").exists())

    def test_public_rollback_and_root_signed_key_add(self) -> None:
        from server import update_trust as trust
        self.write_config()
        self.publish_public("1.0.7", published="2026-11-20T12:00:00Z")
        self.apply_public()
        self.publish_public("1.0.8", BAD_SERVE, published="2026-11-21T12:00:00Z")
        with self.assertRaises(UpdateError):
            self.apply_public(timeout=2)
        self.assertEqual((self.install / "current").resolve().name, "1.0.7")
        self.assertEqual(json.loads((self.state_dir / "update-trust.json").read_text())["lastPublished"], "2026-11-20T12:00:00Z")

        other_pub = self.base / "other.pub"
        subprocess.check_call(["openssl", "pkey", "-in", str(self.other_key), "-pubout", "-out", str(other_pub)], stdout=subprocess.DEVNULL)
        pem = other_pub.read_text()
        self.publish_public("1.0.9", published="2026-11-22T12:00:00Z", extra={"keys": {"add": [{"role": "release", "pem": pem}]}})
        self.assertEqual(self.apply_public()["state"], "installed")
        self.assertTrue((self.keys_dir / f"release-{trust.key_id(other_pub)}.pem").is_file())

    def test_wrong_repo_url_in_signed_manifest_is_refused(self) -> None:
        self.write_config()
        doc = self.publish_public("1.0.7", published="2026-11-20T12:00:00Z")
        from server import update_trust as trust
        evil = dict(doc)
        evil.pop("signatures")
        evil["url"] = "https://github.com/someone/else/releases/download/v1.0.7/flight-tracker-1.0.7.tar.gz"
        self.files[trust.latest_manifest_url(self.REPO)] = json.dumps(trust.sign_document(evil, self.key, self.pub)).encode()
        with self.assertRaises(UpdateError):
            self.apply_public()
        self.assertFalse((self.install / "current").exists())


# Reuse the harness only; the format-1 tests already ran in UpdateFlowTest.
for _name in [n for n in dir(UpdateFlowTest) if n.startswith("test_")]:
    if _name not in PublicUpdateFlowTest.__dict__:
        setattr(PublicUpdateFlowTest, _name, None)
