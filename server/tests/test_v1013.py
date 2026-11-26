"""1.0.13: 09:00 AM Eastern update check, mobile setup, cardinals outside the ring."""
from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

try:
    from server.tests.test_v103 import node_ts_ok, run_ts  # noqa: E402
except ImportError:
    from test_v103 import node_ts_ok, run_ts  # type: ignore  # noqa: E402

import update_schedule as us  # noqa: E402
import updater as up  # noqa: E402


class VersionPinTests(unittest.TestCase):
    def test_version_is_at_least_1013(self) -> None:
        # 1.0.14 moved on; test_v1014 pins the exact number.
        version = (ROOT / "VERSION").read_text().strip()
        self.assertGreaterEqual(tuple(int(x) for x in version.split(".")), (1, 0, 13))


class MorningCheckTimerTests(unittest.TestCase):
    def test_daily_check_is_at_nine_eastern_with_short_delay(self) -> None:
        timer = (ROOT / "deploy/flight-tracker-update.timer").read_text()
        service = (ROOT / "deploy/flight-tracker-update.service").read_text()
        self.assertIn("OnCalendar=*-*-* 09:00:00 America/New_York", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("RandomizedDelaySec=5min", timer)
        self.assertNotIn("RandomizedDelaySec=20min", timer)
        self.assertNotIn("03:10:00", timer)
        self.assertIn("ExecStart=/usr/local/sbin/flight-tracker-update --check", service)
        self.assertNotIn("--auto", service)

    def test_night_auto_install_timer_still_exists(self) -> None:
        timer = (ROOT / "deploy/flight-tracker-auto-update.timer").read_text()
        service = (ROOT / "deploy/flight-tracker-auto-update.service").read_text()
        self.assertIn("OnCalendar=*-*-* 03:10:00 America/New_York", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("RandomizedDelaySec=5min", timer)
        self.assertIn("ExecStart=/usr/local/sbin/flight-tracker-update --auto", service)
        # Quiet-hours install rules are unchanged.
        self.assertEqual(up.auto_decision(False, datetime(2026, 11, 15, 3, 0), 3600), "auto-off")
        self.assertEqual(up.auto_decision(True, datetime(2026, 11, 15, 15, 0), 3600), "not-night")
        self.assertEqual(up.auto_decision(True, datetime(2026, 11, 15, 3, 10), 30), "in-use")
        self.assertEqual(up.auto_decision(True, datetime(2026, 11, 15, 3, 10), 3600), "ok")

    def test_install_sh_enables_both_timers(self) -> None:
        text = (ROOT / "install.sh").read_text()
        self.assertIn("flight-tracker-auto-update.service", text)
        self.assertIn("flight-tracker-auto-update.timer", text)
        self.assertIn("systemctl enable flight-tracker-update.timer", text)
        self.assertIn("systemctl enable flight-tracker-auto-update.timer", text)
        self.assertIn("systemctl restart flight-tracker-auto-update.timer", text)


class SystemdRefreshTests(unittest.TestCase):
    def test_ota_copies_timer_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = Path(tmp) / "r"
            units = Path(tmp) / "systemd"
            (release / "deploy").mkdir(parents=True)
            units.mkdir()
            for name in up.SYSTEMD_UNITS:
                (release / "deploy" / name).write_text((ROOT / "deploy" / name).read_text())
            installed = up.refresh_systemd_units(release, units, run_systemctl=False)
            self.assertEqual(installed, list(up.SYSTEMD_UNITS))
            for name in up.SYSTEMD_UNITS:
                dest = units / name
                self.assertTrue(dest.is_file())
                self.assertEqual(dest.read_text(), (ROOT / "deploy" / name).read_text())
                self.assertEqual(dest.stat().st_mode & 0o777, 0o644)

    def test_ota_daemon_reloads_and_restarts_timers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = Path(tmp) / "r"
            units = Path(tmp) / "systemd"
            runtime = Path(tmp) / "run"
            (release / "deploy").mkdir(parents=True)
            units.mkdir()
            runtime.mkdir()
            for name in up.SYSTEMD_UNITS:
                (release / "deploy" / name).write_text((ROOT / "deploy" / name).read_text())
            calls: list[list[str]] = []

            def fake_run(argv, **kwargs):
                calls.append(list(argv))
                return mock.Mock(returncode=0, stdout=b"", stderr=b"")

            with mock.patch.object(up.subprocess, "run", fake_run):
                installed = up.refresh_systemd_units(
                    release, units, systemctl="/bin/systemctl", runtime_dir=runtime,
                )
            self.assertEqual(installed, list(up.SYSTEMD_UNITS))
            self.assertEqual(calls[0], ["/bin/systemctl", "daemon-reload"])
            actions = [tuple(c) for c in calls]
            for timer in up.TIMER_UNITS:
                self.assertIn(("/bin/systemctl", "enable", timer), actions)
                self.assertIn(("/bin/systemctl", "restart", timer), actions)

    def test_apply_update_calls_refresh_systemd_units(self) -> None:
        text = (ROOT / "server/updater.py").read_text()
        self.assertIn("refresh_systemd_units(final)", text)
        self.assertIn("refresh_helpers(final, wrapper.parent)", text)
        self.assertIn('subprocess.run([ctl, "daemon-reload"]', text)


class PromptWindowTests(unittest.TestCase):
    def test_background_check_is_deferred_at_night(self) -> None:
        day = datetime(2026, 11, 21, 14, 0, tzinfo=timezone.utc)   # 09:00 ET
        night = datetime(2026, 11, 21, 8, 10, tzinfo=timezone.utc)  # 03:10 ET
        self.assertTrue(us.prompt_check_open(day))
        self.assertFalse(us.prompt_check_open(night))
        self.assertFalse(us.prompt_check_open(datetime(2026, 11, 21, 13, 59, tzinfo=timezone.utc)))
        self.assertTrue(us.prompt_check_open(datetime(2026, 11, 22, 1, 59, tzinfo=timezone.utc)))  # 20:59 ET
        self.assertFalse(us.prompt_check_open(datetime(2026, 11, 22, 2, 0, tzinfo=timezone.utc)))   # 21:00 ET

    def test_scheduler_defers_overnight_and_checks_after_nine(self) -> None:
        # Reuse the 1.0.7 live-server fixture style only if imported; otherwise
        # just assert the source contains the deferral return.
        main = (ROOT / "server/flighttracker.py").read_text()
        self.assertIn("if not prompt_check_open(now, self._later_tz()):", main)
        self.assertIn('return "deferred"', main)
        self.assertNotIn("self._bg_checked_at = mono\n            if not prompt_check_open", main)


class TrafficClockTests(unittest.TestCase):
    def test_traffic_time_stays_at_the_1_0_12_layout(self) -> None:
        css = (ROOT / "src/style.css").read_text()
        self.assertIn("bottom: 12%;", css)
        self.assertNotIn("bottom: 13.6%;", css)
        self.assertNotIn("#clock { order: 4; }", css)
        self.assertIn("#clock { font-size: 13px; }", css)
        self.assertNotIn("font-size: 24px;", css)
        self.assertIn("#hud.standby #clock", css)
        self.assertIn("#hud.standby #status", css)
        self.assertIn("#hud.standby #metar", css)
        block = css[css.index("#hud.standby #status"):css.index("#hud.standby #metar") + 80]
        self.assertNotIn("#attrib", block)


class CompassCardinalTests(unittest.TestCase):
    def test_letters_sit_outside_the_tick_ring(self) -> None:
        radar = (ROOT / "src/radar.ts").read_text()
        self.assertIn("export function cardinalRadius", radar)
        self.assertIn("letterR * Math.sin(screen)", radar)
        self.assertNotIn("ringR - 18", radar)
        # Room between ticks (ringR+10) and the safe circle (safeR = ringR+28)
        # is enough, so the ring is not shrunk.
        self.assertIn("const ringR = Math.max(40, safeR - 28);", radar)
        self.assertIn('elementBox(["rangectl"]', radar)
        self.assertIn('elementBox(["status", "clock", "metar", "attrib"]', radar)

    @unittest.skipUnless(node_ts_ok(), "node with --experimental-strip-types not installed")
    def test_cardinal_radius_is_outside_ticks_and_inside_safe_circle(self) -> None:
        radar = (ROOT / "src/radar.ts").read_text()
        start = radar.index("export function cardinalRadius")
        end = radar.index("\n}\n", start) + 3
        body = radar[start:end].replace("export ", "").replace(": number", "")
        snippet = (
            "const safeR = 360 * 0.9;\n"
            "const ringR = Math.max(40, safeR - 28);\n"
            "const fontPx = 14;\n"
            "const r = cardinalRadius(ringR, safeR, fontPx);\n"
            "console.log(JSON.stringify({ ringR, safeR, r, tickOuter: ringR + 10, outerExtent: r + fontPx / 2 }));\n"
        )
        result = run_ts(body + snippet)
        self.assertGreater(result["r"], result["tickOuter"])
        self.assertLessEqual(result["outerExtent"], result["safeR"])
        # Well inside the 720px glass (radius 360).
        self.assertLess(result["outerExtent"], 360)


class SetupResponsiveTests(unittest.TestCase):
    def test_setup_page_has_mobile_layout_and_keeps_desktop_circles(self) -> None:
        html = (ROOT / "setup/index.html").read_text(encoding="utf-8")
        self.assertIn('name="viewport"', html)
        self.assertIn("width=device-width, initial-scale=1", html)
        self.assertIn("@media (max-width: 640px)", html)
        self.assertIn("min-height: 44px", html)
        self.assertIn("grid-template-columns: 1fr;", html)
        self.assertIn("overflow-wrap: anywhere", html)
        self.assertIn("#nets .net-name", html)
        self.assertIn("white-space: pre-wrap !important", html)
        # Desktop rules (before the phone query) stay circular.
        base = html.split("@media (max-width: 640px)")[0]
        self.assertIn("border-radius: 50%", base)
        self.assertIn("aspect-ratio: 1", base)
        self.assertIn("width: 68%", base)

    def test_setup_layouts_do_not_overflow_or_overlap_on_phones(self) -> None:
        chrome = os.environ.get("CHROME") or shutil.which("google-chrome") or shutil.which("google-chrome-stable")
        script = ROOT / "scripts" / "check-setup-responsive.mjs"
        if not chrome or not shutil.which("node") or not script.is_file():
            self.skipTest("Chrome and the setup responsive checker are required")
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
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
            if result.returncode != 0:
                self.fail(result.stdout + chr(10) + result.stderr)
            self.assertIn("setup responsive ok", result.stdout)
        finally:
            server.shutdown()
            server.server_close()


class DocsTests(unittest.TestCase):
    def test_docs_describe_nine_am_check(self) -> None:
        readme = (ROOT / "README.md").read_text()
        software = (ROOT / "docs/SOFTWARE.md").read_text()
        docs = (ROOT / "docs/tokenless-updates.md").read_text()
        self.assertIn("09:00 AM Eastern", software)
        self.assertIn("21:00 and 09:00 Eastern", software)
        self.assertNotIn("The timer runs at about 03:10.", readme)
        self.assertIn("09:00 AM Eastern daily check", docs)



class MapLabelTests(unittest.TestCase):
    def test_map_box_is_identifier_only(self) -> None:
        radar = (ROOT / "src/radar.ts").read_text()
        fmt = (ROOT / "src/format.ts").read_text()
        main = (ROOT / "src/main.ts").read_text()
        html = (ROOT / "index.html").read_text()
        self.assertIn("export function mapLabelIdent", fmt)
        self.assertIn("mapLabelIdent(aircraft)", radar)
        self.assertNotIn("dataBlockLine", radar)
        self.assertNotIn("draft.line2", radar)
        self.assertIn("const boxH = 20;", radar)
        # Icon is not a hit target; the padded label box is.
        self.assertIn("for (const hit of this.labelHits)", radar)
        self.assertIn("Math.max(0, (44 - vis.h) / 2)", radar)
        self.assertNotIn("this.spots", radar)
        # Traffic list and the detail card still carry the flight data.
        self.assertIn("name.textContent = row.item.callsign;", main)
        self.assertIn('["ALTITUDE", formatAltitude(item.altFt, item.ground, config.units)]', main)
        self.assertIn('["REG", item.registration || "—"]', main)
        self.assertIn("Tap the tail-number box for flight details.", html)
        # NAV still clears the selection.
        start = main.index('} else if (key === "NAV") {')
        block = main[start:start + 160]
        self.assertIn("selectedId = null", block)
        self.assertIn("detail.hidden = true", block)

    @unittest.skipUnless(node_ts_ok(), "node with --experimental-strip-types not installed")
    def test_map_label_ident_prefers_registration(self) -> None:
        data = run_ts("""
import { mapLabelIdent } from "./src/format.ts";
console.log(JSON.stringify([
  mapLabelIdent({ registration: "N12345", callsign: "AAL77", hex: "A061D9" }),
  mapLabelIdent({ registration: "  ", callsign: "AAL77", hex: "A061D9" }),
  mapLabelIdent({ registration: null, callsign: "----", hex: "ABC123" }),
  mapLabelIdent({ registration: null, callsign: "", hex: "", id: "x1" }),
]));
""")
        self.assertEqual(data, ["N12345", "AAL77", "ABC123", "x1"])


class CopyrightTests(unittest.TestCase):
    def test_copyright_is_on_the_glass_and_stays_in_standby(self) -> None:
        html = (ROOT / "index.html").read_text()
        css = (ROOT / "src/style.css").read_text()
        self.assertIn('id="copyright"', html)
        self.assertIn("© 2026 Maverick Field Gear", html)
        self.assertIn("#copyright {", css)
        self.assertIn("pointer-events: none", css[css.index("#copyright"):css.index("#copyright") + 400])
        # Standby hides the pills, not the credit or the copyright.
        block = css[css.index("#hud.standby #status"):css.index("#hud.standby #metar") + 80]
        self.assertNotIn("#copyright", block)
        self.assertNotIn("#attrib", block)


class RotorSpinTests(unittest.TestCase):
    def test_rotor_blades_spin_around_the_hub(self) -> None:
        icons = (ROOT / "src/icons.ts").read_text()
        radar = (ROOT / "src/radar.ts").read_text()
        self.assertIn("export function rotorAngle", icons)
        self.assertIn("export const ROTOR_RPS_AIR = 1;", icons)
        self.assertIn("export const ROTOR_RPS_GROUND = 0.25;", icons)
        self.assertIn("paintRotorBlades", icons)
        self.assertIn("ctx.rotate(angle)", icons)
        # Size is unchanged.
        self.assertIn("export const ROTOR_ICON_SCALE = 1.22;", icons)
        self.assertIn("rotorRad: rotorAngle(now, Boolean(aircraft.ground))", radar)
        # The fuselage path does not bake in a static blade cross.
        rotor = icons[icons.index("function drawMaverickRotor"):icons.index("function drawMaverickAirship")]
        self.assertNotIn("ctx.moveTo(-11, -1)", rotor)

    @unittest.skipUnless(node_ts_ok(), "node with --experimental-strip-types not installed")
    def test_rotor_angle_is_slower_on_the_ground(self) -> None:
        icons = (ROOT / "src/icons.ts").read_text()
        start = icons.index("export const ROTOR_RPS_AIR")
        start_fn = icons.index("export function rotorAngle")
        end = icons.index("\n}\n", start_fn) + 3
        body = icons[start:end].replace("export ", "").replace(": number", "").replace(": boolean", "")
        snippet = (
            "const t = 250;\n"
            "console.log(JSON.stringify({"
            " air: rotorAngle(t, false),"
            " ground: rotorAngle(t, true),"
            " airRps: ROTOR_RPS_AIR,"
            " groundRps: ROTOR_RPS_GROUND"
            "}));\n"
        )
        data = run_ts(body + snippet)
        import math
        self.assertEqual(data["airRps"], 1)
        self.assertEqual(data["groundRps"], 0.25)
        self.assertAlmostEqual(data["air"], 0.5 * math.pi, places=5)
        self.assertAlmostEqual(data["ground"], 0.125 * math.pi, places=5)
