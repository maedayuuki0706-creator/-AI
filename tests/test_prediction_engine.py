import unittest

from prediction_engine import analyze_race, score_boat


class PredictionEngineTests(unittest.TestCase):
    def _boats(self):
        return [
            {
                "lane": i,
                "course": i,
                "win_rate": 6.0,
                "top2_rate": 40,
                "top3_rate": 60,
                "course_win_rate": 20 if i != 1 else 55,
                "course_top2_rate": 40 if i != 1 else 75,
                "avg_st": 0.15,
                "exhibition_st": 0.14,
                "motor_top2_rate": 38,
                "motor_top3_rate": 58,
                "motor_grade": "B",
                "exhibition_grade": "B",
                "turn_grade": "B",
                "straight_grade": "B",
                "pit_out_grade": "B",
                "lap_grade": "B",
                "local_win_rate": 6.0,
                "local_top2_rate": 40,
                "entry_grade": "B",
                "comment_grade": "B",
            }
            for i in range(1, 7)
        ]

    def test_returns_120_trifectas(self):
        out = analyze_race({"race": {"venue": "大村"}, "boats": self._boats()})
        self.assertEqual(len(out["trifecta"]), 120)
        self.assertEqual(out["boats"][0]["lane"], 1)

    def test_strong_wind_reduces_inside_condition_component(self):
        boats = self._boats()
        calm = score_boat(boats[0], {"venue": "戸田", "wind_speed": 0})
        windy = score_boat(
            boats[0],
            {"venue": "戸田", "wind_speed": 6, "wind_direction": "向かい風"},
        )
        self.assertLess(windy["components"]["conditions"], calm["components"]["conditions"])

    def test_shared_history_refines_inside_and_attack_scores(self):
        boats = self._boats()

        neutral_inside = score_boat(dict(boats[0]), {"venue": "大村"})
        strong_inside = dict(boats[0])
        strong_inside.update({
            "course_history_samples": 30,
            "course_history_avg_st": 0.13,
            "in_escape_rate": 75.0,
        })
        strong_inside_score = score_boat(strong_inside, {"venue": "大村"})
        self.assertGreater(strong_inside_score["score"], neutral_inside["score"])
        self.assertGreater(strong_inside_score["components"]["history"], 0.5)

        neutral_three = score_boat(dict(boats[2]), {"venue": "福岡"})
        attack_three = dict(boats[2])
        attack_three.update({
            "course_history_samples": 30,
            "course_history_avg_st": 0.13,
            "course_attack_rate": 30.0,
        })
        attack_three_score = score_boat(attack_three, {"venue": "福岡"})
        self.assertGreater(attack_three_score["score"], neutral_three["score"])
        self.assertGreater(attack_three_score["components"]["history"], 0.5)

    def test_expected_value_is_calculated(self):
        boats = self._boats()
        out = analyze_race({
            "race": {"venue": "大村"},
            "boats": boats,
            "trifecta_odds": {"1-2-3": 50.0},
        })
        row = next(x for x in out["trifecta"] if x["combination"] == "1-2-3")
        self.assertIsNotNone(row["expected_value"])
        self.assertGreater(row["fair_odds"], 0)


if __name__ == "__main__":
    unittest.main()
