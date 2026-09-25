import unittest

import opportunity_alerts
from prediction_engine import analyze_race


class RaceShapeFeatureTests(unittest.TestCase):
    def _boats(self):
        boats = []
        for lane in range(1, 7):
            course = lane
            boat = {
                "lane": lane,
                "course": course,
                "predicted_course": course,
                "win_rate": 6.0,
                "top2_rate": 40.0,
                "top3_rate": 60.0,
                "course_win_rate": 55.0 if course == 1 else 15.0,
                "course_top2_rate": 72.0 if course == 1 else 38.0,
                "avg_st": 0.15,
                "exhibition_st": 0.15,
                "motor_top2_rate": 38.0,
                "motor_top3_rate": 58.0,
                "exhibition_grade": 0.5,
                "course_history_samples": 30,
                "course_history_avg_st": 0.15,
            }
            if course == 1:
                boat["in_escape_rate"] = 60.0
            else:
                boat["course_attack_rate"] = 15.0
            boats.append(boat)
        return boats

    def test_race_shape_is_emitted_for_every_analysis(self):
        out = analyze_race({"race": {"venue": "福岡"}, "boats": self._boats()})
        shape = out["race_shape"]
        self.assertIn("inside_trust", shape)
        self.assertIn("attack_pressure", shape)
        self.assertIn("upset_risk", shape)
        self.assertIn("pattern", shape)
        self.assertGreaterEqual(shape["data_confidence"], 0.35)

    def test_shape_gate_accepts_matching_attack_and_rejects_mismatch(self):
        payload = {
            "score": 86,
            "picks": [{
                "combination": "3-1-2",
                "odds": 100.0,
                "probability": 0.015,
                "expected_value": 1.50,
            }],
            "race_shape": {
                "data_confidence": 0.8,
                "upset_risk": 60.0,
                "attack_pressure": 55.0,
                "inside_trust": 35.0,
                "best_attack_lane": 3,
                "pattern": "center_attack",
            },
        }
        analysis = {"preview": {"wind_speed": 2}, "heads": {"1": 0.40, "3": 0.20}}
        self.assertTrue(opportunity_alerts._is_selected_longshot(payload, analysis))

        payload["race_shape"] = dict(payload["race_shape"], best_attack_lane=4)
        self.assertFalse(opportunity_alerts._is_selected_longshot(payload, analysis))

    def test_shape_gate_allows_supported_escape_follower_upset(self):
        payload = {
            "score": 84,
            "picks": [{
                "combination": "1-4-6",
                "odds": 100.0,
                "probability": 0.012,
                "expected_value": 1.20,
            }],
            "race_shape": {
                "data_confidence": 0.8,
                "upset_risk": 38.0,
                "attack_pressure": 43.0,
                "inside_trust": 58.0,
                "best_attack_lane": 4,
                "pattern": "inside_escape_rough_followers",
            },
        }
        analysis = {"preview": {"wind_speed": 2}, "heads": {"1": 0.45, "4": 0.18}}
        self.assertTrue(opportunity_alerts._is_selected_longshot(payload, analysis))


if __name__ == "__main__":
    unittest.main()
