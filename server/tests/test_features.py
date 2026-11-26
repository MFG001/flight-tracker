"""Classifier, N-number conversion, watch list, alerts, rings, and sunrise."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from server.alerts import entering_alerts
from server.classify import classify
from server.nnumber import n_number_to_hex
from server.rings import ring_distances, snap_range
from server.solar import schedule_night, solar_hours
from server.watchlist import canonical_watch, filter_aircraft, is_watched


class NNumberTests(unittest.TestCase):
    def test_published_examples(self) -> None:
        self.assertEqual(n_number_to_hex("N1"), "A00001")
        self.assertEqual(n_number_to_hex("N1A"), "A00002")
        self.assertEqual(n_number_to_hex("N1AA"), "A00003")
        self.assertEqual(n_number_to_hex("N10"), "A0025A")
        self.assertEqual(n_number_to_hex("N12345"), "A061D9")
        self.assertEqual(n_number_to_hex("N172SP"), "A12239")

    def test_hyphen_and_case_and_rejects_non_us(self) -> None:
        self.assertEqual(n_number_to_hex("n-12345"), "A061D9")
        self.assertIsNone(n_number_to_hex("G-ABCD"))
        self.assertIsNone(n_number_to_hex("N0"))


class ClassifyTests(unittest.TestCase):
    def test_categories_map_without_guessing(self) -> None:
        self.assertEqual(classify("A1")["kind"], "light")
        self.assertEqual(classify("A3")["kind"], "jet")
        self.assertEqual(classify("A7")["kind"], "rotor")
        self.assertEqual(classify("B2")["kind"], "lighter")
        self.assertEqual(classify("B6")["kind"], "uav")
        self.assertEqual(classify(None)["kind"], "unknown")
        self.assertEqual(classify("B1")["kind"], "unknown")

    def test_military_is_an_accent_not_a_shape(self) -> None:
        row = classify("A7", db_flags=1)
        self.assertEqual(row["kind"], "rotor")
        self.assertTrue(row["military"])
        self.assertFalse(classify("A3", db_flags=0)["military"])

    def test_type_table_and_hex_range_are_optional(self) -> None:
        typed = classify(None, type_code="R44", type_db={"R44": "rotor"})
        self.assertEqual(typed["kind"], "rotor")
        self.assertEqual(classify("A3", type_code="R44", type_db={"R44": "rotor"})["kind"], "jet")
        ranged = classify("A3", hex_id="ADF7C8", hex_ranges=[(0xADF7C8, 0xAFFFFF)])
        self.assertTrue(ranged["military"])
        self.assertFalse(classify("A3", hex_id="A00001", hex_ranges=[(0xADF7C8, 0xAFFFFF)])["military"])

    def test_callsign_is_not_evidence(self) -> None:
        self.assertFalse(classify(None)["military"])
        self.assertEqual(classify(None)["kind"], "unknown")


class WatchTests(unittest.TestCase):
    def test_n_number_matches_hex_without_a_registration_field(self) -> None:
        aircraft = {"hex": "A061D9", "registration": None, "id": "A061D9"}
        self.assertTrue(is_watched(aircraft, ["n-12345"]))
        self.assertEqual(canonical_watch("G-ABCD"), "GABCD")

    def test_registration_and_hex_and_filter(self) -> None:
        rows = [
            {"id": "1", "hex": "400ABC", "registration": "G-ABCD", "callsign": "TEST"},
            {"id": "2", "hex": "A061D9", "registration": None, "callsign": "N12345"},
            {"id": "3", "hex": "ABCDEF", "registration": None, "callsign": "OTHER"},
        ]
        watched = filter_aircraft(rows, {"enabled": True, "tails": ["G-ABCD", "ABCDEF"]})
        self.assertEqual([row["id"] for row in watched], ["1", "3"])
        self.assertEqual(len(filter_aircraft(rows, {"enabled": False, "tails": ["ABCDEF"]})), 3)
        self.assertEqual(filter_aircraft(rows, {"enabled": True, "tails": []}), [])


class AlertTests(unittest.TestCase):
    def test_only_new_matching_aircraft_alert(self) -> None:
        settings = {"watch": True, "military": True, "emergency": True, "chime": False}
        seen = {"OLD"}
        rows = [
            {"id": "OLD", "callsign": "OLD", "military": True, "squawk": "1200"},
            {"id": "MIL", "callsign": "DUKE1", "military": True, "squawk": "1200"},
            {"id": "EMG", "callsign": "EMG1", "military": False, "squawk": "7700"},
            {"id": "CIV", "callsign": "ASA1", "military": False, "squawk": "1200"},
        ]
        reasons = {item["id"]: item["reason"] for item in entering_alerts(seen, rows, settings, True)}
        self.assertEqual(reasons["MIL"], "military")
        self.assertEqual(reasons["EMG"], "emergency")
        self.assertEqual(reasons["CIV"], "watch")
        self.assertNotIn("OLD", reasons)
        quiet = entering_alerts(set(), rows, {"watch": False, "military": False, "emergency": False}, False)
        self.assertEqual(quiet, [])


class EmergencyTests(unittest.TestCase):
    def test_squawk_and_adsb_flag(self) -> None:
        from server.logic import is_emergency

        self.assertTrue(is_emergency("7700", None))
        self.assertTrue(is_emergency("7500", "none"))
        self.assertTrue(is_emergency("7600", None))
        self.assertTrue(is_emergency("1200", "general"))
        self.assertTrue(is_emergency("1200", "unlawful"))
        self.assertFalse(is_emergency("1200", "none"))
        self.assertFalse(is_emergency("1200", 0))
        self.assertFalse(is_emergency(None, None))


class IconDefaultTests(unittest.TestCase):
    def test_any_icon_choice_is_normalized_to_maverick(self) -> None:
        from server.logic import sanitize_config

        implied, errors = sanitize_config({"home": {"name": "KSEA", "lat": 47.45, "lon": -122.3}, "rangeNm": 20})
        self.assertEqual(errors, [])
        self.assertEqual(implied["icons"], "maverick")
        for value in ("classic", "linecut", "planform", "compact", "silhouette", "unknown", "maverick"):
            cfg, cfg_errors = sanitize_config({"home": {"name": "KSEA", "lat": 47.45, "lon": -122.3}, "rangeNm": 20, "icons": value})
            self.assertEqual(cfg_errors, [], value)
            self.assertEqual(cfg["icons"], "maverick", value)

    def test_migrate_forces_saved_icon_sets_to_maverick_and_bumps_schema(self) -> None:
        from copy import deepcopy
        from server.logic import CONFIG_SCHEMA
        from server.migrate import migrate_config

        for value in ("classic", "linecut", "planform", "compact", "silhouette"):
            out = migrate_config({"schema": 4, "icons": value, "home": {"name": "KSEA", "lat": 47.45, "lon": -122.3}, "rangeNm": 20})
            self.assertEqual(out["icons"], "maverick", value)
            self.assertEqual(out["schema"], CONFIG_SCHEMA, value)
        already = migrate_config({"schema": 4, "icons": "maverick", "rangeNm": 20})
        self.assertEqual(already["icons"], "maverick")
        self.assertEqual(already["schema"], CONFIG_SCHEMA)
        current = {"schema": CONFIG_SCHEMA, "icons": "maverick", "rangeNm": 20}
        self.assertEqual(migrate_config(deepcopy(current)), current)

    def test_setup_page_has_no_icon_set_selector(self) -> None:
        from pathlib import Path

        setup = (Path(__file__).resolve().parents[2] / "setup/index.html").read_text(encoding="utf-8")
        self.assertNotIn('id="icons"', setup)
        self.assertNotIn("Icon set", setup)
        self.assertNotIn('value="linecut"', setup)
        self.assertNotIn('value="classic"', setup)
        self.assertNotIn('value="planform"', setup)
        self.assertNotIn('value="compact"', setup)
        icons = (Path(__file__).resolve().parents[2] / "src/icons.ts").read_text()
        self.assertIn('export type IconSetId = "maverick"', icons)
        self.assertNotIn("function drawClassic", icons)
        self.assertNotIn("function drawCompact", icons)
        self.assertNotIn("function drawPlanform", icons)
        self.assertNotIn("export const ICON_SETS", icons)

    def test_maverick_mark_follows_category_and_type(self) -> None:
        self.assertEqual(classify("A1")["mark"], "light")
        self.assertEqual(classify("A1", type_code="C525")["mark"], "light")
        self.assertEqual(classify("A2")["mark"], "twin")
        self.assertEqual(classify("A2", type_code="BE58")["mark"], "twin")
        self.assertEqual(classify("A2", type_code="C525")["mark"], "bizjet")
        self.assertEqual(classify("A2", type_code="LJ45")["mark"], "bizjet")
        self.assertEqual(classify("A2", type_code="E55P")["mark"], "bizjet")
        self.assertEqual(classify("A2", type_code="GLF5")["mark"], "bizjet")
        self.assertEqual(classify("A2", type_code="FA7X")["mark"], "bizjet")
        self.assertEqual(classify("A2", type_code="HDJT")["mark"], "bizjet")
        self.assertEqual(classify("A2", type_code="C-680")["mark"], "bizjet")
        self.assertEqual(classify("A3")["mark"], "heavy")
        self.assertEqual(classify("A3", type_code="B738")["mark"], "heavy")
        self.assertEqual(classify("A3", type_code="CRJ9")["mark"], "bizjet")
        self.assertEqual(classify("A3", type_code="CRJ-200")["mark"], "bizjet")
        self.assertEqual(classify("A3", type_code="E190")["mark"], "bizjet")
        self.assertEqual(classify("A3", type_code="E145")["mark"], "bizjet")
        self.assertEqual(classify("A3", type_code="ERJ145")["mark"], "bizjet")
        self.assertEqual(classify("A4")["mark"], "heavy")
        self.assertEqual(classify("A5", type_code="E190")["mark"], "heavy")
        self.assertEqual(classify("A6")["mark"], "fighter")
        self.assertEqual(classify("A7")["mark"], "rotor")
        self.assertEqual(classify("B2")["mark"], "lighter")
        self.assertEqual(classify("B6")["mark"], "drone")
        self.assertEqual(classify(None)["mark"], "unknown")
        self.assertEqual(classify(None, type_code="B738")["mark"], "unknown")
        self.assertEqual(classify(None, type_code="C680")["mark"], "bizjet")
        self.assertEqual(classify("B1", type_code="CRJ2")["mark"], "bizjet")
        mil = classify("A3", db_flags=1, type_code="B77W")
        self.assertEqual(mil["kind"], "jet")
        self.assertEqual(mil["mark"], "heavy")
        self.assertTrue(mil["military"])
        self.assertEqual(classify("A6", db_flags=1)["mark"], "fighter")


class RingTests(unittest.TestCase):
    def test_outer_ring_is_the_selected_range(self) -> None:
        self.assertEqual(ring_distances(2), [0.5, 1.0, 1.5, 2.0])
        self.assertEqual(ring_distances(10), [2.5, 5.0, 7.5, 10.0])
        self.assertEqual(ring_distances(40), [10.0, 20.0, 30.0, 40.0])
        self.assertEqual(snap_range(12), 10)
        self.assertEqual(snap_range(500), 100)  # 1.0.7: max range 100 NM


class SolarTests(unittest.TestCase):
    def test_equinox_on_the_prime_meridian_is_near_six_and_eighteen(self) -> None:
        rise, sett = solar_hours(0, 0, date(2026, 3, 20), 0)
        self.assertGreater(rise, 5.5)
        self.assertLess(rise, 6.5)
        self.assertGreater(sett, 17.5)
        self.assertLess(sett, 18.5)

    def test_schedule_wraps_past_midnight(self) -> None:
        self.assertTrue(schedule_night(23, 22, 6))
        self.assertTrue(schedule_night(5, 22, 6))
        self.assertFalse(schedule_night(12, 22, 6))
        self.assertIsNotNone(datetime(2026, 1, 1, tzinfo=timezone.utc))
