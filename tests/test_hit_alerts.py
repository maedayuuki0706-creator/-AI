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

    def test_mid_odds_message_is_labeled(self):
        row = {
            "stream": "mid_odds",
            "venue": "鳴門",
            "rno": 7,
            "score": 78,
            "confidence": "A",
            "point_count": 12,
            "picks": [
                {"combination": "5-1-3", "odds": 24.5},
            ],
        }
        text = hit_alerts._opportunity_message(row, "5-1-3", 2450)
        self.assertIn("中穴AI 的中速報", text)
        self.assertIn("期待度 **78/100**", text)
        self.assertIn("予想時オッズ：**24.5倍**", text)
        self.assertIn("買い目：**12点**", text)

    def test_longshot_message_marks_man_shu(self):
        row = {
            "stream": "longshot",
            "venue": "唐津",
            "rno": 7,
            "score": 71,
            "confidence": "B",
            "point_count": 10,
            "picks": [
                {"combination": "5-3-2", "odds": 95.6},
            ],
        }
        text = hit_alerts._opportunity_message(row, "5-3-2", 12560)
        self.assertIn("穴AI 万舟的中速報", text)
        self.assertIn("12,560円", text)

    def test_stream_keys_do_not_collide(self):
        row = {"day": "20260916", "jcd": "23", "rno": 7}
        self.assertEqual(hit_alerts._stream_key(row, "normal"), "20260916:23:7")
        self.assertEqual(hit_alerts._stream_key(row, "mid_odds"), "mid_odds:20260916:23:7")
        self.assertEqual(hit_alerts._stream_key(row, "longshot"), "longshot:20260916:23:7")


if __name__ == "__main__":
    unittest.main()
