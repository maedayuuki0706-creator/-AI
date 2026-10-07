import unittest

import pt2_strategy_cards as cards


class PT2StrategyCardTests(unittest.TestCase):
    def analysis(self):
        return {
            "trifecta": [
                {"combination": "1-2-3", "probability": 0.20, "odds": 4.0, "expected_value": 0.80},
                {"combination": "1-3-2", "probability": 0.15, "odds": 7.0, "expected_value": 1.05},
                {"combination": "2-1-3", "probability": 0.08, "odds": 18.0, "expected_value": 1.44},
                {"combination": "3-1-2", "probability": 0.04, "odds": 70.0, "expected_value": 2.80},
                {"combination": "5-1-2", "probability": 0.016, "odds": 110.0, "expected_value": 1.76},
                {"combination": "2-4-1", "probability": 0.0045, "odds": 390.0, "expected_value": 1.755},
                {"combination": "4-6-1", "probability": 0.0026, "odds": 330.0, "expected_value": 0.858},
                {"combination": "6-4-3", "probability": 0.0020, "odds": 180.0, "expected_value": 0.36},
                {"combination": "1-4-2", "probability": 0.10, "odds": 8.0, "expected_value": 0.80},
            ]
        }

    def balanced(self):
        return {
            "selection_policy": "current-pt2",
            "picks": ["1-2-3", "1-3-2", "2-1-3"],
            "main_picks": ["1-2-3", "1-3-2"],
        }

    def test_builds_four_distinct_strategy_cards(self):
        result = cards.build_strategy_cards(self.analysis(), self.balanced())
        self.assertEqual(result["version"], cards.STRATEGY_VERSION)
        self.assertEqual(set(result["cards"]), {"balanced", "probability", "value", "longshot"})
        self.assertEqual(result["cards"]["balanced"]["picks"], self.balanced()["picks"])

    def test_value_card_keeps_high_ev_market_mispricing(self):
        result = cards.build_strategy_cards(self.analysis(), self.balanced())
        picks = result["cards"]["value"]["picks"]
        self.assertIn("5-1-2", picks)
        self.assertIn("2-4-1", picks)

    def test_longshot_card_requires_price_probability_and_ev(self):
        result = cards.build_strategy_cards(self.analysis(), self.balanced())
        picks = result["cards"]["longshot"]["picks"]
        self.assertIn("5-1-2", picks)
        self.assertIn("2-4-1", picks)
        self.assertIn("4-6-1", picks)
        self.assertNotIn("6-4-3", picks)


if __name__ == "__main__":
    unittest.main()
