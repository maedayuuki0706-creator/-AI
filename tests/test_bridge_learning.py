import unittest

import bridge_learning


class BridgeLearningVenuePatternTests(unittest.TestCase):
    def test_same_three_order_bias_prioritizes_order_swap(self):
        base = (1, 2, 3)
        order_swap = (1, 3, 2)
        third_swap = (1, 2, 4)
        neutral_order = bridge_learning._bridge_kind(order_swap, base, False)
        biased_order = bridge_learning._bridge_kind(order_swap, base, False, order_bias=0.4)
        third = bridge_learning._bridge_kind(third_swap, base, False)
        self.assertGreater(biased_order, neutral_order)
        self.assertGreater(biased_order, third)

    def test_third_bias_keeps_ordered_top2_priority(self):
        base = (1, 2, 3)
        order_swap = (1, 3, 2)
        third_swap = (1, 2, 4)
        biased_third = bridge_learning._bridge_kind(third_swap, base, False, third_bias=0.4)
        order = bridge_learning._bridge_kind(order_swap, base, False)
        self.assertGreater(biased_third, order)

    def test_bias_never_changes_unrelated_candidate(self):
        base = (1, 2, 3)
        unrelated = (4, 5, 6)
        score = bridge_learning._bridge_kind(
            unrelated, base, True, order_bias=0.6, third_bias=0.6
        )
        self.assertEqual(score, 0.0)


if __name__ == "__main__":
    unittest.main()
