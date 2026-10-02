import unittest

import x_featured_selector as featured


class FeaturedXSelectorTests(unittest.TestCase):
    def model(self, *, grade="A", heads=None, main=None, rows=None):
        return {
            "name": "m",
            "grade": grade,
            "heads": heads or {"1": 0.46, "4": 0.18, "2": 0.10, "3": 0.10, "5": 0.08, "6": 0.08},
            "main": main or ["4-1-3", "4-3-1"],
            "tri": rows or {
                "4-1-3": {"odds": 74.2, "ev": 2.22, "prob": 0.030},
                "4-3-1": {"odds": 128.2, "ev": 1.91, "prob": 0.015},
            },
            "race_shape": {"attack_pressure": 41.3},
            "market_structure": {},
        }

    def test_confidence_route_finds_non_one_value_main(self):
        race = {"models": [self.model()]}
        pick = featured._confidence_candidate(race)
        self.assertIsNotNone(pick)
        self.assertEqual(pick["source"], "配当期待本線")
        self.assertIn("4-1-3", pick["picks"])
        self.assertTrue(all(not combo.startswith("1-") for combo in pick["picks"]))

    def test_overlap_route_prefers_shared_non_one_combo(self):
        m1 = self.model(
            grade="B",
            heads={"1": 0.20, "5": 0.29, "4": 0.24, "2": 0.10, "3": 0.09, "6": 0.08},
            main=["5-2-4", "5-4-1"],
            rows={
                "5-2-4": {"odds": 88.6, "ev": 1.84, "prob": 0.021},
                "5-4-1": {"odds": 81.0, "ev": 2.08, "prob": 0.026},
            },
        )
        m2 = dict(m1)
        m2 = {**m2, "name": "m2"}
        race = {"models": [m1, m2]}
        pick = featured._overlap_candidate(race)
        self.assertIsNotNone(pick)
        self.assertEqual(pick["source"], "AI重なり本線")
        self.assertIn("5-2-4", pick["picks"])

    def test_dominant_one_head_is_not_featured(self):
        m = self.model(
            grade="A",
            heads={"1": 0.72, "2": 0.07, "3": 0.06, "4": 0.06, "5": 0.05, "6": 0.04},
        )
        self.assertIsNone(featured._confidence_candidate({"models": [m]}))

    def test_ticket_plan_is_10_plus_8_and_keeps_every_one_percent_alt_head(self):
        rows = {}
        for first in range(1, 7):
            for second in range(1, 7):
                if second == first:
                    continue
                for third in range(1, 7):
                    if third in {first, second}:
                        continue
                    combo = f"{first}-{second}-{third}"
                    rows[combo] = {
                        "odds": 12.0 + first * 7 + second + third,
                        "ev": 0.9 + first * 0.08,
                        "prob": 0.04 - first * 0.003 - second * 0.0002 - third * 0.0001,
                    }
        model = self.model(
            heads={"1": 0.62, "2": 0.16, "3": 0.09, "4": 0.06, "5": 0.04, "6": 0.03},
            main=[
                "1-2-3", "1-2-4", "1-3-2", "1-3-4", "1-4-2",
                "2-1-3", "2-3-1", "3-1-2", "4-1-2", "5-1-2",
            ],
            rows=rows,
        )
        plan = featured._ticket_plan({"models": [model]})
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan["main"]), 10)
        self.assertEqual(len(plan["cover"]), 8)
        self.assertEqual(set(plan["eligible_alt_heads"]), set("23456"))
        cover_heads = {combo.split("-")[0] for combo in plan["cover"]}
        self.assertTrue(set("23456").issubset(cover_heads))
        self.assertTrue(all(not combo.startswith("1-") for combo in plan["cover"]))


if __name__ == "__main__":
    unittest.main()
