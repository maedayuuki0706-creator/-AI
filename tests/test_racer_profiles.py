import unittest

import racer_profile_learning as l
import racer_profiles as p


class RacerProfileTests(unittest.TestCase):
    def test_update_tracks_course_venue_year_and_winning_method(self):
        state = {
            "racers": {},
            "processed_races": [],
            "weight_anchor_day": "20260918",
        }
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
        self.assertEqual(a["years"]["2026"]["starts"], 1)
        self.assertEqual(a["win_methods"]["まくり差し"], 1)
        self.assertEqual(a["course_win_methods"]["4"]["まくり差し"], 1)
        self.assertAlmostEqual(a["avg_st"], .11)
        self.assertAlmostEqual(a["courses"]["4"]["weighted_starts"], 1.0)

    def test_old_history_is_retained_but_recency_weighted(self):
        state = {
            "racers": {},
            "processed_races": [],
            "weight_anchor_day": "20260918",
        }
        result = {
            "day": "20230918",
            "jcd": "24",
            "method": "差し",
            "finish": [
                {"racer_id": "4001", "name": "選手A", "lane": 2, "course": 2, "st": .14, "finish": 1, "status": "finished"},
            ],
        }
        l.update_from_result(state, result)
        a = state["racers"]["4001"]
        self.assertEqual(a["courses"]["2"]["starts"], 1)
        self.assertLess(a["courses"]["2"]["weighted_starts"], 1.0)
        self.assertEqual(a["years"]["2023"]["starts"], 1)

    def test_smoothed_course_rates_need_minimum_history(self):
        original = p.profile_for
        try:
            p.profile_for = lambda _: {
                "starts": 20,
                "avg_st": .14,
                "win_methods": {"差し": 3},
                "course_win_methods": {"2": {"差し": 3}},
                "courses": {"2": {"starts": 2, "wins": 2, "top2": 2}},
                "venues": {"24": {"starts": 5}},
                "years": {},
            }
            boat = {"racer_id": "4001", "lane": 2, "predicted_course": 2}
            p.apply_profile(boat, "24")
            self.assertNotIn("course_win_rate", boat)

            p.profile_for = lambda _: {
                "starts": 30,
                "avg_st": .14,
                "win_methods": {"差し": 4},
                "course_win_methods": {"2": {"差し": 4}},
                "courses": {
                    "2": {
                        "starts": 10, "wins": 4, "top2": 6,
                        "weighted_starts": 8.0, "weighted_wins": 3.0, "weighted_top2": 5.0,
                    }
                },
                "venues": {"24": {"starts": 5}},
                "years": {"2026": {"starts": 20}},
            }
            boat = {"racer_id": "4001", "lane": 2, "predicted_course": 2}
            p.apply_profile(boat, "24")
            self.assertIn("course_win_rate", boat)
            self.assertIn("course_top2_rate", boat)
            self.assertEqual(boat["racer_profile_course_samples"], 10)
            self.assertEqual(boat["racer_profile_course_win_methods"]["差し"], 4)
            self.assertEqual(boat["racer_profile_avg_st"], .14)
        finally:
            p.profile_for = original

    def test_three_year_backfill_floor_and_cursor(self):
        state = {"backfill": {"next_day": "20221231"}}
        out = l.run_backfill(
            state,
            recent_day="20260918",
            days=6,
            floor_day="20230101",
        )
        self.assertTrue(out["completed"])
        self.assertEqual(out["processed_days"], 0)


if __name__ == "__main__":
    unittest.main()
