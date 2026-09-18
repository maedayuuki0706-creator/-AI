import unittest

import detailed_discord_notify as d


def row(combo, p):
    return {"combination": combo, "probability": p, "expected_value": 1.0, "odds": 20.0}


class ConvictionSelectionTests(unittest.TestCase):
    def test_uses_at_most_two_heads_and_extends_main_prefix(self):
        rows = [
            row("1-2-3", .040), row("1-2-4", .036), row("1-2-5", .032), row("1-2-6", .028),
            row("2-1-3", .030), row("2-1-4", .028), row("2-1-5", .026), row("2-1-6", .024),
            row("4-1-2", .023), row("3-1-2", .022),
            row("1-3-2", .021), row("2-3-1", .020),
        ]
        analysis = {
            "trifecta": rows,
            "heads": {"1": .30, "2": .24, "3": .17, "4": .16, "5": .08, "6": .05},
        }
        picks = d._conviction_picks(analysis, 10)
        heads = {x["combination"].split("-")[0] for x in picks}
        self.assertEqual(heads, {"1", "2"})
        self.assertEqual(
            [x["combination"] for x in picks[:3]],
            ["1-2-3", "1-2-4", "1-2-5"],
        )
        self.assertIn("1-2-6", [x["combination"] for x in picks])
        self.assertIn("2-1-3", [x["combination"] for x in picks])

    def test_clear_primary_drops_weak_second_head(self):
        rows = [
            row("1-2-3", .050), row("1-2-4", .045), row("1-2-5", .040), row("1-2-6", .035),
            row("1-3-2", .030), row("1-3-4", .028), row("1-4-2", .026), row("1-4-3", .024),
            row("2-1-3", .022), row("3-1-2", .020),
        ]
        analysis = {
            "trifecta": rows,
            "heads": {"1": .42, "2": .18, "3": .14, "4": .11, "5": .08, "6": .07},
        }
        picks = d._conviction_picks(analysis, 8)
        self.assertEqual(
            {x["combination"].split("-")[0] for x in picks},
            {"1"},
        )

    def test_tamagawa_g1_still_never_adds_third_head(self):
        rows = []
        for head, base in (("1", .035), ("2", .033), ("3", .031)):
            for second in ("1", "2", "3", "4", "5", "6"):
                if second == head:
                    continue
                for third in ("1", "2", "3", "4", "5", "6"):
                    if third in {head, second}:
                        continue
                    rows.append(row(f"{head}-{second}-{third}", base))
        analysis = {
            "trifecta": rows,
            "heads": {"1": .22, "2": .20, "3": .19, "4": .14, "5": .13, "6": .12},
            "balanced_head_mode": True,
        }
        picks = d._conviction_picks(analysis, 14)
        heads = {x["combination"].split("-")[0] for x in picks}
        self.assertLessEqual(len(heads), 2)
        self.assertEqual(heads, {"1", "2"})


if __name__ == "__main__":
    unittest.main()
