import unittest

import stake_tracking as st


class StakeTrackingTests(unittest.TestCase):
    def test_complete_odds_use_exact_3000_yen(self):
        picks = ["1-2-3", "1-3-2", "2-1-3", "3-1-2"]
        odds = {"1-2-3": 6.0, "1-3-2": 12.0, "2-1-3": 30.0, "3-1-2": 60.0}
        units, mode, minimum = st.allocate_3000(picks, odds)
        self.assertEqual(sum(units.values()), 30)
        self.assertTrue(all(units[p] >= 1 for p in picks))
        self.assertEqual(mode, "send_time_odds_dutch")
        self.assertIsInstance(minimum, int)
        self.assertGreater(units["1-2-3"], units["3-1-2"])

    def test_missing_odds_are_not_invented(self):
        picks = ["1-2-3", "1-3-2", "2-1-3"]
        odds = {"1-2-3": 8.0, "1-3-2": 15.0}
        units, mode, minimum = st.allocate_3000(picks, odds)
        self.assertEqual(sum(units.values()), 30)
        self.assertTrue(all(units[p] >= 1 for p in picks))
        self.assertEqual(mode, "equal_fallback_missing_send_odds")
        self.assertIsNone(minimum)

    def test_too_many_picks_rejected(self):
        picks = [f"x{i}" for i in range(31)]
        with self.assertRaises(ValueError):
            st.allocate_3000(picks, {})


if __name__ == "__main__":
    unittest.main()
