import unittest

import pt2_auto_learning as learner


class PT2AutoLearningTests(unittest.TestCase):
    def settled(self, combo="1-2-3", payout=1200):
        return {"status": "settled", "payouts": {combo: payout}}

    def record(self):
        model = {
            "model_version": learner.MODEL_VERSION,
            "picks": ["1-3-2", "1-2-3"],
            "database": {
                "snapshot_at": "2026-10-07T13:02:56.865+09:00",
                "player_matches": 6,
                "motor_matches": 6,
                "probability_audit": {
                    "base_probability": {
                        "1-2-3": 0.04,
                        "1-3-2": 0.03,
                    }
                },
            },
            "trifecta": [
                {"combination": "1-2-3", "probability": 0.06},
                {"combination": "1-3-2", "probability": 0.02},
            ],
            "learning_audit": {
                "added_by_db": ["1-2-3"],
                "removed_by_db": [],
                "retained_after_db": ["1-3-2"],
                "lane_factors": {
                    "1": {"signals": ["course=60.0/55.0", "motor_grade=0.860"]},
                    "2": {"signals": ["method=1.030"]},
                    "3": {"signals": ["tuning=3.50"]},
                },
            },
        }
        return {
            "key": "20261007_08_07",
            "day": "20261007",
            "venue": "常滑",
            "jcd": "08",
            "rno": 7,
            "created_at": "2026-10-07T13:06:30+09:00",
            "models": {"prototype2": model},
        }

    def test_evaluate_prediction_tracks_db_help(self):
        row = learner.evaluate_prediction(self.record(), self.settled())
        self.assertIsNotNone(row)
        self.assertTrue(row["winner_probability_improved"])
        self.assertTrue(row["winner_added_by_db"])
        self.assertTrue(row["winner_in_final_picks"])
        self.assertTrue(row["hit"])
        self.assertAlmostEqual(row["winner_delta_pp"], 2.0)
        self.assertGreater(row["logloss_improvement"], 0)
        families = {item["family"] for item in row["signal_occurrences"]}
        self.assertIn("course", families)
        self.assertIn("method", families)
        self.assertIn("tuning", families)
        self.assertIn("motor_grade", families)

    def test_state_stays_collecting_before_sample_gate(self):
        row = learner.evaluate_prediction(self.record(), self.settled())
        state = learner.build_state([row])
        rec = learner.build_recommendation(state)
        self.assertEqual(state["samples"], 1)
        self.assertEqual(rec["phase"], "collecting")
        self.assertEqual(rec["action"], "keep_live_weights")
        self.assertFalse(rec["automatic_live_promotion"])

    def test_signal_candidate_requires_minimum_samples(self):
        row = learner.evaluate_prediction(self.record(), self.settled())
        state = learner.build_state([row for _ in range(learner.MIN_SIGNAL_SAMPLES)])
        rec = learner.build_recommendation(state)
        self.assertNotEqual(
            rec["signal_candidates"]["course"]["status"],
            "collecting",
        )


if __name__ == "__main__":
    unittest.main()
