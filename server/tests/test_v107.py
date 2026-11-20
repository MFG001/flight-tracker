"""1.0.7 prototype: range-change traffic fix, map/radar scale after a range
change, weather status on the glass, and the on-screen update prompt with
"install later"."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

try:
    from server.tests.test_v103 import SetupServer, node_ts_ok, run_ts  # noqa: E402
except ImportError:  # discovered with -s server/tests
    from test_v103 import SetupServer, node_ts_ok, run_ts  # type: ignore  # noqa: E402

from adsbfi import AdsbFiFeed, query_radius_nm  # noqa: E402
import update_schedule as us  # noqa: E402

FIXTURE = {"now": 1_700_000_000_000, "ac": [{"hex": "a1", "lat": 40.7, "lon": -73.8, "alt_baro": 3000}]}
BIGGER = {"now": 1_700_000_001_000, "ac": [{"hex": "a1", "lat": 40.7, "lon": -73.8}, {"hex": "b2", "lat": 41.1, "lon": -73.8}]}


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class RangeChangeFeedTests(unittest.TestCase):
    """Root cause of "aircraft show, then disappear" after a range change."""

    def make(self, responses):
        calls = []

        def fetch(url, ua, timeout):
            calls.append(url)
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        clock = FakeClock()
        return AdsbFiFeed("ua", fetch=fetch, clock=clock, min_interval=5), clock, calls

    def test_range_change_keeps_traffic_and_refetches_quickly(self) -> None:
        feed, clock, calls = self.make([FIXTURE, BIGGER])
        self.assertEqual(len(feed.get(40.6, -73.8, 20)["doc"]["aircraft"]), 1)
        clock.t += 0.5  # range picked half a second after a fetch
        r = feed.get(40.6, -73.8, 40)
        # 1.0.6 returned doc None here (and an empty screen for up to 5 s).
        self.assertIsNotNone(r["doc"])
        self.assertEqual(len(r["doc"]["aircraft"]), 1)
        self.assertEqual(len(calls), 1)
        clock.t += 1.1  # 1.5 s after the last request, not 5 s
        r = feed.get(40.6, -73.8, 40)
        self.assertEqual(len(calls), 2)
        self.assertIn(f"/dist/{query_radius_nm(40)}", calls[1])
        self.assertEqual(len(r["doc"]["aircraft"]), 2)

    def test_range_change_during_backoff_keeps_old_traffic(self) -> None:
        feed, clock, calls = self.make([FIXTURE, RuntimeError("offline")])
        feed.get(40.6, -73.8, 20)
        clock.t += 5
        feed.get(40.6, -73.8, 20)  # fails, backs off 10 s
        clock.t += 1
        r = feed.get(40.6, -73.8, 40)
        self.assertEqual(len(calls), 2)  # backoff respected
        self.assertIsNotNone(r["doc"])  # still within the stale window

    def test_home_change_still_drops(self) -> None:
        feed, clock, calls = self.make([FIXTURE, RuntimeError("x")])
        feed.get(40.6, -73.8, 20)
        clock.t += 5
        self.assertIsNone(feed.get(40.0, -75.0, 20)["doc"])


class ServerRangeParamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.srv = SetupServer(self)

    def test_requested_range(self) -> None:
        rr = self.srv.ft.App.requested_range
        self.assertEqual(rr("40"), 40.0)
        for bad in (None, "", "x", "0", "-5", "nan", "inf", "999"):
            self.assertIsNone(rr(bad), bad)

    def test_aircraft_uses_live_range(self) -> None:
        app = self.srv.app
        cfg = app.snapshot()
        cfg["feed"]["mode"] = "adsbfi"
        app.update_config(cfg)
        app.feed_overridden = True
        seen = []
        with mock.patch.object(app.adsbfi, "get", side_effect=lambda lat, lon, rng: seen.append(rng) or {"doc": None, "stale": False, "error": "x"}):
            self.srv.get("/api/aircraft?range=40")
            self.srv.get("/api/aircraft")
        self.assertEqual(seen[0], 40.0)
        self.assertEqual(seen[1], cfg["rangeNm"])


class SourceTests(unittest.TestCase):
    main = (ROOT / "src/main.ts").read_text(encoding="utf-8")
    radar = (ROOT / "src/radar.ts").read_text(encoding="utf-8")

    def test_plate_key_has_map_scale(self) -> None:
        key = self.radar[self.radar.index("const plateKey = ["):]
        key = key[: key.index("].join")]
        self.assertIn("zoom.pxPerWorldPx", key)

    def test_kiosk_polls_with_range_and_drops_stale_replies(self) -> None:
        self.assertIn("aircraftUrl(asked, captureMode)", self.main)
        self.assertIn("if (!aircraftGate.accept(ticket)) return;", self.main)
        self.assertIn("aircraftGate.invalidate();", self.main)

    def test_standby_shows_weather_line(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('<p id="idle-wx" hidden></p>', html)
        css = (ROOT / "src/style.css").read_text(encoding="utf-8")
        self.assertIn("background: rgba(5, 10, 14, 0.5);", css)

    def test_update_pop_markup(self) -> None:
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        for id_ in ("update-pop", "up-now", "up-later", "up-bar", "up-close"):
            self.assertIn(f'id="{id_}"', html)
        self.assertIn(">UPDATE NOW<", html)
        self.assertIn(">LATER<", html)

    def test_setup_card_has_later_time_and_cancel(self) -> None:
        setup = (ROOT / "setup/index.html").read_text(encoding="utf-8")
        for needle in ('id="sw-later-at" type="time" value="02:00"', ">SAVE TIME<", ">CANCEL SCHEDULE<", '"/api/updates/later-at"', '"/api/updates/schedule/cancel"', "Scheduled: Version "):
            self.assertIn(needle, setup)


@unittest.skipUnless(node_ts_ok(), "node with --experimental-strip-types not installed")
class TsLogicTests(unittest.TestCase):
    def test_aircraft_poll(self) -> None:
        data = run_ts("""
import { aircraftUrl, PollGate } from "./src/aircraftpoll.ts";
const g = new PollGate();
const a = g.begin(); const b = g.begin();
const outOfOrder = [g.accept(b), g.accept(a)];
const c = g.begin(); g.invalidate(); const d = g.begin();
console.log(JSON.stringify({ urls: [aircraftUrl(40, false), aircraftUrl(2.5, true), aircraftUrl(NaN, false)], outOfOrder, stale: g.accept(c), fresh: g.accept(d) }));
""")
        self.assertEqual(data["urls"], ["/api/aircraft?range=40", "/api/aircraft?range=2.5&freeze=1", "/api/aircraft"])
        self.assertEqual(data["outOfOrder"], [True, False])
        self.assertFalse(data["stale"])
        self.assertTrue(data["fresh"])

    def test_wx_summary(self) -> None:
        data = run_ts("""
import { wxSummary } from "./src/wxstatus.ts";
const t = Date.UTC(2026, 10, 20, 12, 0) / 1000;
const base = { on: true, down: false, stale: false, frameTime: t, echoes: 0, range: "20 NM" };
console.log(JSON.stringify([
  wxSummary({ ...base, on: false }), wxSummary(base), wxSummary({ ...base, echoes: 0.2 }),
  wxSummary({ ...base, down: true }), wxSummary({ ...base, stale: true }), wxSummary({ ...base, echoes: null }),
]));
""")
        off, clear, rain, down, stale, unknown = data
        self.assertIsNone(off["chip"])
        self.assertEqual((clear["chip"], clear["standby"]), ("WX CLEAR", "Radar 1200Z · no rain within 20 NM"))
        self.assertEqual((rain["chip"], rain["standby"]), ("WX 1200Z", "Radar 1200Z · rain within 20 NM"))
        self.assertEqual((down["chip"], down["tone"]), ("WX UNAVAILABLE", "bad"))
        self.assertEqual((stale["chip"], stale["tone"]), ("WX STALE", "warn"))
        self.assertEqual(unknown["chip"], "WX 1200Z")

    def test_update_pop_logic(self) -> None:
        data = run_ts("""
import { promptAllowed, installPercent, installLine, installDone, installFailed, scheduledLine } from "./src/updatepop.ts";
const ac = (extra) => ({ id: "x", callsign: "X", lat: 28, lon: -80, squawk: null, ...extra });
console.log(JSON.stringify({
  clear: promptAllowed(null, [ac({})]),
  emergencyBanner: promptAllowed("EMERGENCY N123", []),
  militaryBanner: promptAllowed("MILITARY RCH123", []),
  watchBanner: promptAllowed("WATCH N486TT", []),
  squawks: ["7500", "7600", "7700"].map((sq) => promptAllowed(null, [ac({ squawk: sq })])),
  flagged: promptAllowed(null, [ac({ emergency: true })]),
  military: promptAllowed(null, [ac({ military: true })]),
  watched: promptAllowed(null, [ac({ watched: true })]),
  pct: [installPercent({ stage: "checking", step: 1, received: 0, total: 0 }), installPercent({ stage: "downloading", step: 2, received: 50, total: 100 }), installPercent({ stage: "restarting", step: 4, received: 0, total: 0 })],
  line: installLine({ stage: "downloading", step: 2, detail: "Downloading Version 1.0.7 (24 / 71 MB)...", target: "1.0.7" }),
  done: [installDone({ version: "1.0.7", state: "installed" }, "1.0.7"), installDone({ version: "1.0.6", state: "installing" }, "1.0.7")],
  failed: [installFailed({ state: "rolled-back", stage: "failed" }), installFailed({ state: "installing", stage: "verifying" })],
  sched: scheduledLine("2:00 AM ET"),
}));
""")
        # Only emergencies hold the prompt back (1.0.7).
        self.assertTrue(data["clear"])
        self.assertFalse(data["emergencyBanner"])
        self.assertEqual(data["squawks"], [False, False, False])
        self.assertFalse(data["flagged"])
        self.assertTrue(data["militaryBanner"])
        self.assertTrue(data["watchBanner"])
        self.assertTrue(data["military"])
        self.assertTrue(data["watched"])
        self.assertEqual(data["pct"], [4, 38, 79])
        self.assertEqual(data["line"], "Step 2 of 4 · Downloading Version 1.0.7 (24 / 71 MB)...")
        self.assertEqual(data["done"], [True, False])
        self.assertEqual(data["failed"], [True, False])
        self.assertEqual(data["sched"], "Update scheduled for 2:00 AM ET")


class ScheduleLogicTests(unittest.TestCase):
    def test_next_occurrence_and_labels(self) -> None:
        ny = ZoneInfo("America/New_York")
        evening = datetime(2026, 11, 20, 21, 30, tzinfo=ny)
        early = datetime(2026, 11, 20, 1, 15, tzinfo=ny)
        self.assertEqual(us.next_occurrence("02:00", evening, ny), datetime(2026, 11, 21, 2, 0, tzinfo=ny))
        self.assertEqual(us.next_occurrence("02:00", early, ny), datetime(2026, 11, 20, 2, 0, tzinfo=ny))
        self.assertEqual(us.next_occurrence("02:00", datetime(2026, 11, 20, 2, 0, tzinfo=ny), ny), datetime(2026, 11, 21, 2, 0, tzinfo=ny))
        self.assertEqual(us.time_label("02:00", "12h"), "2:00 AM")
        self.assertEqual(us.time_label("02:00", "12h", "America/New_York"), "2:00 AM ET")
        self.assertEqual(us.time_label("02:00", "24h", "America/New_York"), "02:00 ET")
        self.assertEqual(us.time_label("14:30", "12h"), "2:30 PM")
        self.assertEqual(us.time_label("00:05", "12h"), "12:05 AM")
        self.assertEqual(us.time_label("02:00", "24h"), "02:00")
        self.assertEqual(us.valid_later_at("0200"), "02:00")
        self.assertIsNone(us.valid_later_at("25:00"))

    def utc(self, *args) -> datetime:
        return datetime(*args, tzinfo=timezone.utc)

    def at_utc(self, now: datetime) -> datetime:
        return us.next_occurrence("02:00", now, us.zone("America/New_York")).astimezone(timezone.utc)

    def test_utc_clock_books_eastern_two_am(self) -> None:
        # Winter (EST, UTC-5): 02:00 ET is 07:00 UTC.
        self.assertEqual(self.at_utc(self.utc(2026, 11, 20, 12, 0)), self.utc(2026, 11, 21, 7, 0))
        # 06:30 UTC is still 01:30 ET the same night: tonight, not tomorrow.
        self.assertEqual(self.at_utc(self.utc(2026, 11, 21, 6, 30)), self.utc(2026, 11, 21, 7, 0))
        # Summer (EDT, UTC-4): 02:00 ET is 06:00 UTC.
        self.assertEqual(self.at_utc(self.utc(2026, 7, 1, 12, 0)), self.utc(2026, 7, 2, 6, 0))

    def test_dst_days(self) -> None:
        # Spring forward, Sun 8 Mar 2026: 02:00 ET does not exist; it runs at
        # the jump (03:00 EDT = 07:00 UTC), once.
        spring = self.at_utc(self.utc(2026, 3, 7, 20, 0))
        self.assertEqual(spring, self.utc(2026, 3, 8, 7, 0))
        self.assertEqual(spring.astimezone(ZoneInfo("America/New_York")).hour, 3)
        # Fall back, Sun 1 Nov 2026: 02:00 EST = 07:00 UTC (after the repeated 01:xx hour).
        self.assertEqual(self.at_utc(self.utc(2026, 10, 31, 20, 0)), self.utc(2026, 11, 1, 7, 0))
        # During the repeated hour (01:30 EST, 06:30 UTC) the 02:00 is still ahead tonight.
        self.assertEqual(self.at_utc(self.utc(2026, 11, 1, 6, 30)), self.utc(2026, 11, 1, 7, 0))
        # The day after fall back: back to 07:00 UTC; after spring: 06:00 UTC.
        self.assertEqual(self.at_utc(self.utc(2026, 11, 1, 8, 0)), self.utc(2026, 11, 2, 7, 0))
        self.assertEqual(self.at_utc(self.utc(2026, 3, 8, 8, 0)), self.utc(2026, 3, 9, 6, 0))

    def test_pi_on_utc_system_clock(self) -> None:
        # A naive "now" from a Pi whose system zone is UTC.
        code = (
            "import sys; sys.path.insert(0, 'server'); from datetime import datetime; import update_schedule as us; "
            "b = us.booking('1.0.7', '02:00', '12h', 'later', datetime(2026, 11, 20, 12, 0)); "
            "print(b['atLocal'], int(b['atEpoch']), b['label'], b['zone'])"
        )
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env={**os.environ, "TZ": "UTC"}, capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        at_local, epoch, label = out.stdout.split()[0], int(out.stdout.split()[1]), " ".join(out.stdout.split()[2:5])
        self.assertEqual(at_local, "2026-11-21T02:00-05:00")
        self.assertEqual(epoch, int(self.utc(2026, 11, 21, 7, 0).timestamp()))
        self.assertEqual(label, "2:00 AM ET")
        self.assertTrue(out.stdout.strip().endswith("America/New_York"))

    def test_zone_validation(self) -> None:
        self.assertEqual(us.valid_tz("America/Chicago"), "America/Chicago")
        self.assertIsNone(us.valid_tz("Mars/Olympus"))
        self.assertEqual(str(us.zone("Mars/Olympus")), "America/New_York")
        self.assertEqual(us.zone_short("America/Chicago"), "CT")

    def test_summary_line(self) -> None:
        self.assertEqual(us.summary_line("Fixes radar. Also other things."), "Fixes radar.")
        long = "word " * 40
        out = us.summary_line(long, 30)
        self.assertLessEqual(len(out), 30)
        self.assertTrue(out.endswith("…"))

    def test_prompt_visible_rules(self) -> None:
        base = dict(available=True, latest="1.0.7", token_set=True, auto=False, installing=False, schedule={}, now_epoch=1000.0)
        self.assertTrue(us.prompt_visible(**base))
        for change in ({"available": False}, {"token_set": False}, {"auto": True}, {"installing": True}):
            self.assertFalse(us.prompt_visible(**{**base, **change}), change)
        self.assertFalse(us.prompt_visible(**{**base, "schedule": {"version": "1.0.7", "state": "pending"}}))
        quiet = {"version": "1.0.7", "state": "cancelled", "quietUntil": 2000}
        self.assertFalse(us.prompt_visible(**{**base, "schedule": quiet}))
        self.assertTrue(us.prompt_visible(**{**base, "schedule": quiet, "now_epoch": 2001}))
        self.assertTrue(us.prompt_visible(**{**base, "schedule": {"version": "1.0.6", "state": "pending"}}))


class AppScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.srv = SetupServer(self)
        self.app = self.srv.app
        self.ft = self.srv.ft
        import updater as live
        self.live = live
        patch = mock.patch.object(self.ft, "running_version", return_value="1.0.6")
        patch.start()
        self.addCleanup(patch.stop)
        live.write_status(self.app.config_path, {"state": "available", "available": True, "version": "1.0.7", "notes": "Update prompt on the round screen. More text."})

    def test_prompt_shows_then_later_books_default_time(self) -> None:
        view = self.srv.get("/api/updates")
        self.assertEqual(view["prompt"], {"show": True, "version": "1.0.7", "summary": "Update prompt on the round screen."})
        self.assertEqual(view["laterAt"], "02:00")
        self.assertIsNone(view["schedule"])
        booked = self.srv.post("/api/updates/later", {"version": "1.0.7", "source": "later"})
        self.assertTrue(booked["ok"])
        self.assertEqual(booked["schedule"]["version"], "1.0.7")
        self.assertIn(booked["schedule"]["label"], ("02:00 ET", "2:00 AM ET"))
        self.assertEqual((booked["laterTz"], booked["laterZone"]), ("America/New_York", "ET"))
        self.assertFalse(booked["prompt"]["show"])  # not again until the booked time
        at = datetime.fromtimestamp(booked["schedule"]["atEpoch"], ZoneInfo("America/New_York"))
        self.assertEqual((at.hour, at.minute), (2, 0))

    def test_later_refuses_wrong_or_missing_version(self) -> None:
        ok, detail = self.app.defer_update("1.0.9")
        self.assertFalse(ok)
        self.live.write_status(self.app.config_path, {"state": "available", "available": True, "version": "1.0.5"})
        ok, detail = self.app.defer_update("1.0.5")
        self.assertFalse(ok)
        self.assertIn("no newer version", detail)

    def test_cancel_and_quiet_period(self) -> None:
        self.app.defer_update("1.0.7")
        ok, _ = self.app.cancel_update_schedule()
        self.assertTrue(ok)
        view = self.app.update_view()
        self.assertIsNone(view["schedule"])
        self.assertFalse(view["prompt"]["show"])  # quiet until the next background check
        self.assertFalse(self.app.cancel_update_schedule()[0])

    def test_later_at_saves_and_moves_pending(self) -> None:
        self.app.defer_update("1.0.7")
        ok, _ = self.app.set_later_at("03:30")
        self.assertTrue(ok)
        self.assertEqual(self.app.snapshot()["updates"]["laterAt"], "03:30")
        at = datetime.fromtimestamp(self.app.update_view()["schedule"]["atEpoch"], ZoneInfo("America/New_York"))
        self.assertEqual((at.hour, at.minute), (3, 30))
        self.assertFalse(self.app.set_later_at("3pm")[0])
        self.assertEqual(self.srv.reloaded()["updates"]["laterAt"], "03:30")
        self.assertEqual(self.srv.reloaded()["updates"]["laterTz"], "America/New_York")
        cfg = self.app.snapshot()
        cfg["updates"]["laterTz"] = "Mars/Olympus"
        _, errors = self.app.update_config(cfg)
        self.assertTrue(any("time zone" in e for e in errors))

    def test_tick_installs_when_due_and_only_if_newer(self) -> None:
        self.app._bg_checked_at = 10**12  # no background check in this test
        self.app.defer_update("1.0.7")
        sched = us.read_schedule(self.app.config_path)
        before = datetime.fromtimestamp(sched["atEpoch"] - 60)
        after = datetime.fromtimestamp(sched["atEpoch"] + 1)
        with mock.patch.object(self.app, "install_update", return_value=(True, "Installing")) as install:
            self.assertEqual(self.app.scheduler_tick(before), "idle")
            self.assertEqual(self.app.scheduler_tick(after), "installed")
            install.assert_called_once()
            self.assertEqual(self.app.scheduler_tick(after), "idle")  # once only
        # Booked, but by then the unit already runs it: skipped.
        self.app.cancel_update_schedule()
        us.write_schedule(self.app.config_path, {**sched, "state": "pending"})
        self.live.write_status(self.app.config_path, {"state": "current", "available": False, "version": "1.0.6"})
        with mock.patch.object(self.app, "install_update") as install:
            self.assertEqual(self.app.scheduler_tick(after), "skipped-not-newer")
            install.assert_not_called()

    def test_auto_on_books_without_prompt(self) -> None:
        self.app._bg_checked_at = 10**12
        self.app.set_auto_update(True)
        self.assertFalse(self.app.update_view()["prompt"]["show"])
        self.assertEqual(self.app.scheduler_tick(), "auto-booked")
        self.assertEqual(self.app.update_view()["schedule"]["source"], "auto")
        self.assertEqual(self.app.scheduler_tick(), "idle")

    def test_background_check_is_tokenless_and_waits(self) -> None:
        with mock.patch.object(self.app, "check_updates") as check:
            self.app.started = self.ft.time.monotonic()  # just started
            self.assertNotEqual(self.app.scheduler_tick(), "checked")
            self.app.started -= 120
            self.assertEqual(self.app.scheduler_tick(), "checked")
            self.assertNotEqual(self.app.scheduler_tick(), "checked")  # next one in 6 h
            check.assert_called_once()
        # 1.0.7: no access key exists any more, and none is needed for the check.
        self.assertFalse(hasattr(self.live, "read_token"))


class HundredMileRangeTests(unittest.TestCase):
    """1.0.7: 50, 75 and 100 NM steps; 100 is the maximum."""

    STEPS = [2, 5, 10, 20, 30, 40, 50, 75, 100]

    def test_steps_and_snapping_server(self) -> None:
        from rings import MAX_RANGE_NM, RANGES, ring_distances, snap_range
        self.assertEqual(list(RANGES), self.STEPS)
        self.assertEqual(MAX_RANGE_NM, 100)
        self.assertEqual([snap_range(v) for v in (45, 62, 80, 100, 160)], [40, 50, 75, 100, 100])
        self.assertEqual(ring_distances(100, 4), [25.0, 50.0, 75.0, 100.0])

    def test_config_accepts_100_and_clamps_above(self) -> None:
        from logic import sanitize_config
        for asked, kept in ((100, 100), (75, 75), (50, 50), (250, 100), (40, 40)):
            cfg, errors = sanitize_config({"home": {"name": "KJFK", "lat": 40.6399, "lon": -73.7787}, "rangeNm": asked})
            self.assertEqual(errors, [])
            self.assertEqual(cfg["rangeNm"], kept, asked)

    def test_adsbfi_radius_covers_100_without_hitting_the_api_cap(self) -> None:
        import adsbfi
        radius = query_radius_nm(100)
        self.assertEqual(radius, 127)  # 25 % margin + 2 NM so edge traffic does not pop
        self.assertLess(radius, adsbfi.MAX_RADIUS_NM)  # adsb.fi allows up to 250 NM: no clamping at 100
        self.assertEqual(adsbfi.radius_url(40.6399, -73.7787, radius), "https://opendata.adsb.fi/api/v3/lat/40.6399/lon/-73.7787/dist/127")

    def test_range_change_to_100_keeps_traffic(self) -> None:
        feed, clock, calls = RangeChangeFeedTests.make(self, [FIXTURE, BIGGER])
        feed.get(40.6, -73.8, 40)
        clock.t += 0.5
        r = feed.get(40.6, -73.8, 100)
        self.assertIsNotNone(r["doc"])  # no empty screen while the wider radius loads
        self.assertEqual(len(r["doc"]["aircraft"]), 1)
        clock.t += 1.1
        r = feed.get(40.6, -73.8, 100)
        self.assertIn("/dist/127", calls[-1])
        self.assertEqual(len(r["doc"]["aircraft"]), 2)
        clock.t += 0.5
        r = feed.get(40.6, -73.8, 50)  # and back down
        self.assertIsNotNone(r["doc"])

    def test_server_accepts_live_range_up_to_100(self) -> None:
        srv = SetupServer(self)
        rr = srv.ft.App.requested_range
        self.assertEqual([rr("50"), rr("75"), rr("100")], [50.0, 75.0, 100.0])
        self.assertIsNone(rr("101"))

    def test_setup_page_offers_the_new_steps(self) -> None:
        setup = (ROOT / "setup/index.html").read_text(encoding="utf-8")
        self.assertIn("<option>40</option><option>50</option><option>75</option><option>100</option>", setup)

    @unittest.skipUnless(node_ts_ok(), "node with --experimental-strip-types not installed")
    def test_round_screen_steps_map_and_weather_zoom(self) -> None:
        data = run_ts("""
import { RANGE_STEPS, MAX_RANGE_NM, snapRange, ringDistances, formatRing } from "./src/rings.ts";
import { chooseZoom } from "./src/geo.ts";
import { aircraftUrl } from "./src/aircraftpoll.ts";
// 720 px panel, outer ring about 300 px: the map, sectional and radar zooms at 100 NM.
const ringR = 300, NM = 1852;
const ppm = ringR / (100 * NM);
const reach = (z) => { const c = chooseZoom(40.64, ppm, z.min, z.max); return { z: c.z, tilesAcross: Math.ceil((2 * ringR / c.pxPerWorldPx) / 256) + 2 }; };
console.log(JSON.stringify({
  steps: RANGE_STEPS, max: MAX_RANGE_NM, snaps: [snapRange(160), snapRange(88), snapRange(60)],
  labels: ringDistances(100, 4).map(formatRing), labels75: ringDistances(75, 3).map(formatRing),
  street: reach({ min: 0, max: 19 }), sectional: reach({ min: 8, max: 12 }), radar: reach({ min: 2, max: 7 }),
  url: aircraftUrl(100, false),
}));
""")
        self.assertEqual(data["steps"], self.STEPS)
        self.assertEqual(data["max"], 100)
        self.assertEqual(data["snaps"], [100, 100, 50])
        self.assertEqual(data["labels"], ["25", "50", "75", "100"])
        self.assertEqual(data["labels75"], ["25", "50", "75"])
        self.assertEqual(data["url"], "/api/aircraft?range=100")
        for layer in ("street", "sectional", "radar"):
            tiles = data[layer]["tilesAcross"] ** 2
            self.assertLessEqual(tiles, 64, layer)  # within the per-frame tile budget in radar.ts
        self.assertEqual(data["sectional"]["z"], 8)  # FAA sectional tiles start at zoom 8: still served
        self.assertEqual(data["radar"]["z"], 7)  # RainViewer's top zoom; scaled slightly, full coverage



class VersionPinTests(unittest.TestCase):
    def test_version_is_107_everywhere(self) -> None:
        self.assertEqual((ROOT / "VERSION").read_text().strip(), "1.0.7")
        self.assertEqual(json.loads((ROOT / "package.json").read_text())["version"], "1.0.7")
        lock = json.loads((ROOT / "package-lock.json").read_text())
        self.assertEqual((lock["version"], lock["packages"][""]["version"]), ("1.0.7", "1.0.7"))
        self.assertIn("FlightTracker/1.0.7 ", (ROOT / "server/flighttracker.py").read_text())


class LicenseTests(unittest.TestCase):
    """Source-available, use-but-don't-modify; no MIT for Flight Tracker itself."""

    def test_license_files(self) -> None:
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("Maverick Field Gear Flight Tracker License"))
        self.assertIn("Copyright (c) 2026 Maverick Field Gear", text)
        for needle in ("Modify, adapt", "modified versions", "commercial purpose", "unmodified official releases", "signed by Maverick", "CC BY-NC-ND 4.0", "WITHOUT WARRANTY"):
            self.assertIn(needle, text)
        self.assertNotRegex(text, r"\bMIT\b")
        self.assertEqual(json.loads((ROOT / "package.json").read_text())["license"], "SEE LICENSE IN LICENSE")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotRegex(readme, r"\bMIT\b")
        self.assertIn("Maverick Field Gear Flight Tracker License", readme)
        self.assertIn("CC BY-NC-ND 4.0", readme)
        self.assertIn("THIRD_PARTY_NOTICES.md", (ROOT / "install.sh").read_text())

if __name__ == "__main__":
    unittest.main()
