"""On-device Wi-Fi keyboard stays inside the 720×720 round glass."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class WifiOskSourceTests(unittest.TestCase):
    def test_setup_page_has_circle_fitted_keyboard(self) -> None:
        html = (ROOT / "setup" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="ft-osk"', html)
        self.assertIn("function bindWifiOsk()", html)
        self.assertIn("function isDevicePanel()", html)
        self.assertIn('inputmode', html)
        self.assertIn('"none"', html)
        self.assertIn("wifi-ssid", html[html.index("function bindWifiOsk()") :])
        self.assertIn("wifi-pass", html[html.index("function bindWifiOsk()") :])
        # Do not fight the phone OS keyboard.
        self.assertIn("min >= 600", html)


class WifiOskLayoutTests(unittest.TestCase):
    def test_keys_fit_the_720_circle_and_stay_hidden_on_phones(self) -> None:
        chrome = os.environ.get("CHROME") or shutil.which("google-chrome") or shutil.which("google-chrome-stable")
        script = ROOT / "scripts" / "check-wifi-osk.mjs"
        if not chrome or not shutil.which("node") or not script.is_file():
            self.skipTest("Chrome and the Wi-Fi keyboard checker are required")

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(ROOT), **kwargs)

            def log_message(self, format, *args):
                return

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{port}/setup/index.html"
            env = dict(os.environ)
            env["CHROME"] = chrome
            result = subprocess.run(
                ["node", str(script), url],
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )
        finally:
            server.shutdown()
        if result.returncode != 0:
            self.fail((result.stdout or "") + (result.stderr or ""))
        self.assertIn("all", result.stdout)
        self.assertIn("keys sit inside the circle", result.stdout)


if __name__ == "__main__":
    unittest.main()
