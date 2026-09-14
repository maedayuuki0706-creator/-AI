import unittest

import hit_alerts


class HitAlertTests(unittest.TestCase):
    def test_settle_3000_uses_recorded_units(self):
        row = {
            "stake_3000_units": {
                "1-2-3": 10,
                "1-3-2": 8,
                "2-1-3": 12,
            }
        }
        result = {"payouts": {"1-2-3": 520}, "refund_lanes": []}
        settled = hit_alerts._settle_3000(row, result)
        self.assertEqual(settled["stake"], 3000)
        self.assertEqual(settled["return"], 5200)
        self.assertEqual(settled["profit"], 2200)
        self.assertAlmostEqual(settled["roi"], 173.3333333333)

    def test_message_marks_longshot_and_section(self):
        row = {
            "venue": "若松",
            "rno": 2,
            "grade": "B",
            "selection_score": 81,
            "main": ["5-3-6"],
            "cover": ["5-6-3"],
            "outsiders": [],
            "stake_3000_units": {"5-3-6": 10, "5-6-3": 20},
        }
        result = {"payouts": {"5-3-6": 13790}, "refund_lanes": []}
        text = hit_alerts._message(row, "5-3-6", 13790, result)
        self.assertIn("万舟的中速報", text)
        self.assertIn("◎ 本線", text)
        self.assertIn("13,790円", text)
        self.assertIn("3,000円資金配分", text)


if __name__ == "__main__":
    unittest.main()
