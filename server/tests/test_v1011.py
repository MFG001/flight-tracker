"""1.0.11: owner on the selected-aircraft card; map blocks still have no ft."""
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

from server.logic import normalize_aircraft  # noqa: E402


class VersionPinTests(unittest.TestCase):
    def test_version_is_1011_everywhere(self) -> None:
        self.assertEqual((ROOT / "VERSION").read_text().strip(), "1.0.11")
        self.assertEqual(json.loads((ROOT / "package.json").read_text())["version"], "1.0.11")
        lock = json.loads((ROOT / "package-lock.json").read_text())
        self.assertEqual((lock["version"], lock["packages"][""]["version"]), ("1.0.11", "1.0.11"))
        self.assertIn("FlightTracker/1.0.11 ", (ROOT / "server/flighttracker.py").read_text())


class FormatOwnerTests(unittest.TestCase):
    def test_title_case_keeps_suffixes_and_mixed_case(self) -> None:
        data = run_ts("""
import { formatOwner } from "./src/format.ts";
console.log(JSON.stringify([
  formatOwner(null),
  formatOwner(""),
  formatOwner("   "),
  formatOwner("NORTH STAR AIRWAYS INC"),
  formatOwner("BLUE RIDGE HELI LLC"),
  formatOwner("GREAT LAKES HOPPER CO"),
  formatOwner("PRAIRIE EXPRESS LTD"),
  formatOwner("ORANGE BANNER AIR LP"),
  formatOwner("NASA TEST JET USA"),
  formatOwner("CITY OF CEDAR LAKE"),
  formatOwner("FOO-BAR LTD"),
  formatOwner("Prairie Wing Flying Club"),
  formatOwner("ACME AVIATION INC."),
  formatOwner("FAA"),
]));
""")
        self.assertEqual(data, [
            "—", "—", "—",
            "North Star Airways INC",
            "Blue Ridge Heli LLC",
            "Great Lakes Hopper CO",
            "Prairie Express LTD",
            "Orange Banner Air LP",
            "NASA Test Jet USA",
            "City of Cedar Lake",
            "Foo-Bar LTD",
            "Prairie Wing Flying Club",
            "Acme Aviation INC.",
            "FAA",
        ])


class OwnerFieldTests(unittest.TestCase):
    def test_normalize_keeps_ownop_operator_and_local_aliases(self) -> None:
        rows = normalize_aircraft([
            {"hex": "abc001", "flight": "TST1", "lat": 40.6, "lon": -73.7, "alt_baro": 3000,
             "ownOp": "NORTH STAR AIRWAYS INC"},
            {"hex": "abc002", "flight": "TST2", "lat": 40.6, "lon": -73.7, "alt_baro": 3000,
             "owner": "Harbor Crown Jets Inc"},
            {"hex": "abc003", "flight": "TST3", "lat": 40.6, "lon": -73.7, "alt_baro": 3000,
             "operator": "CASCADE HOPPER CO"},
            {"hex": "abc004", "flight": "TST4", "lat": 40.6, "lon": -73.7, "alt_baro": 3000},
        ])
        by = {row["callsign"]: row for row in rows}
        self.assertEqual(by["TST1"]["owner"], "NORTH STAR AIRWAYS INC")
        self.assertEqual(by["TST2"]["owner"], "Harbor Crown Jets Inc")
        self.assertEqual(by["TST3"]["owner"], "CASCADE HOPPER CO")
        self.assertIsNone(by["TST4"]["owner"])

    def test_sample_demo_owners_are_fictional_and_optional(self) -> None:
        raw = json.loads((ROOT / "data" / "sample-aircraft.json").read_text())
        rows = normalize_aircraft(raw)
        self.assertEqual(len(rows), 19)
        owned = [row for row in rows if row.get("owner")]
        missing = [row for row in rows if not row.get("owner")]
        self.assertGreaterEqual(len(owned), 8)
        self.assertGreaterEqual(len(missing), 1)
        self.assertEqual(next(row for row in rows if row["callsign"] == "N407PH")["owner"], "BLUE RIDGE HELI LLC")
        self.assertIsNone(next(row for row in rows if row["callsign"] == "EMG7700")["owner"])

    def test_detail_shows_owner_list_and_map_do_not(self) -> None:
        main = (ROOT / "src/main.ts").read_text()
        radar = (ROOT / "src/radar.ts").read_text()
        types = (ROOT / "src/types.ts").read_text()
        css = (ROOT / "src/style.css").read_text()
        self.assertIn("owner?: string | null;", types)
        self.assertIn('["OWNER", formatOwner(item.owner), "wide"]', main)
        self.assertIn("formatOwner(item.owner)", main)
        self.assertNotIn("formatOwner", radar)
        self.assertNotIn("item.owner", radar)
        self.assertIn("alt.textContent = listAltitude(row.item.altFt, row.item.ground, config.units);", main)
        # Traffic list builds name, altitude, and meta only — no owner cell.
        self.assertIn("li.append(name, alt, meta);", main)
        self.assertIn("#d-grid .wide", css)
        self.assertIn("-webkit-line-clamp: 2;", css)
        script = (ROOT / "scripts/check-safe-circle.mjs").read_text()
        self.assertIn('await open(`${base}/?capture=1&owner=long`)', script)
        self.assertIn("detail-long-owner", script)
        self.assertIn("NORTHWOOD AVIATION HOLDINGS LLC OF THE GREAT LAKES AND PRAIRIE STATES", main)


class MapStillOmitsFtTests(unittest.TestCase):
    def test_map_block_path_still_omits_ft(self) -> None:
        radar = (ROOT / "src/radar.ts").read_text()
        main = (ROOT / "src/main.ts").read_text()
        self.assertIn("const line2 = dataBlockLine(aircraft.altFt, aircraft.ground, aircraft.vsFpm, aircraft.gsKt, scene.units);", radar)
        self.assertNotIn("formatAltitude", radar)
        self.assertIn('["ALTITUDE", formatAltitude(item.altFt, item.ground, config.units)]', main)
