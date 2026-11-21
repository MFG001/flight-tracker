"""1.0.9: update prompt headline and 5-minute auto-dismiss as LATER."""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

try:
    from server.tests.test_v103 import run_ts  # noqa: E402
    from server.tests.test_v107 import SetupServer  # noqa: E402
except ImportError:
    from test_v103 import run_ts  # type: ignore  # noqa: E402
    from test_v107 import SetupServer  # type: ignore  # noqa: E402

import update_schedule as us  # noqa: E402


class VersionPinTests(unittest.TestCase):
    def test_version_is_at_least_109(self) -> None:
        # 1.0.10 moved on; test_v1010 pins the exact number.
        version = (ROOT / "VERSION").read_text().strip()
        self.assertGreaterEqual(tuple(int(x) for x in version.split(".")), (1, 0, 9))


class PromptCopyTests(unittest.TestCase):
    def test_headline_and_five_minute_timeout(self) -> None:
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("<h2 id=\"up-title\">Update available</h2>", index)
        self.assertIn(">UPDATE NOW</button>", index)
        self.assertIn(">LATER</button>", index)
        main = (ROOT / "src/main.ts").read_text()
        self.assertIn("title: PROMPT_TITLE", main)
        self.assertIn("hint: promptHint(view.laterLabel)", main)
        self.assertIn('kicker: ""', main)
        self.assertIn('void popLater("timeout")', main)
        self.assertIn("PROMPT_TIMEOUT_MS", main)
        self.assertNotIn("Closes by itself in 2 min.", main)
        data = run_ts("""
import { PROMPT_TIMEOUT_MS, PROMPT_TITLE, promptHint, promptAllowed } from "./src/updatepop.ts";
const ac = (extra) => ({ id: "a", callsign: "N1", squawk: "", emergency: false, military: false, watched: false, ...extra });
console.log(JSON.stringify({
  title: PROMPT_TITLE,
  ms: PROMPT_TIMEOUT_MS,
  hint: promptHint("2:00 AM ET"),
  defaultHint: promptHint(),
  emergency: promptAllowed("EMERGENCY N123", []),
  squawk: promptAllowed(null, [ac({ squawk: "7700" })]),
  clear: promptAllowed(null, [ac({})]),
}));
""")
        self.assertEqual(data["title"], "Update available")
        self.assertEqual(data["ms"], 300_000)
        self.assertEqual(us.PROMPT_TIMEOUT_SEC * 1000, data["ms"])
        self.assertEqual(data["hint"], "LATER installs at 2:00 AM ET. Closes by itself in 5 min.")
        self.assertEqual(data["defaultHint"], data["hint"])
        self.assertFalse(data["emergency"])
        self.assertFalse(data["squawk"])
        self.assertTrue(data["clear"])


class TimeoutSchedulesLikeLaterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.srv = SetupServer(self)
        self.app = self.srv.app
        self.ft = self.srv.ft
        import updater as live
        self.live = live
        from unittest import mock
        patch = mock.patch.object(self.ft, "running_version", return_value="1.0.8")
        patch.start()
        self.addCleanup(patch.stop)
        live.write_status(self.app.config_path, {
            "state": "available",
            "available": True,
            "version": "1.0.9",
            "notes": "Update available, closes in 5 minutes.",
        })

    def test_timeout_books_default_time_and_does_not_reprompt(self) -> None:
        view = self.srv.get("/api/updates")
        self.assertTrue(view["prompt"]["show"])
        self.assertEqual(view["prompt"]["version"], "1.0.9")
        self.assertEqual(view["laterAt"], "02:00")
        booked = self.srv.post("/api/updates/later", {"version": "1.0.9", "source": "timeout"})
        self.assertTrue(booked["ok"])
        self.assertEqual(booked["schedule"]["version"], "1.0.9")
        self.assertEqual(booked["schedule"]["source"], "timeout")
        self.assertEqual(us.read_schedule(self.app.config_path)["state"], "pending")
        self.assertIn(booked["schedule"]["label"], ("02:00 ET", "2:00 AM ET"))
        self.assertEqual((booked["laterTz"], booked["laterZone"]), ("America/New_York", "ET"))
        self.assertFalse(booked["prompt"]["show"])
        at = datetime.fromtimestamp(booked["schedule"]["atEpoch"], ZoneInfo("America/New_York"))
        self.assertEqual((at.hour, at.minute), (2, 0))
        again = self.srv.get("/api/updates")
        self.assertFalse(again["prompt"]["show"])
        self.assertEqual(again["schedule"]["source"], "timeout")


if __name__ == "__main__":
    unittest.main()
