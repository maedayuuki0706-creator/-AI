"""Prospective integrity, refund arithmetic and isolated integration checks."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import fusion_shadow as fusion
import fusion_shadow_runner as runner

NOW = datetime(2026, 10, 12, 10, 0, tzinfo=fusion.JST)


def fixture():
    boats = [{"lane": i, "racer_id": str(4000 + i), "name": f"試験{i}",
              "current_class": "A1", "motor_number": i, "predicted_course": i,
              "exhibition_time": 6.7 + .02 * i, "exhibition_rank": i,
              "exhibition_st": .12 + .01 * i, "motor_top2_rate": 35,
              "win_rate": 6.0, "avg_st": .15} for i in range(1, 7)]
    rows = [{"combination": c, "probability": 1 / 120, "odds": 20.0}
            for c in sorted(fusion.COMBINATIONS)]
    analyses = {name: {"inputs": deepcopy(boats), "trifecta": deepcopy(rows),
                      "venue": "浜名湖", "model_version": name,
                      "preview": {"exhibition_count": 6, "wind_speed": 3, "wave_cm": 2},
                      "heads": {str(i): 1/6 for i in range(1, 7)}, "grade": "C"}
                for name in fusion.WEIGHTS}
    analyses["hiyori"]["features"] = [{"used": ["fixture_only"]}]
    analyses["sheet_db"]["sheet_database"] = {"enabled": True,
                         "snapshot_at": (NOW - timedelta(days=1)).isoformat()}
    request = {"day": "20261012", "jcd": "06", "rno": 1, "deadline": "10:15",
               "captured_at": (NOW - timedelta(seconds=10)).isoformat(),
               "source_fetched_at": (NOW - timedelta(seconds=5)).isoformat()}
    strategies = {"one": fusion.card(["1-2-3"], families=["official"]),
                  "two": fusion.card(["2-3-4"], families=["hiyori"])}
    return request, analyses, strategies


def record():
    request, analyses, strategies = fixture()
    return fusion.build_prediction(request, analyses, strategies, NOW)


def result(prediction, **extra):
    return {"key": prediction["key"], "status": "settled",
            "observed_at": "2026-10-12T10:20:00+09:00",
            "prediction_committed_at": "2026-10-12T10:01:00+09:00",
            "payouts": {"1-2-3": 12000}, "refund_lanes": [], **extra}


class FusionGuardTests(unittest.TestCase):
    def test_complete_distribution_and_main_cover(self):
        prediction = record()
        self.assertAlmostEqual(sum(r["probability"] for r in prediction["trifecta"]), 1)
        model = prediction["models"]["fusion"]
        self.assertEqual((len(model["main_picks"]), len(model["cover_picks"])), (6, 4))
        self.assertEqual(len(set(model["picks"])), 10)
        self.assertFalse(set(model["main_picks"]) & set(model["cover_picks"]))
        self.assertEqual(model["stake_yen"], 1000)
        self.assertFalse(prediction["probabilities_are_calibrated"])

    def test_correlated_duplicate_policies_cannot_increase_vote(self):
        _, analyses, strategies = fixture()
        odds = {c: 20 for c in fusion.COMBINATIONS}
        first = fusion.rank_fusion(analyses, strategies, odds)
        for i in range(30):
            strategies[f"duplicate{i}"] = deepcopy(strategies["one"])
        self.assertEqual(first, fusion.rank_fusion(analyses, strategies, odds))

    def test_db_distribution_is_used_directly(self):
        _, analyses, _ = fixture()
        for row in analyses["sheet_db"]["trifecta"]:
            row["probability"] = int(row["combination"] == "6-5-4")
        rows, _ = fusion.rank_fusion(analyses, {}, {})
        winner = next(r for r in rows if r["combination"] == "6-5-4")
        self.assertAlmostEqual(winner["probability"], .25 + .75 / 120)

    def test_invalid_distribution_never_silently_falls_back(self):
        request, analyses, strategies = fixture()
        analyses["hiyori"]["trifecta"].pop()
        with self.assertRaises(ValueError):
            fusion.build_prediction(request, analyses, strategies, NOW)
        request, analyses, strategies = fixture()
        del analyses["sheet_db"]
        with self.assertRaises(ValueError):
            fusion.build_prediction(request, analyses, strategies, NOW)

    def test_timing_and_future_snapshot_guards(self):
        for field, value in (("captured_at", NOW + timedelta(seconds=1)),
                             ("source_fetched_at", NOW + timedelta(seconds=1)),
                             ("captured_at", NOW - timedelta(seconds=181))):
            request, analyses, strategies = fixture()
            request[field] = value.isoformat()
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                fusion.build_prediction(request, analyses, strategies, NOW)
        request, analyses, strategies = fixture()
        analyses["sheet_db"]["sheet_database"]["snapshot_at"] = NOW.isoformat()
        with self.assertRaises(ValueError):
            fusion.build_prediction(request, analyses, strategies, NOW)
        request, analyses, strategies = fixture()
        with self.assertRaises(ValueError):
            fusion.build_prediction(request, analyses, strategies, NOW + timedelta(minutes=13))
        with self.assertRaises(ValueError):
            fusion.build_prediction(request, analyses, strategies, NOW + timedelta(days=1))
        with self.assertRaises(ValueError):
            fusion.aware(datetime(2026, 10, 12))

    def test_current_outcomes_and_mismatched_entrants_rejected(self):
        for field in ("finish", "actual_st", "actual_course", "payout"):
            request, analyses, strategies = fixture()
            analyses["existing"]["inputs"][0][field] = 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                fusion.build_prediction(request, analyses, strategies, NOW)
        request, analyses, strategies = fixture()
        analyses["hiyori"]["inputs"][0]["racer_id"] = "9999"
        with self.assertRaises(ValueError):
            fusion.build_prediction(request, analyses, strategies, NOW)

    def test_missing_hiyori_and_disabled_db_rejected(self):
        request, analyses, strategies = fixture()
        analyses["hiyori"]["features"] = []
        with self.assertRaises(ValueError):
            fusion.build_prediction(request, analyses, strategies, NOW)
        request, analyses, strategies = fixture()
        analyses["sheet_db"]["sheet_database"]["enabled"] = False
        with self.assertRaises(ValueError):
            fusion.build_prediction(request, analyses, strategies, NOW)

    def test_context_is_frozen_and_missing_is_unknown(self):
        request, analyses, strategies = fixture()
        self.assertFalse(record()["context_available"])
        context = {"key": "20261012_06_01", "observed_at": NOW.isoformat(),
                   "types": [], "outcome": None, "baseline_in_loss_suppressed": True}
        frozen = fusion.build_prediction(request, analyses, strategies, NOW, context=context)
        self.assertTrue(frozen["context_available"])
        self.assertTrue(all(r["context_bonus"] == 0 for r in frozen["trifecta"]))
        context["observed_at"] = (NOW + timedelta(minutes=1)).isoformat()
        with self.assertRaises(ValueError):
            fusion.build_prediction(request, analyses, strategies, NOW, context=context)

    def test_atomic_immutable_predictions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prediction.json"
            with ThreadPoolExecutor(max_workers=4) as pool:
                outcomes = list(pool.map(lambda n: fusion.write_once(path, {"value": n}), range(10)))
            self.assertEqual(sum(outcomes), 1)
            value = path.read_bytes()
            self.assertFalse(fusion.write_once(path, {"value": "replacement"}))
            self.assertEqual(path.read_bytes(), value)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)


class EvaluationTests(unittest.TestCase):
    def test_dead_heat_payouts_and_refunds_without_double_count(self):
        prediction = record()
        outcome = fusion.evaluate(prediction, result(prediction, payouts={"1-2-3": 12000, "2-3-4": 800},
                                                    refund_lanes=[6]), NOW + timedelta(minutes=20))
        model = outcome["models"]["fusion"]
        self.assertEqual(model["return_yen"], 12800 + model["refund_yen"])
        self.assertTrue(model["hit"])
        self.assertTrue(model["manshu_hit"])
        self.assertEqual(model["stake_yen"], model["net_stake_yen"] + model["refund_yen"])

    def test_void_special_and_pending_are_not_normal_losses(self):
        prediction = record()
        now = NOW + timedelta(minutes=20)
        outcome = fusion.evaluate(prediction, result(prediction, status="void", payouts={}), now)
        model = outcome["models"]["fusion"]
        self.assertEqual(model["return_yen"], 1000)
        self.assertFalse(model["eligible_race"])
        outcome = fusion.evaluate(prediction, result(prediction, status="special", payouts={}, special_per_100=70), now)
        self.assertEqual(outcome["models"]["fusion"]["return_yen"], 700)
        self.assertFalse(outcome["models"]["fusion"]["eligible_race"])
        self.assertIsNone(fusion.evaluate(prediction, result(prediction, status="pending", payouts={}), now))

    def test_durable_pre_deadline_save_and_result_guards(self):
        prediction = record()
        now = NOW + timedelta(minutes=20)
        with self.assertRaises(ValueError):
            fusion.evaluate(prediction, result(prediction, prediction_committed_at=prediction["deadline_at"]), now)
        with self.assertRaises(ValueError):
            fusion.evaluate(prediction, result(prediction), NOW)
        with self.assertRaises(ValueError):
            fusion.evaluate(prediction, result(prediction, key="20261012_06_02"), now)
        prediction["models"]["fusion"]["picks"].pop()
        with self.assertRaises(ValueError):
            fusion.evaluate(prediction, result(prediction), now)

    def test_summary_excludes_pending_and_retrospective_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prediction = record()
            fusion.write_once(root / "predictions/20261012/one.json", prediction)
            summary = fusion.summarize(root)
            self.assertEqual(summary["pending_races"], 1)
            self.assertEqual(summary["models"], {})
            outcome = fusion.evaluate(prediction, result(prediction), NOW + timedelta(minutes=20))
            fusion.write_once(root / "evaluations/20261012/one.json", outcome)
            retrospective = deepcopy(prediction)
            retrospective["mode"] = "retrospective_diagnostic"
            fusion.write_once(root / "predictions/20261012/diagnostic.json", retrospective)
            summary = fusion.summarize(root)
            self.assertEqual(summary["pending_races"], 0)
            self.assertEqual(summary["models"]["fusion"]["eligible_races"], 1)
            self.assertEqual(summary["models"]["fusion"]["roi_pct"], 1200)
            old_engine = deepcopy(prediction)
            old_engine["version"] = "all-ai-fusion-shadow-v1"
            fusion.write_once(root / "predictions/20261012/old-engine.json", old_engine)
            summary = fusion.summarize(root)
            self.assertEqual(summary["excluded_other_engine_races"], 1)
            self.assertEqual(summary["pending_races"], 0)


class RunnerIsolationTests(unittest.TestCase):
    def test_later_official_details_are_appended_without_replacing_forecast_or_first_result(self):
        import direct_discord_notify as base
        import daily_report
        import race_context
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=record();filename=p['key']+'.json'
            forecast=root/'predictions'/p['day']/filename
            original=root/'evaluations'/p['day']/filename
            fusion.write_once(forecast,p)
            fusion.write_once(root/'checkpoints'/p['day']/filename,{
                'prediction_digest':p['digest'],'prediction_committed_at':'2026-10-12T10:01:00+09:00','commit_sha':'a'*40})
            outcome=fusion.evaluate(p,result(p),NOW+timedelta(minutes=20))
            fusion.write_once(original,outcome)
            before=(forecast.read_bytes(),original.read_bytes())
            details={'method':'逃げ','finish':[{'lane':l,'status':'finished','course':l,'st':.12} for l in range(1,7)]}
            with patch.object(runner,'now_jst',return_value=NOW+timedelta(minutes=20)), \
                 patch.object(base,'fetch',return_value='official-fixture-only'), \
                 patch.object(daily_report,'parse_payout',return_value=result(p)), \
                 patch.object(race_context,'parse_result',return_value=details):
                self.assertEqual(runner.collect_results(root,time.monotonic()+60)['settled'],1)
                self.assertEqual(runner.collect_results(root,time.monotonic()+60)['settled'],0)
            self.assertEqual(before,(forecast.read_bytes(),original.read_bytes()))
            extra=runner.load(root/'official_verifications'/p['day']/filename)
            self.assertTrue(extra['evaluation']['scenario_review']['boats'][0]['method_matches_win_hypothesis'])

    def test_outside_race_hours_writes_readiness_but_no_forecast(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, "now_jst", return_value=NOW.replace(hour=2)), \
                patch.object(runner, "collect_card", side_effect=AssertionError("No live requests expected")), \
                patch.object(runner, "collect_results", return_value={"settled": 0, "errors": []}):
            self.assertEqual(runner.run(directory), 0)
            self.assertEqual(runner.load(Path(directory) / "heartbeat.json")["status"], "waiting_for_race_hours")
            self.assertFalse((Path(directory) / "predictions").exists())

    def test_native_builders_integration_has_no_delivery_or_results(self):
        import direct_discord_notify as base
        import hiyori_model
        import hiyori_source
        import opportunity_alerts
        import pt2_sheet_db
        import x_post_delivery
        from prediction_engine import analyze_race
        _, analyses, _ = fixture()
        boats = analyses["existing"]["inputs"]
        official = analyze_race({"race": {"venue": "浜名湖", "wind_speed": 3, "wave_cm": 2},
                                "boats": boats, "trifecta_odds": {c: 20 for c in fusion.COMBINATIONS}})
        official.update(inputs=boats, preview=analyses["existing"]["preview"], heads={str(i): 1/6 for i in range(1, 7)}, grade="C")
        database = {"players": {str(4000+i): {"course_win": [60, 20, 20, 15, 8, 3], "maintenance_grade": 3} for i in range(1, 7)},
                    "motors": {}, "venues": {"06": {"course_win": [55, 18, 17, 12, 7, 2]}},
                    "meta": {"snapshot_at": "2026-10-11T07:00:00+09:00"}}
        forbidden = AssertionError("Shadow code must never dispatch, log production predictions or read live results")
        with patch.object(base, "analyze_official", return_value=official), \
                patch.object(hiyori_source, "fetch_race", return_value={"source_url": "fixture-only", "rows": []}), \
                patch.object(hiyori_model, "analyze", return_value=analyses["hiyori"]), \
                patch.object(pt2_sheet_db, "load_database", return_value=database), \
                patch.object(runner, "now_jst", return_value=NOW), \
                patch.object(base, "send_discord", side_effect=forbidden), \
                patch.object(base, "log_prediction", side_effect=forbidden), \
                patch.object(base, "fetch", side_effect=forbidden), \
                patch.object(opportunity_alerts, "_send", side_effect=forbidden), \
                patch.object(opportunity_alerts, "_append_log", side_effect=forbidden), \
                patch.object(x_post_delivery, "post_to_x", side_effect=forbidden):
            prediction, snapshot = runner.build_live("20261012", "06", 1, "10:15", prefetch=False)
        self.assertEqual(len(prediction["models"]["fusion"]["picks"]), 10)
        for key in ("native_pt2_balanced", "native_pt2_probability", "native_pt2_value", "native_pt2_longshot",
                    "native_comparison_prototype1", "native_comparison_prototype3", "native_featured_plan", "native_long_selected"):
            self.assertIn(key, prediction["models"])
        self.assertEqual(set(snapshot["analyses"]), set(fusion.WEIGHTS))

    def test_checkpoint_refers_to_committed_bytes_and_is_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            root = repository / "data/fusion_shadow"
            prediction = record()
            path = root / "predictions/20261012/one.json"
            fusion.write_once(path, prediction)
            commands = [["git", "init", "-q"], ["git", "config", "user.name", "test"],
                        ["git", "config", "user.email", "test@example.invalid"],
                        ["git", "add", "."], ["git", "commit", "-qm", "frozen test"]]
            for command in commands:
                subprocess.run(command, cwd=repository, check=True)
            sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
            with patch.object(runner, "now_jst", return_value=NOW + timedelta(minutes=1)):
                self.assertEqual(runner.checkpoint(root, sha), 1)
                self.assertEqual(runner.checkpoint(root, sha), 0)
            receipt = runner.load(root / "checkpoints/20261012/one.json")
            self.assertEqual(receipt["prediction_digest"], prediction["digest"])
            self.assertTrue(receipt["eligible_checkpoint"])


if __name__ == "__main__":
    unittest.main()
