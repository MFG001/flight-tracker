"""1.0.8: range steps 10, 20, 30, 40, 50, 75, 100 NM; 2 and 5 removed."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from logic import DEFAULT_CONFIG, sanitize_config  # noqa: E402
from migrate import migrate_config  # noqa: E402
from rings import MIN_RANGE_NM, MAX_RANGE_NM, RANGES, ring_distances, rings_for_range, snap_range  # noqa: E402

try:
    from server.tests.test_v103 import run_ts  # noqa: E402
except ImportError:
    from test_v103 import run_ts  # type: ignore  # noqa: E402


class VersionPinTests(unittest.TestCase):
    def test_version_is_at_least_108(self) -> None:
        # 1.0.9 moved on; test_v109 pins the exact number.
        version = (ROOT / "VERSION").read_text().strip()
        self.assertGreaterEqual(tuple(int(x) for x in version.split(".")), (1, 0, 8))


class RangeStepTests(unittest.TestCase):
    STEPS = (10, 20, 30, 40, 50, 75, 100)

    def test_steps_and_default(self) -> None:
        self.assertEqual(RANGES, self.STEPS)
        self.assertEqual((MIN_RANGE_NM, MAX_RANGE_NM), (10, 100))
        # The 1.0.7 default was already 20, which is still in the list.
        self.assertEqual(DEFAULT_CONFIG["rangeNm"], 20.0)
        self.assertIn(int(DEFAULT_CONFIG["rangeNm"]), RANGES)
        example = json.loads((ROOT / "data/config.example.json").read_text())
        self.assertEqual(example["rangeNm"], 20)
        main = (ROOT / "src/main.ts").read_text()
        self.assertIn("rangeNm: 20,", main)
        software = (ROOT / "docs/SOFTWARE.md").read_text()
        self.assertIn("The steps are 10, 20, 30, 40, 50, 75, and 100 nm", software)
        self.assertNotIn("Steps 2, 5, 10", software)
        self.assertNotIn("At 2 nm they read", software)

    def test_legacy_2_and_5_and_other_non_steps_snap(self) -> None:
        self.assertEqual([snap_range(v) for v in (2, 5, 0, 9, 2.0, 5.0)], [10, 10, 10, 10, 10, 10])
        # In-list values stay; values above 100 become 100; mid values go to the nearest step.
        self.assertEqual([snap_range(v) for v in (10, 20, 30, 40, 50, 75, 100, 25, 45, 250)], [10, 20, 30, 40, 50, 75, 100, 20, 40, 100])

    def test_sanitize_and_migrate_rewrite_saved_2_and_5(self) -> None:
        home = {"name": "KJFK", "lat": 40.6399, "lon": -73.7787}
        for asked, kept in ((2, 10), (5, 10), (10, 10), (20, 20), (100, 100), (7, 10), (250, 100)):
            cfg, errors = sanitize_config({"home": home, "rangeNm": asked})
            self.assertEqual(errors, [])
            self.assertEqual(cfg["rangeNm"], kept, asked)
        for saved, kept in ((2, 10), (5, 10), (20, 20), (40, 40), (15, 10), (250, 100)):
            out = migrate_config({"schema": 3, "rangeNm": saved, "home": home})
            self.assertEqual(out["rangeNm"], kept, saved)

    def test_auto_rings_outer_equals_range_and_even_spacing(self) -> None:
        expected = {
            10: [2.5, 5.0, 7.5, 10.0],
            20: [5.0, 10.0, 15.0, 20.0],
            30: [10.0, 20.0, 30.0],
            40: [10.0, 20.0, 30.0, 40.0],
            50: [10.0, 20.0, 30.0, 40.0, 50.0],
            75: [25.0, 50.0, 75.0],
            100: [25.0, 50.0, 75.0, 100.0],
        }
        self.assertEqual({nm: rings_for_range(nm) for nm in self.STEPS},
                         {10: 4, 20: 4, 30: 3, 40: 4, 50: 5, 75: 3, 100: 4})
        for nm, rings in expected.items():
            got = ring_distances(nm)  # auto count
            self.assertEqual(got, rings, nm)
            self.assertEqual(got[-1], float(nm))
            step = got[0]
            for i, value in enumerate(got, start=1):
                self.assertAlmostEqual(value, step * i, places=6)
            # Labels stay round: integers, or a single decimal only below 10 NM.
            for value in got:
                if value >= 10:
                    self.assertEqual(value, round(value), (nm, value))

    def test_migrate_default_four_rings_becomes_auto(self) -> None:
        home = {"name": "KJFK", "lat": 40.6399, "lon": -73.7787}
        out = migrate_config({"schema": 3, "rangeNm": 30, "rings": 4, "home": home})
        self.assertEqual(out["rings"], 0)
        kept = migrate_config({"schema": 3, "rangeNm": 30, "rings": 5, "home": home})
        self.assertEqual(kept["rings"], 5)
        cfg, errors = sanitize_config({"home": home, "rangeNm": 20, "rings": 0})
        self.assertEqual(errors, [])
        self.assertEqual(cfg["rings"], 0)

    def test_glass_has_no_preset_bar(self) -> None:
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="range-minus"', index)
        self.assertIn('id="range-plus"', index)
        self.assertIn('<div id="range" aria-live="polite">', index)
        self.assertNotIn("range-picker", index)
        self.assertNotIn("range-picker", (ROOT / "src/main.ts").read_text())
        setup = (ROOT / "setup/index.html").read_text(encoding="utf-8")
        self.assertIn('<option value="0">Auto</option>', setup)




class ListAltitudeTests(unittest.TestCase):
    def test_list_drops_ft_detail_keeps_it(self) -> None:
        main = (ROOT / "src/main.ts").read_text()
        fmt = (ROOT / "src/format.ts").read_text()
        # The IN RANGE / TRAFFIC list drops the unit. The selected card
        # still shows FT. Map blocks are asserted in test_v1010.
        self.assertIn("alt.textContent = listAltitude(row.item.altFt, row.item.ground, config.units);", main)
        self.assertIn('["ALTITUDE", formatAltitude(item.altFt, item.ground, config.units)]', main)
        self.assertIn('return `${Math.round(ft).toLocaleString("en-US")} FT`;', fmt)
        data = run_ts("""
import { formatAltitude, listAltitude, formatVertical } from "./src/format.ts";
const rows = [
  listAltitude(3200, false, "aviation"),
  listAltitude(7600, false, "imperial"),
  listAltitude(34000, false, "aviation"),
  listAltitude(0, true, "aviation"),
  listAltitude(null, false, "aviation"),
  listAltitude(3200, false, "metric"),
  formatAltitude(3200, false, "aviation"),
  formatVertical(800, "aviation"),
];
console.log(JSON.stringify(rows));
""")
        self.assertEqual(data, [
            "3,200",
            "7,600",
            "34,000",
            "GROUND",
            "—",
            "975 M",
            "3,200 FT",
            "+800 FPM",
        ])


class LabelPlacementTests(unittest.TestCase):
    def test_radar_uses_sticky_placement(self) -> None:
        radar = (ROOT / "src/radar.ts").read_text()
        self.assertIn("placeLabels(drafts", radar)
        self.assertIn("this.labelMemory", radar)
        self.assertNotIn("{ ox: 14, oy: -16 }", radar)
        self.assertNotIn("if (!box) continue", radar)

    def test_two_close_aircraft_first_fit_bounces_sticky_holds(self) -> None:
        data = run_ts(r"""
import { placeLabels, placeLabelsFirstFit } from "./src/labelplace.ts";
const box = { w: 86, h: 30 };
const a = { id: "A", x: 360, y: 360, ...box, distNm: 1.00 };
const b = { id: "B", x: 364, y: 361, ...box, distNm: 1.01 };
const opts = { cx: 360, cy: 360, radius: 280 };
const first1 = placeLabelsFirstFit([a, b], opts);
const first2 = placeLabelsFirstFit([{ ...a, distNm: 1.01 }, { ...b, distNm: 1.00 }], opts);
const memory = new Map();
const sticky1 = placeLabels([a, b], { ...opts, memory });
const sticky2 = placeLabels([{ ...a, distNm: 1.01 }, { ...b, distNm: 1.00 }], { ...opts, memory });
function key(rows) {
  return Object.fromEntries(["A", "B"].map((id) => {
    const r = rows.find((row) => row.id === id);
    return [id, r ? [r.ox, r.oy] : null];
  }));
}
function same(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}
console.log(JSON.stringify({
  first1: key(first1),
  first2: key(first2),
  sticky1: key(sticky1),
  sticky2: key(sticky2),
  firstFlipped: !same(key(first1), key(first2)),
  stickyHeld: same(key(sticky1), key(sticky2)),
}));
""")
        self.assertTrue(data["firstFlipped"], data)
        self.assertTrue(data["stickyHeld"], data)
        self.assertEqual(data["sticky1"], data["sticky2"])

    def test_clusters_of_2_3_and_6_keep_every_label(self) -> None:
        data = run_ts(r"""
import { placeLabels, placeLabelsFirstFit } from "./src/labelplace.ts";
function cluster(n) {
  return Array.from({ length: n }, (_, i) => ({
    id: `C${i + 1}`,
    x: 360 + (i % 3) * 6,
    y: 360 + Math.floor(i / 3) * 6,
    w: 86,
    h: 30,
    distNm: 0.2 + i * 0.01,
  }));
}
const opts = { cx: 360, cy: 360, radius: 280 };
const counts = {};
for (const n of [2, 3, 6]) {
  const items = cluster(n);
  counts[n] = {
    first: placeLabelsFirstFit(items, opts).length,
    sticky: placeLabels(items, { ...opts, memory: new Map() }).length,
  };
}
console.log(JSON.stringify(counts));
""")
        for n in (2, 3, 6):
            self.assertEqual(data[str(n)]["sticky"], n, data)
        # The old five-slot first-fit drops some of a tight 6-ship cluster.
        self.assertLess(data["6"]["first"], 6, data)

    def test_overflow_priority_is_stable(self) -> None:
        data = run_ts(r"""
import { placeLabels } from "./src/labelplace.ts";
const items = [
  { id: "far", x: 360, y: 360, w: 90, h: 30, distNm: 5 },
  { id: "near", x: 362, y: 361, w: 90, h: 30, distNm: 0.4 },
  { id: "mid", x: 361, y: 362, w: 90, h: 30, distNm: 1.2 },
  { id: "pick", x: 363, y: 360, w: 90, h: 30, distNm: 4, selected: true },
  { id: "sos", x: 359, y: 363, w: 90, h: 30, distNm: 3, emergency: true },
];
// Tiny circle: only a couple of boxes can sit fully inside, so some hide.
const opts = { cx: 360, cy: 360, radius: 48 };
const memory = new Map();
const a = placeLabels(items, { ...opts, memory });
const b = placeLabels(items, { ...opts, memory });
const ids = (rows) => rows.map((r) => r.id).sort();
console.log(JSON.stringify({
  first: ids(a),
  second: ids(b),
  hasPick: a.some((r) => r.id === "pick"),
  hasSos: a.some((r) => r.id === "sos"),
  hasNear: a.some((r) => r.id === "near"),
  hidden: items.map((i) => i.id).filter((id) => !a.some((r) => r.id === id)),
}));
""")
        self.assertEqual(data["first"], data["second"], data)
        self.assertTrue(data["hasPick"], data)
        self.assertTrue(data["hasSos"], data)
        # Nearest of the remaining ordinary traffic should beat farther ones
        # when any ordinary label still fits.
        if data["hasNear"] or "near" in data["hidden"]:
            self.assertTrue(data["hasNear"] or "far" in data["hidden"], data)


if __name__ == "__main__":
    unittest.main()
