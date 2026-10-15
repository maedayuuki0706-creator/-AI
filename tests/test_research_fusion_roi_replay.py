import tempfile
import copy
import hashlib
import json
import unittest
from pathlib import Path

from research_fusion_roi_replay import ALL_COMBOS, aggregate, score, ticket_sets, verify


class ReplayTests(unittest.TestCase):
    def test_rejects_tampering_and_post_deadline_checkpoint(self):
        key = "20261014_04_01"
        record = {"key": key, "mode": "prospective_shadow", "research_only": True,
                  "created_at": "2026-10-14T10:00:00+09:00",
                  "deadline_at": "2026-10-14T10:10:00+09:00",
                  "trifecta": [{"combination": c, "expected_value": 1.1}
                               for c in sorted(ALL_COMBOS)],
                  "models": {name: {"picks": ["1-2-3"]} for name in
                             ("fusion", "control_existing_10", "control_hiyori_10")}}
        record["digest"] = hashlib.sha256(json.dumps(record, ensure_ascii=False,
            sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        checkpoint = {"key": key, "prediction_digest": record["digest"],
                      "eligible_checkpoint": True, "commit_sha": "frozen",
                      "prediction_committed_at": "2026-10-14T10:01:00+09:00"}
        result = {"key": key, "prediction_commit_sha": "frozen",
                  "prediction_committed_at": checkpoint["prediction_committed_at"],
                  "observed_at": "2026-10-14T10:20:00+09:00", "status": "settled",
                  "payouts": {"1-2-3": 1000}}
        evaluation = {"key": key, "prediction_digest": record["digest"]}
        verify(key, record, checkpoint, result, evaluation)
        bad = copy.deepcopy(record)
        bad["research_only"] = False
        with self.assertRaises(ValueError):
            verify(key, bad, checkpoint, result, evaluation)
        bad_checkpoint = dict(checkpoint, prediction_committed_at=record["deadline_at"])
        with self.assertRaisesRegex(ValueError, "before deadline"):
            verify(key, record, bad_checkpoint, result, evaluation)

    def test_missing_input_fails_instead_of_reporting_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Missing predictions"):
                aggregate(Path(directory))

    def test_refund_is_not_a_hit_and_reduces_at_risk_stake(self):
        row = score(["1-2-3", "4-5-6"], {
            "status": "settled", "refund_lanes": [1], "payouts": {"4-5-6": 500}})
        self.assertEqual((row["stake"], row["returned"], row["refund"]), (200, 600, 100))
        self.assertTrue(row["hit"])
        refunded = score(["1-2-3"], {
            "status": "settled", "refund_lanes": [1], "payouts": {"4-5-6": 500}})
        self.assertFalse(refunded["hit"])
        self.assertFalse(refunded["active"])

    def test_void_returns_all_stakes(self):
        row = score(["1-2-3", "4-5-6"], {"status": "void"})
        self.assertEqual(row["returned"], row["stake"])
        self.assertFalse(row["hit"])
        self.assertFalse(row["active"])

    def test_torigami_and_manshu(self):
        self.assertTrue(score(["1-2-3", "4-5-6"], {
            "status": "settled", "payouts": {"1-2-3": 150}})["torigami"])
        self.assertTrue(score(["1-2-3"], {
            "status": "settled", "payouts": {"1-2-3": 10000}})["manshu"])

    def test_selection_uses_frozen_ev_and_keeps_order(self):
        picks = ["1-2-3", "1-2-4", "1-2-5", "1-2-6", "1-3-2",
                 "1-3-4", "1-3-5", "1-3-6", "1-4-2", "1-4-3"]
        record = {"models": {"fusion": {"picks": picks, "main_picks": picks[:6]},
                   "control_existing_10": {"picks": picks},
                   "control_hiyori_10": {"picks": picks}},
                  "trifecta": [{"combination": p, "expected_value": ev}
                               for p, ev in zip(picks, [None, .9, 1, 1.2, 1.3, 1.4, .5, .6, .7, .8])]}
        variants = ticket_sets(record)
        self.assertEqual(variants["fusion_ev100"], picks[2:6])
        self.assertEqual(variants["fusion_ev120"], picks[3:6])
        self.assertEqual(variants["skip_weak_ev"], [])


if __name__ == "__main__":
    unittest.main()
