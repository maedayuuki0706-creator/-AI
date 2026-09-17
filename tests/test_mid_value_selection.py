import unittest

import mid_value_selection
import opportunity_alerts


class MidValueSelectionTests(unittest.TestCase):
    def setUp(self):
        # Use a tiny stand-in module so installing the policy never mutates the
        # global opportunity_alerts module used by unrelated tests.
        class Stub:
            pass

        self.stub = Stub()
        self.stub._candidate_rows = opportunity_alerts._candidate_rows
        self.stub._is_selected_mid = opportunity_alerts._is_selected_mid
        self.stub._mid_value_selection_installed = False
        mid_value_selection.install(self.stub)

    def test_supported_6_to_12x_candidate_is_admitted(self):
        analysis = {
            "trifecta": [
                {"combination": "1-2-3", "odds": 8.0, "probability": 0.14, "expected_value": 1.12},
                {"combination": "1-3-2", "odds": 7.5, "probability": 0.04, "expected_value": 0.30},
                {"combination": "2-1-3", "odds": 18.0, "probability": 0.03, "expected_value": 0.54},
            ]
        }
        rows = self.stub._candidate_rows(analysis, "mid")
        combos = {row["combination"] for row in rows}
        self.assertIn("1-2-3", combos)
        self.assertNotIn("1-3-2", combos)
        self.assertIn("2-1-3", combos)

    def test_market_price_alone_never_creates_candidate(self):
        analysis = {
            "trifecta": [
                {"combination": "1-2-3", "odds": 10.0, "probability": 0.01, "expected_value": 0.10},
            ]
        }
        self.assertEqual(self.stub._candidate_rows(analysis, "mid"), [])

    def test_longshot_candidate_rules_are_untouched(self):
        analysis = {
            "trifecta": [
                {"combination": "4-1-6", "odds": 75.0, "probability": 0.004, "expected_value": 0.30},
                {"combination": "1-2-3", "odds": 8.0, "probability": 0.20, "expected_value": 1.60},
            ]
        }
        rows = self.stub._candidate_rows(analysis, "long")
        self.assertEqual([row["combination"] for row in rows], ["4-1-6"])

    def test_looser_selected_route_requires_stronger_value_support(self):
        payload = {
            "score": 70,
            "composite_odds": 3.2,
            "picks": [
                {"combination": "1-2-3", "odds": 9.0, "probability": 0.07, "expected_value": 1.20},
                {"combination": "1-3-2", "odds": 14.0, "probability": 0.04, "expected_value": 1.22},
            ],
        }
        self.assertTrue(self.stub._is_selected_mid(payload))

        weak = dict(payload)
        weak["picks"] = [dict(payload["picks"][0], expected_value=1.08), dict(payload["picks"][1], expected_value=1.10)]
        self.assertFalse(self.stub._is_selected_mid(weak))

        low_score = dict(payload, score=67)
        self.assertFalse(self.stub._is_selected_mid(low_score))


if __name__ == "__main__":
    unittest.main()
