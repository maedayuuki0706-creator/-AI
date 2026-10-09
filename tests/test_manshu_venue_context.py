"""The weak-in venue itself is NOT an exceptional in-loss alert.

Only an A1 2/3-boat plus unusual exhibition or severe-water corroboration
can pass the internal in-loss gate at verified weak-in venues.
"""
import unittest
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from manshu_shadow_watch import classify
from manshu_shadow_learning import export_learning


class VenueAdjustedUpsetTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 10, 11, 20, tzinfo=ZoneInfo("Asia/Tokyo"))
        self.snapshot = {
            "day": "20261010", "jcd": "02", "rno": 4,
            "venue": "戸田", "deadline": "11:40", "settled": False,
            "rows": [
                {
                    "lane": i,
                    "current_class": "B1",
                    "exhibition_st": 0.22 if i == 1 else 0.09,
                    "exhibition_time": 7.03 if i == 1 else 6.81,
                    "exhibition_rank": 6 if i == 1 else i-1,
                    "wind_m": 4, "wave_cm": 4,
                    "actual_st": None, "actual_course": None, "finish": None,
                }
                for i in range(1, 7)
            ],
        }

    def check_weak_place(self, jcd, expected_win_pct):
        p = deepcopy(self.snapshot)
        p["jcd"] = jcd
        obs = classify(p, self.now)
        self.assertIsNotNone(obs)
        self.assertFalse(obs["alert"])
        self.assertEqual(obs["types"], [])
        self.assertTrue(obs["baseline_in_loss_suppressed"])
        self.assertEqual(obs["venue_context"]["baseline_course1_win_pct"], expected_win_pct)
        self.assertEqual(obs["venue_context"]["a1_2or3_lanes"], [])
        return obs

    def test_verified_weak_in_venues_never_alert_for_baseline_alone(self):
        self.check_weak_place("02", 42.8)
        self.check_weak_place("03", 48.8)
        self.check_weak_place("04", 40.5)

    def test_toda_2_a1_alone_does_not_make_common_non1_head_an_alert(self):
        p = deepcopy(self.snapshot)
        p["rows"][1]["current_class"] = "A1"
        p["rows"][1]["exhibition_st"] = 0.18
        p["rows"][1]["exhibition_time"] = 6.98
        obs = classify(p, self.now)
        self.assertFalse(obs["alert"])
        self.assertTrue(obs["baseline_in_loss_suppressed"])
        self.assertEqual(obs["venue_context"]["a1_2or3_lanes"], [2])
        self.assertEqual(obs["venue_context"]["strong_attacker_lanes"], [])
        self.assertIn("通常の頭候補", obs["venue_context"]["decision_reason"])

    def test_toda_strong_a1_second_lane_plus_exhibition_can_make_exception(self):
        p = deepcopy(self.snapshot)
        p["rows"][1]["current_class"] = "A1"
        obs = classify(p, self.now)
        self.assertTrue(obs["alert"])
        self.assertIn("イン敗北警戒", obs["types"])
        self.assertFalse(obs["baseline_in_loss_suppressed"])
        self.assertTrue(obs["venue_context"]["strong_exception"])
        self.assertEqual(obs["venue_context"]["strong_attacker_lanes"], [2])
        self.assertEqual(obs["pre_boats"][1]["class"], "A1")

    def test_toda_strong_a1_third_lane_plus_exhibition_can_make_exception(self):
        p = deepcopy(self.snapshot)
        p["rows"][2]["current_class"] = "A1"
        obs = classify(p, self.now)
        self.assertIn("イン敗北警戒", obs["types"])
        self.assertEqual(obs["venue_context"]["strong_attacker_lanes"], [3])

    def test_a1_in_4th_boat_does_not_qualify_2_3_exception(self):
        p = deepcopy(self.snapshot)
        p["rows"][3]["current_class"] = "A1"
        obs = classify(p, self.now)
        self.assertFalse(obs["alert"])
        self.assertTrue(obs["baseline_in_loss_suppressed"])

    def test_ordinary_venue_keeps_existing_upset_rule(self):
        p = deepcopy(self.snapshot)
        p["jcd"] = "16"
        p["venue"] = "児島"
        obs = classify(p, self.now)
        self.assertTrue(obs["alert"])
        self.assertIn("イン敗北警戒", obs["types"])
        self.assertFalse(obs["venue_context"]["weak_in_baseline"])

    def test_follower_alert_remains_independent_at_weak_venue(self):
        p = deepcopy(self.snapshot)
        for i, row in enumerate(p["rows"], 1):
            row["exhibition_st"] = 0.14 if i == 1 else 0.13
            row["exhibition_time"] = 6.80 if i == 1 else 6.90
            row["exhibition_rank"] = 2 if i == 1 else (1 if i == 5 else 4)
        obs = classify(p, self.now)
        self.assertTrue(obs["alert"])
        self.assertNotIn("イン敗北警戒", obs["types"])
        self.assertIn("ヒモ荒れ警戒", obs["types"])

    def test_suppressed_manshu_goes_into_missed_study_with_reason(self):
        entry = self.check_weak_place("02", 42.8)
        entry["outcome"] = {
            "settled": True, "trifecta": "2-3-5",
            "payout_per_100": 14600, "manshu": True,
        }
        study = export_learning("20261010", {entry["key"]: entry})
        self.assertEqual(study["missed_manshu_count"], 1)
        missed = study["missed_manshu_cases"][0]
        self.assertTrue(missed["pre_race_decision"]["in_loss_suppressed_as_baseline"])
        self.assertIn("公式弱イン場のため通常のイン敗北シグナルを抑制",
                      missed["pre_race_decision"]["not_triggered_reasons"])
        self.assertIn("公式弱イン場（1コース1着率50%未満）",
                      missed["pre_race_features"]["tags"])


if __name__ == "__main__":
    unittest.main()
