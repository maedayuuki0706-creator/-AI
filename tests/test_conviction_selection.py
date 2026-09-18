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

    def test_tamagawa_g1_allows_third_head_only_when_truly_tight(self):
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
        self.assertEqual(heads, {"1", "2", "3"})
        self.assertLessEqual(len(picks), 16)


    def test_third_head_is_not_added_when_gap_is_not_tight(self):
        analysis = {
            "trifecta": [
                row("1-4-2", .04), row("1-4-3", .035), row("2-4-1", .03),
                row("2-4-3", .028), row("3-4-1", .026), row("3-4-2", .024),
            ],
            "heads": {"1": .30, "2": .24, "3": .21, "4": .10, "5": .08, "6": .07},
        }
        heads = d._conviction_heads(analysis)
        self.assertEqual([x[0] for x in heads], ["1", "2"])


if __name__ == "__main__":
    unittest.main()
