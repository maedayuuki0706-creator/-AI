"""Strict no-delivery scenario audit tests using synthetic, non-real data."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from yuuki_v3_shadow_audit import analyze_race, audit


def fixture():
    pred = {
        "key": "20261013_00_01", "venue": "SYNTHETIC", "digest": "frozen-digest",
        "created_at": "2026-10-13T10:00:00+09:00",
        "deadline_at": "2026-10-13T10:15:00+09:00",
        "mode": "prospective_shadow", "research_only": True,
        "head_probabilities": {"1": .4, "2": .3, "3": .12, "4": .08, "5": .06, "6": .04},
        "boat_scenarios": [
            {"lane": lane, "anticipated_methods": ["差し"] if lane == 2 else ["逃げ"]}
            for lane in range(1, 7)
        ],
        "models": {
            "fusion": {"picks": ["1-2-3", "2-1-4"]},
            "control_existing_10": {"picks": ["2-1-3", "1-2-3"]},
            "control_hiyori_10": {"picks": ["1-2-3"]},
            "control_sheet_db_10": {"picks": ["2-1-3"]},
            "control_knowledge_v2_10": {"picks": ["1-2-3"]},
        }
    }
    ver = {"key": pred["key"], "prediction_digest": pred["digest"], "evaluation": {
        "key": pred["key"], "prediction_digest": pred["digest"],
        "prediction_committed_at": "2026-10-13T10:02:00+09:00",
        "official_result": {"status": "settled", "refund_lanes": [],
                            "payouts": {"2-1-3": 2180},
                            "race_details": {"method": "差し"}},
        "scenario_review": {"boats": [
            {"lane": 2, "condition_checks": [{"observed": True}]}
        ]}
    }}
    return pred, ver


class ScenarioAuditTests(unittest.TestCase):
    def test_wrong_top_head_not_treated_as_tail_failure(self):
        p, v = fixture()
        row, reason = analyze_race(p, v)
        self.assertIsNone(reason)
        self.assertEqual(row["ticket_failure"], "head_covered_tail_missing")
        self.assertFalse(row["model_top_head_correct"])
        self.assertEqual(row["cards"]["fusion"]["return"], 0)
        self.assertEqual(row["cards"]["control_existing_10"]["return"], 2180)
        self.assertTrue(row["winning_method_compatible"])

    def test_exact_hit(self):
        p, v = fixture()
        p["models"]["fusion"]["picks"].append("2-1-3")
        row, reason = analyze_race(p, v)
        self.assertEqual(row["ticket_failure"], "hit")
        self.assertIsNone(reason)

    def test_head_not_in_ticket(self):
        p, v = fixture()
        p["models"]["fusion"]["picks"] = ["1-2-3"]
        row, _ = analyze_race(p, v)
        self.assertEqual(row["ticket_failure"], "winning_head_not_in_picks")

    def test_reject_late_prediction(self):
        p, v = fixture()
        v["evaluation"]["prediction_committed_at"] = "2026-10-13T10:16:00+09:00"
        self.assertEqual(analyze_race(p, v)[1], "unproven_predeadline")

    def test_reject_wrong_digest(self):
        p, v = fixture()
        v["prediction_digest"] = "other"
        self.assertEqual(analyze_race(p, v)[1], "digest_mismatch")

    def test_reject_refunds(self):
        p, v = fixture()
        v["evaluation"]["official_result"]["refund_lanes"] = [2]
        self.assertEqual(analyze_race(p, v)[1], "unsettled_abnormal_refund")

    def test_do_not_accept_incomplete_six_boat_evidence(self):
        p, v = fixture()
        p["boat_scenarios"].pop()
        self.assertEqual(analyze_race(p, v)[1], "invalid_scenarios")

    def test_offline_audit_reads_only_qualified_records(self):
        p, v = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            pred = base / "predictions" / "20261013"
            verify = base / "official_verifications" / "20261013"
            pred.mkdir(parents=True)
            verify.mkdir(parents=True)
            (pred / "20261013_00_01.json").write_text(json.dumps(p))
            (verify / "20261013_00_01.json").write_text(json.dumps(v))
            report = audit(base, ["20261013"])
            self.assertEqual(report["verified_races"], 1)
            self.assertEqual(report["cards"]["fusion"]["stake_yen"], 200)
            self.assertEqual(report["cards"]["control_existing_10"]["returned_yen"], 2180)
            self.assertEqual(report["failure_types"]["head_covered_tail_missing"], 1)


if __name__ == "__main__":
    unittest.main()
