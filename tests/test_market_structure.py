import unittest
from itertools import permutations

import mid_value_selection
import opportunity_alerts
from market_structure import analyze_market_structure


COMBOS = ["-".join(map(str, p)) for p in permutations(range(1, 7), 3)]


def odds_with_top(top_rows, default=500.0):
    odds = {combo: float(default) for combo in COMBOS}
    for combo, value in top_rows:
        odds[combo] = float(value)
    return odds


def model_rows(head_shares):
    rows = []
    for head in range(1, 7):
        combos = [combo for combo in COMBOS if combo.startswith(f"{head}-")]
        share = float(head_shares.get(head, 0.0))
        for combo in combos:
            rows.append({"combination": combo, "probability": share / len(combos)})
    return rows


class MarketStructureTests(unittest.TestCase):
    def test_sparse_odds_are_not_used_as_a_signal(self):
        result = analyze_market_structure({"1-2-3": 8.0}, [])
        self.assertFalse(result["available"])
        self.assertEqual(result["actionability"], "insufficient_odds")

    def test_flat_same_head_market_is_himo_split(self):
        top = [
            ("1-2-3", 10), ("1-2-4", 10.5), ("1-3-2", 11), ("1-3-4", 11.5),
            ("1-4-2", 12), ("1-4-3", 12.5), ("1-5-2", 13), ("1-5-3", 13.5),
            ("1-6-2", 14), ("1-6-3", 14.5),
        ]
        result = analyze_market_structure(odds_with_top(top), model_rows({1: .55, 2: .09, 3: .09, 4: .09, 5: .09, 6: .09}))
        self.assertTrue(result["available"])
        self.assertEqual(result["market_type"], "ヒモ割れ型")
        self.assertEqual(result["top10_unique_heads"], 1)

    def test_price_gap_same_head_market_is_concentrated(self):
        top = [
            ("1-2-3", 3), ("1-2-4", 4), ("1-3-2", 5), ("1-3-4", 6),
            ("1-4-2", 7), ("1-4-3", 8), ("1-5-2", 9), ("1-5-3", 10),
            ("1-6-2", 11), ("1-6-3", 12),
        ]
        result = analyze_market_structure(odds_with_top(top, default=1000), model_rows({1: .70, 2: .06, 3: .06, 4: .06, 5: .06, 6: .06}))
        self.assertEqual(result["market_type"], "集中型")
        self.assertGreater(result["market_top_head_share"], .68)

    def test_split_market_plus_clear_model_creates_actionable_disagreement(self):
        top = [
            ("1-2-3", 11), ("2-1-3", 11.2), ("3-1-2", 11.4), ("4-1-2", 11.6),
            ("1-3-4", 12), ("2-3-4", 12.2), ("3-2-4", 12.4), ("4-2-3", 12.6),
            ("1-4-5", 13), ("4-3-5", 13.2),
        ]
        rows = model_rows({1: .10, 2: .10, 3: .10, 4: .55, 5: .08, 6: .07})
        result = analyze_market_structure(odds_with_top(top), rows)
        self.assertIn(result["market_type"], {"頭割れ型", "完全混戦型", "中間型"})
        self.assertGreaterEqual(result["split_index"], 55)
        self.assertEqual(result["model_top_head"], 4)
        self.assertGreater(result["model_market_head_edge_pp"], 4)
        self.assertEqual(result["actionability"], "market_split_model_clear")

    def test_market_edge_only_reranks_existing_mid_candidates(self):
        class Stub:
            pass

        stub = Stub()
        stub._candidate_rows = opportunity_alerts._candidate_rows
        stub._is_selected_mid = opportunity_alerts._is_selected_mid
        stub._mid_value_selection_installed = False
        mid_value_selection.install(stub)

        analysis = {
            "trifecta": [
                {"combination": "4-1-2", "odds": 20.0, "probability": .03, "expected_value": .60},
                {"combination": "1-4-2", "odds": 20.0, "probability": .03, "expected_value": .60},
                {"combination": "6-1-2", "odds": 5.0, "probability": .001, "expected_value": .005},
            ],
            "market_structure": {
                "actionability": "market_split_model_clear",
                "head_edge_pp": {"4": 18.0, "1": -2.0},
            },
        }
        rows = stub._candidate_rows(analysis, "mid")
        self.assertEqual([row["combination"] for row in rows[:2]], ["4-1-2", "1-4-2"])
        self.assertIn("_market_edge_boost", rows[0])
        self.assertNotIn("6-1-2", {row["combination"] for row in rows})


if __name__ == "__main__":
    unittest.main()
