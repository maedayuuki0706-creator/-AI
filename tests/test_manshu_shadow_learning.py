import unittest
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import manshu_shadow_watch as shadow
from manshu_shadow_learning import export_learning, pre_race_tags


class MissedManshuLearningTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 10, 11, 20, tzinfo=ZoneInfo("Asia/Tokyo"))
        self.snapshot = {
            "day": "20261010", "jcd": "16", "rno": 5,
            "deadline": "11:40", "settled": False,
            "rows": [
                {"lane": n, "exhibition_st": 0.09 + n * 0.01,
                 "exhibition_time": 6.82 + n * 0.01,
                 "exhibition_rank": n, "wind_m": 1, "wave_cm": 1,
                 "actual_st": None, "actual_course": None, "finish": None}
                for n in range(1, 7)
            ]
        }
    def test_missed_10k_saved_as_separate_case_and_not_predicted(self):
        entry = shadow.classify(self.snapshot, self.now)
        self.assertIsNotNone(entry)
        self.assertFalse(entry["alert"])
        self.assertIsNone(entry["outcome"])
        self.assertTrue(shadow.adjudicate(entry, {
            "16:5": {"status": "settled", "payouts": {"3-5-2": 13560}}
        }))
        learning = export_learning("20261010", {entry["key"]: entry})
        self.assertEqual(learning["missed_manshu_count"], 1)
        self.assertEqual(learning["alert_manshu_count"], 0)
        case = learning["missed_manshu_cases"][0]
        self.assertEqual(case["sniper_join_key"], entry["key"])
        self.assertFalse(case["pre_race_decision"]["alert"])
        self.assertIn("気象ゲート不成立（風<3m・波<3cm）",
                      case["pre_race_decision"]["not_triggered_reasons"])
        self.assertEqual(case["observed_result"]["head"], "3")
        self.assertTrue(case["observed_result"]["manshu"])
        self.assertTrue(case["pre_race_features"]["features_complete"])
        self.assertNotIn("trifecta", case["pre_race_features"])
        self.assertEqual(learning["training_status"], "case_collection_only_not_model_retraining")
        self.assertEqual(shadow.summarize("20261010", {entry["key"]: entry})["missed_manshu_races"], 1)

    def test_negative_control_and_no_overfitting(self):
        entry = shadow.classify(self.snapshot, self.now)
        yes = deepcopy(entry)
        yes["outcome"] = {
            "settled": True, "trifecta": "1-2-4",
            "payout_per_100": 1200, "manshu": False
        }
        missed = deepcopy(entry)
        missed["key"] = "20261010_16_06"
        missed["rno"] = 6
        missed["outcome"] = {
            "settled": True, "trifecta": "3-5-2",
            "payout_per_100": 13560, "manshu": True
        }
        result = export_learning("20261010", {x["key"]: x for x in (yes, missed)})
        self.assertEqual(result["negative_control_count"], 1)
        self.assertEqual(result["missed_manshu_count"], 1)
        self.assertEqual(result["tag_comparisons"]["低風波"]["n"], 2)
        self.assertEqual(result["tag_comparisons"]["低風波"]["manshu"], 1)
        self.assertFalse(result["tag_comparisons"]["低風波"]["minimum_20_race_sample"])

    def test_unobserved_official_manshu_is_not_mislabeled_rule_miss(self):
        missing = {
            "16:7": {"status":"settled","payouts":{"5-2-3":167940}},
            "16:8": {"status":"settled","payouts":{"1-2-3":1400}},
        }
        actual = export_learning("20261010", {}, missing)
        self.assertEqual(actual["missed_manshu_count"], 0)
        self.assertEqual(actual["unobserved_official_manshu_count"], 1)
        self.assertEqual(actual["unobserved_official_resolved_races"], 2)
        self.assertEqual(actual["total_unalerted_or_unobserved_manshu_cases"], 1)
        self.assertIsNone(actual["unobserved_official_manshu_cases"][0]["pre_race_features"])
        self.assertFalse(actual["unobserved_official_manshu_cases"][0]["eligible_for_signal_learning"])

    def test_missing_result_never_looks_like_no_manshu(self):
        entry = shadow.classify(self.snapshot, self.now)
        result = export_learning("20261010", {entry["key"]: entry})
        self.assertEqual(result["resolved_examples"], 0)
        self.assertEqual(result["negative_control_count"], 0)
        self.assertEqual(result["missed_manshu_count"], 0)


if __name__ == "__main__":
    unittest.main()
