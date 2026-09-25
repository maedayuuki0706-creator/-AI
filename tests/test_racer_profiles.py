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

    def test_apply_profile_exposes_shared_inside_and_attack_history(self):
        original = p.profile_for
        try:
            profile = {
                "starts": 80,
                "avg_st": .14,
                "win_methods": {"逃げ": 10, "まくり": 2, "まくり差し": 1},
                "course_win_methods": {},
                "courses": {
                    "1": {
                        "starts": 20, "wins": 12, "top2": 16,
                        "weighted_starts": 20.0, "weighted_wins": 12.0, "weighted_top2": 16.0,
                        "avg_st": .13, "win_methods": {"逃げ": 10, "抜き": 2},
                    },
                    "3": {
                        "starts": 20, "wins": 4, "top2": 8,
                        "weighted_starts": 20.0, "weighted_wins": 4.0, "weighted_top2": 8.0,
                        "avg_st": .15, "win_methods": {"まくり": 2, "まくり差し": 1, "抜き": 1},
                    },
                },
                "venues": {"24": {"starts": 10}},
                "years": {"2026": {"starts": 40}},
            }
            p.profile_for = lambda _: profile

            inside = {"racer_id": "4001", "lane": 1, "predicted_course": 1}
            p.apply_profile(inside, "24")
            self.assertEqual(inside["course_history_samples"], 20)
            self.assertAlmostEqual(inside["course_history_avg_st"], .13)
            self.assertAlmostEqual(inside["in_escape_rate"], 50.0)
            self.assertAlmostEqual(inside["in_loss_rate"], 40.0)

            attacker = {"racer_id": "4001", "lane": 3, "predicted_course": 3}
            p.apply_profile(attacker, "24")
            self.assertAlmostEqual(attacker["course_makuri_rate"], 10.0)
            self.assertAlmostEqual(attacker["course_makurisashi_rate"], 5.0)
            self.assertAlmostEqual(attacker["course_attack_rate"], 15.0)
        finally:
            p.profile_for = original

    def test_start_correction_learns_late_exhibition_to_fast_race_start(self):
        state = {
            "racers": {},
            "processed_races": [],
            "start_correction_processed_races": [],
            "weight_anchor_day": "20260925",
        }
        result = {
            "day": "20260925",
            "jcd": "08",
            "method": "まくり",
            "finish": [{
                "racer_id": "4001", "name": "選手A", "lane": 4, "course": 4,
                "st": .08, "exhibition_st_timing": .22,
                "finish": 1, "status": "finished",
            }],
        }
        learned = l.update_start_correction_from_result(state, result)
        self.assertEqual(learned, 1)
        row = state["racers"]["4001"]["start_correction_courses"]["4"]
        self.assertAlmostEqual(row["late_avg_correction"], .14)
        self.assertEqual(row["late_to_fast"], 1)
        self.assertEqual(row["late_to_zero"], 1)
        self.assertEqual(row["late_makuri_wins"], 1)

    def test_profile_exposes_start_correction_by_course(self):
        original = p.profile_for
        try:
            p.profile_for = lambda _: {
                "starts": 40,
                "avg_st": .13,
                "courses": {"4": {
                    "starts": 10, "wins": 2, "top2": 4,
                    "weighted_starts": 10, "weighted_wins": 2, "weighted_top2": 4,
                    "avg_st": .12, "win_methods": {"まくり": 2},
                }},
                "venues": {},
                "years": {},
                "win_methods": {"まくり": 2},
                "course_win_methods": {"4": {"まくり": 2}},
                "start_correction": {"samples": 10, "avg_correction": .04},
                "start_correction_courses": {"4": {
                    "samples": 8, "avg_correction": .05,
                    "late_samples": 5, "late_avg_correction": .09,
                    "late_to_fast": 4, "late_to_zero": 2,
                    "late_makuri_wins": 2, "late_makurisashi_wins": 0,
                }},
            }
            boat = {"racer_id": "4001", "lane": 4, "predicted_course": 4}
            p.apply_profile(boat, "08")
            self.assertEqual(boat["start_correction_samples"], 8)
            self.assertEqual(boat["late_exhibition_samples"], 5)
            self.assertAlmostEqual(boat["late_start_correction_avg"], .09)
            self.assertAlmostEqual(boat["late_to_fast_rate"], 80.0)
            self.assertAlmostEqual(boat["late_makuri_win_rate"], 40.0)
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
