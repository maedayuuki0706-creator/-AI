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
