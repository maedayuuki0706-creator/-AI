import unittest

import prototype_scoreboard as board


class PrototypeScoreboardTests(unittest.TestCase):
    def test_hit_and_flat_stake_return(self):
        model = {
            "picks": ["1-2-3", "1-3-2"],
            "main_picks": ["1-2-3"],
            "cover_picks": ["1-3-2"],
        }
        result = {
            "status": "settled",
            "payouts": {"1-2-3": 2500},
            "refund_lanes": [],
        }
        scored = board.score_model(model, result)
        self.assertTrue(scored["hit"])
        self.assertTrue(scored["main_hit"])
        self.assertFalse(scored["cover_hit"])
        self.assertEqual(scored["stake_yen"], 200)
        self.assertEqual(scored["return_yen"], 2500)
        self.assertEqual(scored["profit_yen"], 2300)
        self.assertAlmostEqual(scored["roi"], 1250.0)

    def test_refund_is_returned_and_not_a_hit(self):
        model = {
            "picks": ["1-2-3", "1-4-3"],
            "main_picks": ["1-2-3"],
            "cover_picks": ["1-4-3"],
        }
        result = {
            "status": "settled",
            "payouts": {"4-1-3": 1800},
            "refund_lanes": [2],
        }
        scored = board.score_model(model, result)
        self.assertFalse(scored["hit"])
        self.assertEqual(scored["stake_yen"], 200)
        self.assertEqual(scored["refund_yen"], 100)
        self.assertEqual(scored["return_yen"], 100)
        self.assertAlmostEqual(scored["roi"], 50.0)

    def test_aggregate_uses_judged_for_hit_rate_and_resolved_for_roi(self):
        rows = [
            {
                "eligible": True, "hit": True, "stake_yen": 1000, "return_yen": 2200,
                "manshu": False, "torigami": False, "main_hit": True, "cover_hit": False,
            },
            {
                "eligible": False, "hit": False, "stake_yen": 1000, "return_yen": 1000,
                "manshu": False, "torigami": False, "main_hit": False, "cover_hit": False,
            },
        ]
        stats = board.aggregate(rows)
        self.assertEqual(stats["resolved"], 2)
        self.assertEqual(stats["judged"], 1)
        self.assertEqual(stats["hits"], 1)
        self.assertAlmostEqual(stats["hit_rate"], 100.0)
        self.assertEqual(stats["stake_yen"], 2000)
        self.assertEqual(stats["return_yen"], 3200)
        self.assertAlmostEqual(stats["roi"], 160.0)


if __name__ == "__main__":
    unittest.main()
