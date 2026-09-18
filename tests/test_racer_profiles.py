import unittest

import racer_profile_learning as l
import racer_profiles as p


class RacerProfileTests(unittest.TestCase):
    def test_update_tracks_course_and_winning_method(self):
        state = {"racers": {}, "processed_races": []}
        result = {
            "day": "20260918",
            "jcd": "07",
            "method": "まくり差し",
            "finish": [
                {"racer_id": "4001", "name": "選手A", "lane": 4, "course": 4, "st": .11, "finish": 1, "status": "finished"},
                {"racer_id": "4002", "name": "選手B", "lane": 1, "course": 1, "st": .15, "finish": 2, "status": "finished"},
            ],
        }
        l.update_from_result(state, result)
        a = state["racers"]["4001"]
        self.assertEqual(a["courses"]["4"]["wins"], 1)
        self.assertEqual(a["venues"]["07"]["starts"], 1)
        self.assertEqual(a["win_methods"]["まくり差し"], 1)
        self.assertAlmostEqual(a["avg_st"], .11)

    def test_smoothed_course_rates_need_minimum_history(self):
        original = p.profile_for
        try:
            p.profile_for = lambda _: {
                "starts": 20,
                "avg_st": .14,
                "win_methods": {"差し": 3},
                "courses": {"2": {"starts": 2, "wins": 2, "top2": 2}},
                "venues": {"24": {"starts": 5}},
            }
            boat = {"racer_id": "4001", "lane": 2, "predicted_course": 2}
            p.apply_profile(boat, "24")
            self.assertNotIn("course_win_rate", boat)

            p.profile_for = lambda _: {
                "starts": 30,
                "avg_st": .14,
                "win_methods": {"差し": 4},
                "courses": {"2": {"starts": 10, "wins": 4, "top2": 6}},
                "venues": {"24": {"starts": 5}},
            }
            boat = {"racer_id": "4001", "lane": 2, "predicted_course": 2}
            p.apply_profile(boat, "24")
            self.assertIn("course_win_rate", boat)
            self.assertIn("course_top2_rate", boat)
            self.assertEqual(boat["racer_profile_course_samples"], 10)
        finally:
            p.profile_for = original


if __name__ == "__main__":
    unittest.main()
