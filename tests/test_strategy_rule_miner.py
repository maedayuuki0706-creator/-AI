import unittest
import strategy_rule_miner as s


class StrategyRuleMinerTests(unittest.TestCase):
    def _row(self, day, roi_hit=True, venue="A", grade="B"):
        return {
            "day": day,
            "key": "01:1",
            "hit": bool(roi_hit),
            "stake": 1000,
            "return": 1300 if roi_hit else 0,
            "profit": 300 if roi_hit else -1000,
            "features": {
                "venue": venue, "grade": grade, "event": "normal",
                "score": "75-84", "points": "11-12",
                "head_top": "35-44%", "head_gap": "10-19pt",
                "wind": "0-1m", "wave": "0-2cm", "selected": "yes",
            },
        }

    def test_tactical_features_detect_outer_attack(self):
        pred = {
            "preview": {
                "boats": {
                    "1": {"exhibition_flying": True},
                    "2": {"exhibition_st": 0.07},
                    "3": {"exhibition_st": 0.25},
                    "4": {"exhibition_st": 0.03},
                    "5": {"exhibition_st": 0.07},
                    "6": {"exhibition_st": 0.17},
                }
            }
        }
        out = s._tactical_features(pred)
        self.assertEqual(out["attack_lane"], "4")
        self.assertEqual(out["slit_shape"], "strong_outer_attack_4")
        self.assertEqual(out["attack_gap"], "15pt+")
        self.assertEqual(out["outer_fast"], "yes")
        self.assertEqual(out["lane1_flying"], "yes")

    def test_tactical_features_unknown_without_exhibition(self):
        out = s._tactical_features({})
        self.assertEqual(out["slit_shape"], "unknown")
        self.assertEqual(out["attack_lane"], "unknown")
        self.assertEqual(out["outer_fast"], "unknown")

    def test_one_day_never_promotes(self):
        rows = [self._row("20260901", True) for _ in range(100)]
        result = s.mine(rows)
        self.assertEqual(result["validated_positive_rules"], [])

    def test_summary_uses_real_stake_and_return(self):
        rows = [self._row("20260901", True), self._row("20260902", False)]
        out = s.summary(rows)
        self.assertEqual(out["samples"], 2)
        self.assertEqual(out["stake_yen"], 2000)
        self.assertEqual(out["return_yen"], 1300)
        self.assertEqual(out["profit_yen"], -700)


if __name__ == "__main__":
    unittest.main()
