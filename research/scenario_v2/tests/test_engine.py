import copy
import json
from pathlib import Path
import tempfile
import unittest

from research.scenario_v2 import engine as e
from research.scenario_v2.adapters import from_fusion
from research.scenario_v2.run import write_once


def fixture():
    return {"meta": {"day": "20261016", "jcd": "06", "rno": 7, "deadline": "19:00",
                     "captured_at": "2026-10-16T18:50:00+09:00"},
            "boats": [{"lane": i, "course": i, "racer_id": str(4000 + i), "avg_st": .12 + .01*i,
                       "exhibition_st": .15, "motor_top2_rate": 40, "course_top2_rate": 70-i*7,
                       "straight_time": 7+i*.03, "turn_time": 5+i*.03,
                       "lap_time": 37+i*.03, "exhibition_time": 6.7+i*.01} for i in range(1, 7)],
            "environment": {"wind_speed": 5, "wave_cm": 10},
            "baseline_picks": sorted(e.COMBINATIONS)[:10], "baseline_ranking": sorted(e.COMBINATIONS)}


NOW = "2026-10-16T18:51:00+09:00"


def forecast(data=None):
    return e.generate(data or fixture(), now=NOW)


def result(combo="1-2-3", method="逃げ"):
    order = list(map(int, combo.split("-")))
    order += [i for i in range(1, 7) if i not in order]
    return {"race_id": "20261016_06_07", "status": "settled", "observed_at": "2026-10-16T19:10:00+09:00",
            "trifecta": combo, "payout_per_100": 1400, "winning_method": method,
            "boats": [{"lane": i, "racer_id": str(4000+i), "actual_course": i,
                       "actual_st": .1+i*.01, "finish": order.index(i)+1} for i in range(1, 7)]}


class GuardTests(unittest.TestCase):
    def test_six_heads_and_real_generation_clock(self):
        f = forecast()
        self.assertEqual([r["lane"] for r in f["lanes"]], list(range(1, 7)))
        self.assertTrue(all(r["win_paths"] and r["loss_paths"] for r in f["lanes"]))
        self.assertEqual(f["generated_at"], NOW)
        self.assertFalse(f["probabilities_calibrated"])
        self.assertEqual(f["mode"], "prospective_uncheckpointed")

    def test_old_capture_does_not_backdate_live_forecast(self):
        with self.assertRaises(ValueError):
            e.generate(fixture(), now="2026-10-17T12:00:00+09:00")
        f = e.generate(fixture(), mode="replay", now="2026-10-17T12:00:00+09:00")
        self.assertEqual(f["mode"], "retrospective_replay")

    def test_nested_outcomes_cannot_hide_in_any_section(self):
        for key in ["actual_st", "actual_course", "finish", "payouts", "winning_method", "result", "current_result_json"]:
            data = fixture(); data["environment"]["nested"] = {key: None}
            with self.subTest(key=key), self.assertRaises(ValueError):
                forecast(data)

    def test_aware_timestamp_and_three_minute_boundary(self):
        d = fixture(); d["meta"]["captured_at"] = "2026-10-16T18:50:00"
        with self.assertRaises(ValueError): forecast(d)
        e.generate(fixture(), now="2026-10-16T18:57:00+09:00")
        with self.assertRaises(ValueError): e.generate(fixture(), now="2026-10-16T18:57:01+09:00")

    def test_future_database_or_observation_rejected(self):
        for key in ["db_snapshot_at", "source_observed_at"]:
            d = fixture(); d["meta"][key] = "2026-10-16T18:52:00+09:00"
            with self.assertRaises(ValueError): forecast(d)
        d = fixture(); d["boats"][0]["observations"] = [{"observed_at": "2026-10-16T18:52:00+09:00"}]
        with self.assertRaises(ValueError): forecast(d)

    def test_day_has_exactly_eight_digits(self):
        d = fixture(); d["meta"]["day"] = "2026101"
        with self.assertRaises(ValueError): forecast(d)

    def test_invalid_identity_measurements_and_duplicate_course(self):
        for value in [True, float("nan"), float("inf"), -1, 1.1]:
            d = fixture(); d["boats"][0]["avg_st"] = value
            with self.subTest(value=value), self.assertRaises(ValueError): forecast(d)
        for field, value in [("lane", 1.5), ("course", 2), ("racer_id", "4002")]:
            d = fixture(); d["boats"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): forecast(d)

    def test_baseline_requires_complete_unique_ranking(self):
        d = fixture(); d["baseline_ranking"] = d["baseline_ranking"][:-1]
        with self.assertRaises(ValueError): forecast(d)
        d = fixture(); d["baseline_picks"][1] = d["baseline_picks"][0]
        with self.assertRaises(ValueError): forecast(d)

    def test_missing_data_does_not_turn_into_observed_zero(self):
        d = fixture()
        for b in d["boats"]:
            for k in ["avg_st", "straight_time", "turn_time", "lap_time"]: b[k] = None
        f = forecast(d)
        self.assertEqual(f["virtual_card"]["picks"], d["baseline_picks"])
        self.assertTrue(all(h["supported_observations"] == 0 for r in f["lanes"] for h in r["hypotheses"]))


class TacticTests(unittest.TestCase):
    def test_course_changes_follow_the_boat_not_lane_number(self):
        d = fixture()
        for b, course in zip(d["boats"], [1, 2, 3, 5, 6, 4]): b["course"] = course
        f = forecast(d)
        self.assertEqual(f["lanes"][5]["predicted_course"], 4)
        self.assertIn("差し", [h["tactic"] for h in f["lanes"][5]["hypotheses"]])

    def test_linked_initiator_is_separate_from_winner(self):
        branches = forecast()["lanes"][3]["hypotheses"]
        linked = [h for h in branches if h["tactic"] == "まくり差し"]
        self.assertEqual({h["attack_origin_lane"] for h in linked}, {2, 3})
        self.assertTrue(all(h["attack_origin_lane"] != h["winner_lane"] for h in linked))

    def test_five_six_course_sashi_is_preserved(self):
        for row in forecast()["lanes"][4:]:
            self.assertIn("差し", [h["tactic"] for h in row["hypotheses"]])

    def test_makuri_and_sashi_have_distinct_followers_and_two_second_paths(self):
        row = forecast()["lanes"][2]
        hs = {h["tactic"]: h for h in row["hypotheses"] if h["tactic"] != "まくり差し"}
        self.assertNotEqual(hs["差し"]["formations"], hs["まくり"]["formations"])
        self.assertTrue(any(c["combination"].startswith("3-4-") for c in hs["まくり"]["formations"]))
        self.assertGreater(len({c["combination"].split("-")[1] for c in hs["まくり"]["formations"]}), 1)
        self.assertTrue(all(len(h["reactions"]) == 5 for h in row["hypotheses"]))

    def test_measurement_rank_requires_all_six(self):
        d = fixture(); d["boats"][5]["turn_time"] = None
        f = forecast(d)
        self.assertTrue(all(c["rank"] is None for r in f["lanes"] for h in r["hypotheses"]
                            for c in h["conditions"] if c["kind"] == "turn_rank"))

    def test_identical_timings_do_not_manufacture_six_top_ranks(self):
        d = fixture()
        for b in d["boats"]: b["turn_time"] = 5.5
        f = forecast(d)
        self.assertTrue(all(c["rank"] is None for r in f["lanes"] for h in r["hypotheses"]
                            for c in h["conditions"] if c["kind"] == "turn_rank"))

    def test_exhibition_st_motor_rate_and_wind_do_not_fabricate_foot_or_probability(self):
        original = forecast()
        d = fixture(); d["boats"][5]["exhibition_st"] = -.05; d["boats"][5]["motor_top2_rate"] = 99
        d["environment"] = {"wind_speed": 12, "wave_cm": 30}
        f = forecast(d)
        self.assertEqual(f["virtual_card"], original["virtual_card"])
        self.assertNotIn("expected_value", json.dumps(f))
        self.assertNotIn("trifecta_probability", json.dumps(f))

    def test_card_same_budget_unique_and_preserves_main(self):
        d = fixture(); f = forecast(d); c = f["virtual_card"]
        self.assertEqual(c["picks"][:6], d["baseline_picks"][:6])
        self.assertEqual(len(set(c["picks"])), 10)
        self.assertEqual(c["stake_yen"], 1000)
        self.assertLess(f["formation_candidate_count"], 120)


class ReviewTests(unittest.TestCase):
    def test_review_keeps_forecast_and_does_not_infer_causal_tactics_from_hit(self):
        f = forecast(); saved = copy.deepcopy(f)
        r = e.review(f, result())
        self.assertEqual(f, saved)
        self.assertFalse(r["causal_tactics_verified"])
        self.assertTrue(all(l["loss_cause"].startswith("未確定") for l in r["lanes"]))

    def test_tamper_and_race_mismatch_rejected(self):
        f = forecast(); f["lanes"][0]["name"] = "changed"
        with self.assertRaises(ValueError): e.review(f, result())
        r = result(); r["race_id"] = "20261016_06_08"
        with self.assertRaises(ValueError): e.review(forecast(), r)

    def test_entry_change_and_actual_st_are_post_race_diagnostics(self):
        r = result(); r["boats"][3]["actual_course"], r["boats"][5]["actual_course"] = 6, 4
        report = e.review(forecast(), r)
        self.assertEqual(report["entry_changed_lanes"], [4, 6])
        checks = [c for l in report["lanes"] for c in l["condition_checks"]]
        self.assertTrue(all(c["same_entry"] is False and not c["causal_failure_confirmed"] for c in checks))

    def test_missing_details_remain_unverified(self):
        r = result(); del r["boats"]; report = e.review(forecast(), r)
        self.assertFalse(report["entry_verified"])
        self.assertTrue(all(c["condition_occurred"] is None for l in report["lanes"] for c in l["condition_checks"]))

    def test_refund_accident_and_special_not_normal_failures(self):
        for status in ["pending", "accident", "f", "l", "void", "special"]:
            r = result(); r["status"] = status
            self.assertEqual(e.review(forecast(), r)["status"], "excluded")
        r = result(); r["refund_lanes"] = [3]
        self.assertEqual(e.review(forecast(), r)["reason"], "refund_or_accident")

    def test_actual_details_and_racer_must_match(self):
        r = result(); r["boats"][0]["racer_id"] = "9999"
        with self.assertRaises(ValueError): e.review(forecast(), r)
        r = result(); r["boats"][0]["finish"], r["boats"][1]["finish"] = 2, 1
        with self.assertRaises(ValueError): e.review(forecast(), r)

    def test_nuki_not_mistaken_for_first_turn_method_failure(self):
        report = e.review(forecast(), result(method="抜き"))
        self.assertIsNone(report["lanes"][0]["winner_method_matches"])

    def test_same_formation_does_not_prove_different_method(self):
        f = forecast()
        self.assertTrue(e.review(f, result())["method_and_formation_covered"])
        self.assertFalse(e.review(f, result(method="差し"))["method_and_formation_covered"])

    def test_exclusive_complete_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"frozen.json"; write_once(p, {"original": True})
            with self.assertRaises(FileExistsError): write_once(p, {"changed": True})
            self.assertEqual(json.loads(p.read_text()), {"original": True})
            self.assertEqual(list(Path(tmp).glob(".pending-*")), [])


if __name__ == "__main__":
    unittest.main()
