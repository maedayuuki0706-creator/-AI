"""Offline tests for the independent Yuuki EV sheet synchronizer."""
import unittest
from research.yuuki_ev_sheet_sync import close_out, metrics, summary


def row():
    data = [""] * 24
    data[0] = "20261014"
    data[1] = "尼崎"
    data[3] = "A_現行PT2"
    data[5] = "1-4-3"
    data[10] = "0.76"
    data[12] = "100"
    data[15] = "未確定"
    data[19] = "20261014_13_07"
    data[22] = "締切前固定"
    return data


class EVSheetSyncTests(unittest.TestCase):
    def test_result_is_virtual_payout_not_odds(self):
        result = close_out(row(), {"status": "settled", "payouts": {"1-4-3": 2480}})
        self.assertEqual(result, ["○", 2480, "確定", 2380, 24.8, "1-4-3"])

    def test_missing_or_refund_is_excluded(self):
        self.assertIsNone(close_out(row(), {"status": "settled", "payouts": {}}))
        self.assertIsNone(close_out(row(), {"status": "settled", "payouts": {"1-4-3": 2480}, "refund_lanes": [2]}))

    def test_missed_ticket_is_true_zero(self):
        data = row()
        data[5] = "1-5-4"
        self.assertEqual(close_out(data, {"status": "settled", "payouts": {"1-4-3": 2480}}),
                         ["×", 0, "確定", -100.0, 0.0, "1-4-3"])

    def test_threshold_has_one_race_not_two(self):
        items = [
            {"cohort": "締切前固定", "model": "A_現行PT2", "key": "20261014_13_07", "day": "20261014",
             "venue": "尼崎", "ev": 1.5, "stake": 100, "payout": 0, "hit": False},
            {"cohort": "締切前固定", "model": "B_展開連動", "key": "20261014_13_07", "day": "20261014",
             "venue": "尼崎", "ev": 1.6, "stake": 100, "payout": 0, "hit": False},
        ]
        self.assertEqual(metrics(items)[:3], [1, 2, 0])
        records = summary(items)
        r = next(r for r in records if r[:4] == ["締切前固定", "全モデル", "総計", 1.4])
        self.assertEqual(r[4:7], [1, 2, 0])

    def test_no_double_count_on_repeated_summary(self):
        ticket = {"cohort": "締切前固定", "model": "A_現行PT2", "key": "20261014_13_07",
                  "day": "20261014", "venue": "尼崎", "ev": 1.4, "stake": 100,
                  "payout": 0, "hit": False}
        self.assertEqual(summary([ticket]), summary([ticket]))


if __name__ == "__main__":
    unittest.main()
