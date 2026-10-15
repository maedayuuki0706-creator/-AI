import copy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from research_fusion_roi_replay import ALL_COMBOS
from research_no_alt_head_replay import choose, POLICY, SOURCE_SHA
from research_no_alt_head_holdout import evaluate, validate_plan

BASE = Path(__file__).resolve().parents[1]
CANDIDATE = BASE / "research_no_alt_head_v1.json"
PLAN = BASE / "research_no_alt_head_holdout_plan.json"


def fixture(root, day="20261016"):
    key = day+"_01_01"
    date = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    record = {"key": key, "day": day, "code_sha": SOURCE_SHA,
        "mode": "prospective_shadow", "research_only": True,
        "created_at": date+"T10:00:00+09:00", "deadline_at": date+"T10:10:00+09:00",
        "trifecta": [{"combination": c, "probability": 1/120,
                      "rank_score": 120-i, "cover_score": 120-i}
                     for i, c in enumerate(sorted(ALL_COMBOS))],
        "boat_scenarios": [{"lane": 2, "factor_components": [{"log_factor": .1}]}],
        "head_probabilities": {"2": 1/6}}
    picks = choose(record, True)
    record["models"] = {"fusion": {"picks": picks, "selection_policy": POLICY},
                        "control_existing_10": {"picks": picks},
                        "control_hiyori_10": {"picks": picks}}
    record["digest"] = sha256(json.dumps(record, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode()).hexdigest()
    cp = {"key": key, "prediction_digest": record["digest"], "commit_sha": "fixed",
          "prediction_committed_at": date+"T10:01:00+09:00", "eligible_checkpoint": True}
    result = {"key": key, "status": "settled", "payouts": {picks[0]: 1000},
              "prediction_commit_sha": "fixed", "prediction_committed_at": cp["prediction_committed_at"],
              "observed_at": date+"T10:20:00+09:00"}
    ev = {"key": key, "prediction_digest": record["digest"],
          "models": {"fusion": {"stake_yen": 1000, "return_yen": 1000, "hit": True}}}
    for folder, obj in (("predictions", record), ("checkpoints", cp),
                        ("results", result), ("evaluations", ev)):
        path = root / folder / day / (key+".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj), encoding="utf-8")
    return key


class HoldoutTests(unittest.TestCase):
    def test_historical_data_never_becomes_holdout(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fixture(root, "20261014")
            r = evaluate(root, CANDIDATE, PLAN)
            self.assertEqual(r["status"], "WAITING_FOR_ELIGIBLE_FUTURE_DATA")
            self.assertEqual(r["periods"], {})

    def test_future_data_verified_and_scored(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fixture(root)
            r = evaluate(root, CANDIDATE, PLAN)
            self.assertEqual(r["status"], "PARTIAL_HOLDOUT")
            self.assertEqual(r["counts"]["evaluated"], 1)
            self.assertEqual(r["periods"]["total"]["no_alt_head_v1"]["roi_pct"], 100)
            self.assertFalse(r["automatic_promotion"])

    def test_missing_checkpoint_is_pending_not_loss(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); key = fixture(root)
            (root/"checkpoints/20261016"/(key+".json")).unlink()
            r = evaluate(root, CANDIDATE, PLAN)
            self.assertEqual(r["counts"]["missing_checkpoint"], 1)
            self.assertEqual(r["periods"], {})

    def test_tampered_future_record_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); key = fixture(root)
            p = root/"predictions/20261016"/(key+".json")
            record = json.loads(p.read_text()); record["trifecta"][0]["probability"] = .5
            p.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "tampered"):
                evaluate(root, CANDIDATE, PLAN)

    def test_plan_rejects_changed_rule_or_historical_window(self):
        plan = json.loads(PLAN.read_text())
        validate_plan(plan, CANDIDATE)
        for field, value in (("candidate_digest", "wrong"), ("selector_sha256", "wrong"),
                             ("start_day", "20261013"), ("automatic_promotion", True)):
            bad = copy.deepcopy(plan); bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_plan(bad, CANDIDATE)

    def test_missing_root_fails(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError, "Missing predictions"):
                evaluate(Path(d), CANDIDATE, PLAN)


if __name__ == "__main__":
    unittest.main()
