"""Kiosk boot: wait for the display server, clear stale Chromium state."""

from __future__ import annotations

import json
import socket
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _exe(folder: Path, name: str, body: str) -> None:
    path = folder / name
    path.write_text("#!/bin/bash\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class KioskBootTests(unittest.TestCase):
    def start_kiosk(
        self,
        *,
        wayland: bool = True,
        health_wait: str = "0",
        health_url: str | None = None,
        display_wait: str = "1",
        home: Path | None = None,
        extra_env: dict[str, str] | None = None,
        timeout: int = 20,
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(tmp)], check=False))
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        runtime = tmp / "run"
        runtime.mkdir()
        socks: list[socket.socket] = []
        if wayland:
            sock = socket.socket(socket.AF_UNIX)
            sock.bind(str(runtime / "wayland-0"))
            socks.append(sock)
        self.addCleanup(lambda: [s.close() for s in socks])
        _exe(bin_dir, "chromium", f'printf "%s\\n" "$@" > {tmp}/chrome-args\n')
        _exe(bin_dir, "wlr-randr", "true\n")
        (tmp / "config.json").write_text("{}", encoding="utf-8")
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "XDG_RUNTIME_DIR": str(runtime),
            "XDG_CONFIG_HOME": str((home or tmp) / ".config"),
            "FLIGHT_TRACKER_CONFIG": str(tmp / "config.json"),
            "FLIGHT_TRACKER_DISPLAY_WAIT": display_wait,
            "FLIGHT_TRACKER_HEALTH_WAIT": health_wait,
            "HOME": str(home or tmp),
        }
        if health_url:
            env["FLIGHT_TRACKER_HEALTH_URL"] = health_url
        if extra_env:
            env.update(extra_env)
        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "kiosk.sh")],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result, tmp

    def test_chromium_waits_until_health_answers(self) -> None:
        port = _free_port()
        ready = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if not ready.is_set() or self.path != "/api/health":
                    self.send_error(503)
                    return
                body = b'{"ok": true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                return

        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def _stop_server() -> None:
            server.shutdown()
            server.server_close()

        self.addCleanup(_stop_server)
        started = time.monotonic()

        def enable() -> None:
            time.sleep(1.5)
            ready.set()

        threading.Thread(target=enable, daemon=True).start()
        result, tmp = self.start_kiosk(
            health_wait="8",
            health_url=f"http://127.0.0.1:{port}/api/health",
            timeout=20,
        )
        elapsed = time.monotonic() - started
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreaterEqual(elapsed, 1.4)
        self.assertIn("http://127.0.0.1:8741/?kiosk=1", (tmp / "chrome-args").read_text())

    def test_chromium_is_not_opened_if_the_server_stays_down(self) -> None:
        result, tmp = self.start_kiosk(
            health_wait="1",
            health_url="http://127.0.0.1:9/api/health",
            timeout=15,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not answering", result.stderr)
        self.assertFalse((tmp / "chrome-args").exists())

    def test_missing_display_does_not_open_chromium(self) -> None:
        result, tmp = self.start_kiosk(wayland=False, health_wait="0", display_wait="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("desktop session is not up", result.stderr)
        self.assertFalse((tmp / "chrome-args").exists())

    def test_stale_chromium_lock_and_crash_state_are_cleared(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(tmp)], check=False))
        profile = tmp / ".config" / "chromium"
        default = profile / "Default"
        default.mkdir(parents=True)
        (profile / "SingletonLock").write_text("stale", encoding="utf-8")
        (profile / "SingletonSocket").write_text("", encoding="utf-8")
        (profile / "SingletonCookie").write_text("", encoding="utf-8")
        prefs = default / "Preferences"
        prefs.write_text(
            json.dumps({"profile": {"exited_cleanly": False, "exit_type": "Crashed"}, "keep": 1}),
            encoding="utf-8",
        )
        result, _ = self.start_kiosk(health_wait="0", home=tmp)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((profile / "SingletonLock").exists())
        self.assertFalse((profile / "SingletonSocket").exists())
        self.assertFalse((profile / "SingletonCookie").exists())
        data = json.loads(prefs.read_text(encoding="utf-8"))
        self.assertTrue(data["profile"]["exited_cleanly"])
        self.assertEqual(data["profile"]["exit_type"], "Normal")
        self.assertEqual(data["keep"], 1)


class BootUnitTests(unittest.TestCase):
    def test_display_server_does_not_wait_for_network_online(self) -> None:
        unit = (ROOT / "deploy/flight-tracker.service").read_text()
        self.assertNotIn("network-online.target", unit)
        self.assertIn("Restart=always", unit)
        self.assertIn("StartLimitIntervalSec=0", unit)

    def test_kiosk_unit_keeps_retrying(self) -> None:
        unit = (ROOT / "deploy/flight-tracker-kiosk.service").read_text()
        self.assertIn("Restart=always", unit)
        self.assertIn("StartLimitIntervalSec=0", unit)
        self.assertIn("After=flight-tracker.service graphical.target", unit)

    def test_boot_retries_are_in_the_display_script(self) -> None:
        main = (ROOT / "src/main.ts").read_text()
        self.assertIn("async function loadDisplay()", main)
        self.assertIn("window.setTimeout(() => void retry(), 2000)", main)
        self.assertIn("if (booted) splash.hidden = true", main)


if __name__ == "__main__":
    unittest.main()
