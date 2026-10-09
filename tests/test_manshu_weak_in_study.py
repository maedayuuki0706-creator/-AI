import unittest
from copy import deepcopy

from manshu_weak_in_study import analyze_weak_in


def make_case(key, jcd, venue, winner, pay, classes, ranks, alert=False):
    pre_boats = []
    for i in range(1, 7):
        pre_boats.append({
            "lane": i, "class": classes.get(i), "ex_rank": ranks.get(i),
            "ex_time": 6.80 if i == 1 else 6.65 if i == 2 else 6.81,
            "ex_st": 0.20 if i == 1 else 0.08 if i == 2 else 0.18,
            "ex_course": i,
        })
    return {
        "key": key,
        "pre_race_features": {
            "day": "20261010", "jcd": jcd, "venue": venue,
            "rno": int(key[-2:]), "six_boat_exhibition": pre_boats,
            "wind_m": 3, "wave_cm": 4, "lane1_ex_rank": ranks.get(1),
            "outside_ex_time_advantage_s": 0.15, "inner_dip_s": 0.12
        },
        "pre_race_decision": {"alert": alert, "types": ["イン敗北警戒"] if alert else [],
                               "in_loss_suppressed_as_baseline": not alert},
        "observed_result": {
            "trifecta": winner, "payout_per_100": pay, "manshu": pay >= 10000,
            "head": winner.split("-")[0],
            "second": winner.split("-")[1], "third": winner.split("-")[2],
            "five_in_top3": "5" in winner.split("-"),
            "six_in_top3": "6" in winner.split("-"),
            "source": "official-test"
        },
    }


class WeakInStudyTests(unittest.TestCase):
    def setUp(self):
        self.toda_normal = make_case(
            "20261010_02_01", "02", "戸田", "2-3-1", 3500,
            {1: "B1", 2: "A1", 3: "A1"}, {1: 6, 2: 1, 3: 2})
        self.toda_outer_manshu = make_case(
            "20261010_02_02", "02", "戸田", "5-6-4", 58900,
            {1: "B1", 2: "B1", 3: "A2", 5: "A1"}, {1: 6, 2: 3, 3: 1, 5: 2})
        self.edogawa_escape_manshu = make_case(
            "20261010_03_03", "03", "江戸川", "1-5-6", 10640,
            {1: "A1", 2: "B1", 3: "B1", 5: "A2"}, {1: 2, 2: 6, 3: 5, 5: 1})

    def test_non1_normal_a1_head_is_not_manshu(self):
        data = analyze_weak_in([self.toda_normal, self.toda_outer_manshu])
        self.assertEqual(data["base"]["races"], 2)
        self.assertEqual(data["base"]["manshu_races"], 1)
        self.assertEqual(data["base"]["head_distribution_all"], {2: 1, 5: 1})
        self.assertEqual(data["cohorts"]["a1_in_2or3"]["manshu_races"], 0)
        self.assertEqual(data["cohorts"]["a1_in_2or3"]["races"], 1)
        self.assertEqual(data["cohorts"]["no_a1_in_2or3"]["manshu_races"], 1)
        self.assertEqual(data["manshu_cases"][0]["outcome_pattern"], "4_5_6号艇頭_外攻め")
        self.assertFalse(data["weak_in_head_does_not_imply_manshu"] is False)

    def test_weak_in_venue_can_1_head_manshu_on_followers(self):
        data = analyze_weak_in([self.edogawa_escape_manshu])
        self.assertEqual(data["one_head_manshu_count"], 1)
        self.assertEqual(data["base"]["manshu_1_head_with_5_or_6"], 1)
        self.assertEqual(data["manshu_cases"][0]["outcome_pattern"], "イン艇頭_ヒモ荒れ")

    def test_unverified_venues_do_not_automatically_become_weak(self):
        other = deepcopy(self.toda_outer_manshu)
        other["pre_race_features"]["jcd"] = "16"
        study = analyze_weak_in([other])
        self.assertEqual(study["base"]["races"], 0)
        self.assertEqual(study["manshu_cases"], [])

    def test_grade_unknown_is_not_no_a1(self):
        case = deepcopy(self.toda_outer_manshu)
        case["pre_race_features"]["six_boat_exhibition"][2]["class"] = ""
        data = analyze_weak_in([case])
        self.assertEqual(data["cohorts"]["unknown_2or3_grade"]["races"], 1)
        self.assertNotIn("no_a1_in_2or3", data["cohorts"])

    def test_no_result_never_creates_manshu(self):
        row = deepcopy(self.toda_outer_manshu)
        row["observed_result"] = {}
        data = analyze_weak_in([row])
        self.assertEqual(data["base"]["races"], 0)
        self.assertEqual(data["base"]["manshu_races"], 0)

    def test_study_does_not_modify_pre_race_features(self):
        case = deepcopy(self.edogawa_escape_manshu)
        before = deepcopy(case)
        data = analyze_weak_in([case])
        self.assertEqual(case, before)
        self.assertTrue(data["no_future_values_in_features"])
        self.assertEqual(data["model_training_state"], "offline_case_study_not_predictor_retraining")
        self.assertTrue(data["base"]["insufficient_for_stable_generalization"])


if __name__ == "__main__":
    unittest.main()
