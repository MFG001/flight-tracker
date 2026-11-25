"""1.0.15: METAR follows the home airport; larger time and weather on standby."""
from __future__ import annotations

import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from server.logic import (  # noqa: E402
    CONFIG_SCHEMA,
    DEFAULT_CONFIG,
    icao_home_name,
    metar_follows_home,
    metar_station_after_save,
    metar_station_for_home,
    migrate_default_metar_station,
    sanitize_config,
)
from server.migrate import migrate_config  # noqa: E402

KMLB = {"name": "KMLB", "lat": 28.1028, "lon": -80.6453}
KJFK = {"name": "KJFK", "lat": 40.6399, "lon": -73.7787}
POS = {"name": "POS", "lat": 28.1, "lon": -80.65}


class VersionPinTests(unittest.TestCase):
    def test_version_is_at_least_1015(self) -> None:
        # 1.0.17 moved on; test_v1017 pins the exact number.
        version = (ROOT / "VERSION").read_text().strip()
        self.assertGreaterEqual(tuple(int(x) for x in version.split(".")), (1, 0, 15))
        self.assertEqual(CONFIG_SCHEMA, 4)
        self.assertEqual(DEFAULT_CONFIG["schema"], 4)
        self.assertEqual(DEFAULT_CONFIG["metarStation"], "KJFK")
        self.assertEqual(DEFAULT_CONFIG["home"]["name"], "KJFK")


class MetarFollowHelpersTests(unittest.TestCase):
    def test_icao_home_name(self) -> None:
        self.assertEqual(icao_home_name("kmlb"), "KMLB")
        self.assertEqual(icao_home_name("MLB"), "MLB")
        self.assertEqual(icao_home_name("POS"), "")
        self.assertEqual(icao_home_name("HOME"), "")
        self.assertEqual(icao_home_name("Melbourne"), "")
        self.assertEqual(icao_home_name(""), "")

    def test_follows_blank_or_matching_home(self) -> None:
        self.assertTrue(metar_follows_home("", "KMLB"))
        self.assertTrue(metar_follows_home("KMLB", "KMLB"))
        self.assertTrue(metar_follows_home("KJFK", "KJFK"))
        self.assertFalse(metar_follows_home("KJFK", "KMLB"))
        self.assertFalse(metar_follows_home("KXMR", "KMLB"))

    def test_station_for_home(self) -> None:
        self.assertEqual(metar_station_for_home("KMLB"), "KMLB")
        self.assertEqual(metar_station_for_home("POS"), "")
        self.assertEqual(metar_station_for_home("HOME"), "")

    def test_save_airport_search_follows_home(self) -> None:
        previous = {"home": KJFK, "metarStation": "KJFK"}
        new = {"home": KMLB, "metarStation": "KJFK"}
        self.assertEqual(metar_station_after_save(previous, new), "KMLB")

    def test_save_follows_when_previous_station_matched_old_home(self) -> None:
        previous = {"home": KMLB, "metarStation": "KMLB"}
        new = {"home": {"name": "KMCO", "lat": 28.4294, "lon": -81.309}, "metarStation": "KMLB"}
        self.assertEqual(metar_station_after_save(previous, new), "KMCO")

    def test_save_lat_lon_uses_nearest(self) -> None:
        previous = {"home": KMLB, "metarStation": "KMLB"}
        new = {"home": POS, "metarStation": "KMLB"}
        self.assertEqual(metar_station_after_save(previous, new), "")

    def test_save_keeps_explicit_override(self) -> None:
        previous = {"home": KJFK, "metarStation": "KNYC"}
        new = {"home": KMLB, "metarStation": "KNYC"}
        self.assertEqual(metar_station_after_save(previous, new), "KNYC")

    def test_save_keeps_station_typed_in_the_same_request(self) -> None:
        previous = {"home": KJFK, "metarStation": "KJFK"}
        new = {"home": KMLB, "metarStation": "KXMR"}
        self.assertEqual(metar_station_after_save(previous, new), "KXMR")

    def test_save_without_home_change_leaves_station(self) -> None:
        previous = {"home": KMLB, "metarStation": "KJFK"}
        new = {"home": KMLB, "metarStation": "KJFK"}
        self.assertEqual(metar_station_after_save(previous, new), "KJFK")

    def test_blank_station_follows_new_airport(self) -> None:
        previous = {"home": POS, "metarStation": ""}
        new = {"home": KMLB, "metarStation": ""}
        self.assertEqual(metar_station_after_save(previous, new), "KMLB")


class MetarMigrationTests(unittest.TestCase):
    def test_leftover_kjfk_default_follows_home_airport(self) -> None:
        cfg = {"schema": 3, "home": KMLB, "metarStation": "KJFK", "rangeNm": 20}
        out = migrate_config(deepcopy(cfg))
        self.assertEqual(out["schema"], 4)
        self.assertEqual(out["metarStation"], "KMLB")

    def test_leftover_kjfk_default_with_lat_lon_home_uses_nearest(self) -> None:
        cfg = {"schema": 3, "home": POS, "metarStation": "KJFK", "rangeNm": 20}
        out = migrate_config(deepcopy(cfg))
        self.assertEqual(out["schema"], 4)
        self.assertEqual(out["metarStation"], "")

    def test_default_home_keeps_kjfk(self) -> None:
        cfg = {"schema": 3, "home": KJFK, "metarStation": "KJFK", "rangeNm": 20}
        out = migrate_config(deepcopy(cfg))
        self.assertEqual(out["schema"], 4)
        self.assertEqual(out["metarStation"], "KJFK")

    def test_explicit_override_is_kept(self) -> None:
        cfg = {"schema": 3, "home": KMLB, "metarStation": "KXMR", "rangeNm": 20}
        out = migrate_config(deepcopy(cfg))
        self.assertEqual(out["metarStation"], "KXMR")
        self.assertEqual(out["schema"], 4)

    def test_schema_4_does_not_overwrite_an_explicit_kjfk(self) -> None:
        # After the one-time upgrade, a user who then chooses KJFK keeps it.
        cfg = {"schema": 4, "home": KMLB, "metarStation": "KJFK", "rangeNm": 20}
        out = migrate_config(deepcopy(cfg))
        self.assertEqual(out["metarStation"], "KJFK")
        self.assertEqual(out["schema"], 4)

    def test_migration_is_idempotent_for_a_fixed_unit(self) -> None:
        cfg = {"schema": 3, "home": KMLB, "metarStation": "KJFK", "rangeNm": 20}
        once = migrate_config(deepcopy(cfg))
        twice = migrate_config(deepcopy(once))
        self.assertEqual(once, twice)

    def test_helper_alone_matches_migrate(self) -> None:
        cfg = {"home": KMLB, "metarStation": "KJFK"}
        migrate_default_metar_station(cfg)
        self.assertEqual(cfg["metarStation"], "KMLB")

    def test_example_and_default_are_already_current(self) -> None:
        example = json.loads((ROOT / "data/config.example.json").read_text())
        self.assertEqual(example["schema"], 4)
        self.assertEqual(example["metarStation"], "KJFK")
        cfg, errors = sanitize_config(example)
        self.assertEqual(errors, [])
        self.assertEqual(migrate_config(deepcopy(cfg)), cfg)

    def test_old_schema_2_lands_on_4(self) -> None:
        out = migrate_config({"schema": 2, "home": KMLB, "metarStation": "KJFK", "rangeNm": 20})
        self.assertEqual(out["schema"], 4)
        self.assertEqual(out["metarStation"], "KMLB")


class SetupPageTests(unittest.TestCase):
    def test_location_save_updates_metar_when_it_follows_home(self) -> None:
        setup = (ROOT / "setup/index.html").read_text()
        self.assertIn("function metarFollowsHome(station, homeName)", setup)
        self.assertIn("function icaoHomeName(name)", setup)
        self.assertIn("current.metarStation = icaoHomeName(home.name)", setup)
        self.assertIn('$("metar-station").value = current.metarStation', setup)
        # Location save still writes only a location patch, plus the followed station.
        self.assertIn("current.home = home", setup)


class StandbyTypeTests(unittest.TestCase):
    def test_standby_time_and_weather_are_larger(self) -> None:
        css = (ROOT / "src/style.css").read_text()
        # Standby card
        start = css.index("/* 1.0.15: larger time and weather on the standby card only.")
        block = css[start:start + 600]
        self.assertIn("#idle-clock { margin: 2px 0; font-size: 36px; letter-spacing: 0.08em; white-space: nowrap; }", block)
        self.assertIn("width: 64%;", css)
        self.assertIn("#idle-metar { font-size: 15px; }", block)
        self.assertIn("#idle-wx { font-size: 15px;", block)
        # Traffic-view pills at the bottom of the glass stay the same size.
        self.assertIn("#clock { font-size: 13px; }", css)
        metar_rule = css[css.index("#metar {"):css.index("#metar {") + 280]
        self.assertIn("font-size: 12px;", metar_rule)
        # Title and airport on the standby card are unchanged.
        self.assertIn("#idle-title { color: #ffd089; letter-spacing: 0.04em; font-size: 14px; }", css)
        self.assertIn("#idle-airport, #idle-metar { color: var(--muted); font-size: 12px; letter-spacing: 0.04em; }", css)

    def test_idle_metar_still_wraps(self) -> None:
        css = (ROOT / "src/style.css").read_text()
        # Shared wrap rule covers the standby METAR and weather lines.
        start = css.index("#d-call, #wifi-title, #about-status, #traffic-list strong, #idle-title, #idle-airport, #idle-metar, #idle-wx, #alert {")
        block = css[start:start + 280]
        self.assertIn("white-space: normal", block)
        self.assertIn("overflow-wrap: anywhere", block)


class ServerSaveHookTests(unittest.TestCase):
    def test_update_config_uses_follow_helper(self) -> None:
        source = (ROOT / "server/flighttracker.py").read_text()
        self.assertIn("metar_station_after_save", source)
        self.assertIn('cfg["metarStation"] = metar_station_after_save(self.config, cfg)', source)


if __name__ == "__main__":
    unittest.main()
