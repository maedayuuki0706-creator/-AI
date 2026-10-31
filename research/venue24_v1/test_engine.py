"""Offline unit tests, no network and no production imports."""
import json
import tempfile
import unittest
from pathlib import Path
from research.venue24_v1 import engine as e


def fixture(code="23", day="20261031", rno=7):
    return {
        "day": day, "jcd": code, "rno": rno, "deadline": "13:00",
        "captured_at": "2026-10-31T12:15:00+09:00", "settled": True,
        "rows": [{
            "lane": i, "racer_id": str(5000 + i), "name": "R" + str(i),
            "motor_number": i * 2,
            "exhibition_time": 6.5 + i / 100, "exhibition_st": i / 100,
            "exhibition_course": i, "finish": i, "actual_course": i,
            "actual_st": .1, "method": "逃げ",
        } for i in range(1, 7)],
    }


def original(raw):
    return {
        "race_id": e.race_id(raw["day"], raw["jcd"], raw["rno"]),
        "status": "ok",
        "acquisition": {
            "retrieved_at": "2026-10-31T12:20:00+09:00",
            "url": "https://www.boatrace-karatsu.jp/example",
            "sha256": "f" * 64,
            "published_at": None,
        },
        "rows": [{
            "lane": i, "racer_id": str(5000 + i), "motor_number": i * 2,
            "lap_time": 36 + i / 10,
            "turn_time": 5 + i / 10,
            "straight_time": 7 + i / 10,
        } for i in range(1, 7)],
    }


class Venue24Tests(unittest.TestCase):
    def test_catalog_all_24_and_measurement_differences(self):
        self.assertEqual(len(e.VENUES), 24)
        self.assertEqual(set(e.VENUES), {f"{x:02d}" for x in range(1, 25)})
        self.assertEqual(e.VENUES["03"]["expected_metrics"], [])
        self.assertIn("half_lap_time", e.VENUES["01"]["expected_metrics"])
        self.assertNotIn("lap_time", e.VENUES["01"]["expected_metrics"])
        self.assertNotIn("straight_time", e.VENUES["18"]["expected_metrics"])
        self.assertIn("turn_time", e.VENUES["23"]["expected_metrics"])

    def test_join_all_six_racer_and_motor_ids(self):
        raw = fixture()
        result = e.join_official_original(raw, original(raw))
        self.assertEqual(result["original_status"], "captured_before_deadline")
        self.assertEqual(result["rows"][0]["original"]["lap_time"], 36.1)
        self.assertFalse(result["original_acquisition"]["source_publish_time_verified"])
        self.assertFalse(result["original_acquisition"]["scoring_connected"])

    def test_mismatched_id_never_joins(self):
        raw = fixture()
        data = original(raw)
        data["rows"][4]["racer_id"] = "9999"
        result = e.join_official_original(raw, data)
        self.assertEqual(result["original_status"], "racer_identity_mismatch")
        self.assertTrue(all(x["original"] is None for x in result["rows"]))

    def test_after_deadline_rejected(self):
        raw = fixture()
        data = original(raw)
        data["acquisition"]["retrieved_at"] = "2026-10-31T13:01:00+09:00"
        self.assertEqual(e.join_official_original(raw, data)["original_status"], "captured_after_deadline")

    def test_edogawa_original_not_fabricated(self):
        raw = fixture(code="03")
        result = e.join_official_original(raw)
        self.assertEqual(result["original_status"], "not_published_at_venue")
        self.assertTrue(all(x["original"] is None for x in result["rows"]))

    def test_no_same_day_outcome_leakage(self):
        early = e.join_official_original(fixture(day="20261030", rno=1))
        today = e.join_official_original(fixture(day="20261031", rno=2))
        profiles = e.fit_venue_profiles([early, today], "20261031")
        self.assertEqual(profiles["23"]["training_races"], 1)
        self.assertEqual(profiles["03"]["training_races"], 0)
        output = e.predict_research(profiles["23"], today)
        self.assertEqual(output["status"], "insufficient_verified_history")
        self.assertTrue(all(b["research_index"] is None for b in output["boats"]))

    def test_short_history_does_not_invent_probabilities(self):
        record = e.join_official_original(fixture())
        profiles = e.fit_venue_profiles([record], "20261101")
        self.assertIsNone(profiles["23"]["course_observations"]["1"]["observed_win_rate"])
        self.assertIsNone(profiles["23"]["racer_observations"]["5001"]["observed_win_rate"])

    def test_immutable_archiving(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "r.json"
            val = {"ok": True}
            self.assertTrue(e.immutable_json(path, val))
            self.assertFalse(e.immutable_json(path, val))
            with self.assertRaises(ValueError):
                e.immutable_json(path, {"ok": False})

    def test_full_file_build_creates_all_models_and_player_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "official" / "20261031"
            folder.mkdir(parents=True)
            (folder / "23_07.json").write_text(json.dumps(fixture(), ensure_ascii=False))
            orig = root / "original"
            orig.mkdir()
            (orig / "karatsu.json").write_text(json.dumps(original(fixture()), ensure_ascii=False))
            summary = e.build(root / "official", orig, root / "out", "20261101")
            self.assertEqual(summary["official_races_archived"], 1)
            self.assertTrue(summary["all_24_models_created"])
            self.assertEqual(summary["original_status_counts"]["captured_before_deadline"], 1)
            self.assertTrue((root / "out" / "models" / "20261101" / "03.json").is_file())
            self.assertTrue((root / "out" / "players" / "23" / "5001.json").is_file())


if __name__ == "__main__":
    unittest.main()
