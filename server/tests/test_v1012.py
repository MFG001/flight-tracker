"""1.0.12: kiosk credits stay on the glass; standby hides duplicate bottom pills; map locked on home."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

try:
    from server.tests.test_v103 import run_ts  # noqa: E402
except ImportError:
    from test_v103 import run_ts  # type: ignore  # noqa: E402


class VersionPinTests(unittest.TestCase):
    def test_version_is_at_least_1012(self) -> None:
        # 1.0.13 moved on; test_v1013 pins the exact number.
        version = (ROOT / "VERSION").read_text().strip()
        self.assertGreaterEqual(tuple(int(x) for x in version.split(".")), (1, 0, 12))
        self.assertEqual(json.loads((ROOT / "package.json").read_text())["version"], version)
        lock = json.loads((ROOT / "package-lock.json").read_text())
        self.assertEqual((lock["version"], lock["packages"][""]["version"]), (version, version))
        self.assertIn(f"FlightTracker/{version} ", (ROOT / "server/flighttracker.py").read_text())


class KioskCreditTests(unittest.TestCase):
    def test_glass_keeps_required_credit_wording(self) -> None:
        html = (ROOT / "index.html").read_text()
        css = (ROOT / "src/style.css").read_text()
        main = (ROOT / "src/main.ts").read_text()
        self.assertIn('id="attrib"', html)
        self.assertIn("https://www.esri.com/en-us/legal/terms/data-attributions", html)
        self.assertIn("https://adsb.fi/", html)
        self.assertIn("data from", html)
        # Esri and adsb.fi wording stay visible as text on the About sources list.
        self.assertIn("Powered by Esri", html)
        self.assertIn("open data (https://adsb.fi/)", html)
        self.assertIn("installKioskGuards(window)", main)
        self.assertIn("if (!kiosk && attrib instanceof HTMLAnchorElement)", main)
        self.assertIn("body.kiosk #attrib", css)
        self.assertIn("pointer-events: none", css)
        # The phone setup page may keep its links.
        setup = (ROOT / "setup/index.html").read_text()
        self.assertIn('href="https://www.esri.com/"', setup)
        self.assertIn('href="https://adsb.fi/"', setup)

    def test_local_href_and_window_open_rules(self) -> None:
        data = run_ts("""
import { isLocalHref, shouldBlockWindowOpen } from "./src/kioskguard.ts";
const base = "http://127.0.0.1:8741/?kiosk=1";
console.log(JSON.stringify({
  localAbs: isLocalHref("http://127.0.0.1:8741/setup/", base),
  localRel: isLocalHref("/setup/", base),
  localHash: isLocalHref("#menu", base),
  esri: isLocalHref("https://www.esri.com/en-us/legal/terms/data-attributions", base),
  adsb: isLocalHref("https://adsb.fi/", base),
  rain: isLocalHref("https://www.rainviewer.com/", base),
  js: isLocalHref("javascript:alert(1)", base),
  empty: isLocalHref("", base),
  blockEsri: shouldBlockWindowOpen("https://www.esri.com/en-us/legal/terms/data-attributions", base),
  blockBlank: shouldBlockWindowOpen("", base),
  blockNull: shouldBlockWindowOpen(null, base),
  allowLocal: shouldBlockWindowOpen("http://127.0.0.1:8741/", base),
}));
""")
        self.assertEqual(data, {
            "localAbs": True,
            "localRel": True,
            "localHash": True,
            "esri": False,
            "adsb": False,
            "rain": False,
            "js": False,
            "empty": False,
            "blockEsri": True,
            "blockBlank": True,
            "blockNull": True,
            "allowLocal": False,
        })

    def test_click_handler_and_window_open_override_are_installed(self) -> None:
        guard = (ROOT / "src/kioskguard.ts").read_text()
        self.assertIn("neutralizeExternalAnchors(win.document, win.location.href)", guard)
        self.assertIn('win.document.addEventListener(', guard)
        self.assertIn('"click"', guard)
        self.assertIn("event.preventDefault()", guard)
        self.assertIn("event.stopPropagation()", guard)
        self.assertIn("win.open =", guard)
        self.assertIn("shouldBlockWindowOpen(url, win.location.href)", guard)
        self.assertIn("return null", guard)
        # No new Chromium flags: nothing low-risk blocks only off-origin
        # navigations without also breaking map tiles, weather, or updates.
        kiosk = (ROOT / "scripts/kiosk.sh").read_text()
        self.assertIn("--kiosk", kiosk)
        self.assertNotIn("--host-rules", kiosk)
        self.assertNotIn("--host-resolver-rules", kiosk)

    def test_non_kiosk_view_still_has_credit_links_in_markup(self) -> None:
        html = (ROOT / "index.html").read_text()
        self.assertIn('<a id="attrib" href="https://www.esri.com/en-us/legal/terms/data-attributions" target="_blank" rel="noreferrer"></a>', html)
        self.assertIn('<a href="https://www.esri.com/" target="_blank" rel="noreferrer">Powered by Esri</a>', html)
        self.assertIn('<a href="https://www.rainviewer.com/" target="_blank" rel="noreferrer">Weather data by RainViewer</a>', html)
        self.assertIn('<a href="https://adsb.fi/" target="_blank" rel="noreferrer">adsb.fi</a>', html)


class StandbyStripTests(unittest.TestCase):
    def test_standby_hides_bottom_pills_and_keeps_credit(self) -> None:
        css = (ROOT / "src/style.css").read_text()
        main = (ROOT / "src/main.ts").read_text()
        self.assertIn("#hud.standby #status", css)
        self.assertIn("#hud.standby #clock", css)
        self.assertIn("#hud.standby #metar", css)
        self.assertIn("classList.toggle(\"standby\", !idle.hidden)", main)
        # Credit is not hidden with the pills.
        block_start = css.index("#hud.standby #status")
        block = css[block_start:block_start + 280]
        self.assertIn("#hud.standby #metar", block)
        self.assertNotIn("#attrib", block)
        self.assertIn("display: none", block)

    def test_traffic_view_time_and_weather_sit_lower(self) -> None:
        css = (ROOT / "src/style.css").read_text()
        start = css.index("/* 1.0.12: time and weather sit lower")
        block = css[start:start + 500]
        self.assertIn("bottom: 12%;", block)
        self.assertNotIn("bottom: 16%;", block)
        self.assertNotIn("bottom: 13.6%;", css)
        self.assertIn("font-size: 13px", css)  # clock
        self.assertIn("font-size: 12px", css)  # status / metar

    def test_standby_clock_still_opens_the_about_menu(self) -> None:
        main = (ROOT / "src/main.ts").read_text()
        css = (ROOT / "src/style.css").read_text()
        self.assertIn('document.querySelector<HTMLElement>("#idle-clock")', main)
        self.assertIn("statusEl, clockEl, idleClock", main)
        self.assertIn("#idle-clock.hold-target", css)
        self.assertIn("pointer-events: auto", css)


class LockedHomeTests(unittest.TestCase):
    def test_glass_cannot_pan_or_recenter_by_gesture(self) -> None:
        main = (ROOT / "src/main.ts").read_text()
        html = (ROOT / "index.html").read_text()
        self.assertNotIn("panNorth", main)
        self.assertNotIn("panEast", main)
        self.assertNotIn("function recenter", main)
        self.assertNotIn("recenter()", main)
        self.assertNotIn("toast(\"HOME\")", main)
        # Centre is always the saved home, not an offset from a drag.
        self.assertIn("return { lat: config.home.lat, lon: config.home.lon };", main)
        # A swipe is still distinguished from a tap so it does not select,
        # but the move must not change the centre.
        self.assertIn("if (Math.hypot(sx, sy) > 6) drag.moved = true;", main)
        self.assertNotIn("radar.nmPerPx", main)
        self.assertNotIn("Double-tap the map to recenter", html)
        self.assertIn("The map stays centred on the home location set there.", html)

    def test_nav_clears_selection_only(self) -> None:
        main = (ROOT / "src/main.ts").read_text()
        start = main.index('} else if (key === "NAV") {')
        block = main[start:main.index("} else if (key === \"HDG\") {", start)]
        self.assertIn("selectedId = null;", block)
        self.assertIn("detail.hidden = true;", block)
        self.assertNotIn("panNorth", block)
        self.assertNotIn("toast", block)
        # Range still changes around home; pinch remains for zoom, not pan.
        self.assertIn("pinch = { dist: distance(), range: rangeNm };", main)
        self.assertIn("setRange(pinch.range * (pinch.dist / dist), false);", main)

    def test_docs_and_setup_match_locked_home(self) -> None:
        readme = (ROOT / "README.md").read_text()
        software = (ROOT / "docs/SOFTWARE.md").read_text()
        developer = (ROOT / "docs/DEVELOPER.md").read_text()
        setup = (ROOT / "setup/index.html").read_text()
        self.assertNotIn("drag to pan", readme)
        self.assertNotIn("clears a pan", readme)
        self.assertNotIn("NAV recentres", readme)
        self.assertIn("The map stays centered on the home location you set here. You cannot drag or pan the map on the screen.", software)
        self.assertIn("Clear the selection. The map stays centered on the home location from Settings", developer)
        self.assertIn("The screen stays centered there; it cannot be panned on the display", software)
        self.assertIn("Saved. The glass is now centred here.", setup)
        self.assertNotIn("NAV recentres the glass here.", setup)
