import unittest

from prediction_engine_v2 import ALL_VENUE_PROFILES, analyze_race_v2


class PredictionEngineV2Tests(unittest.TestCase):
    def _boats(self):
        return [
            {
                "lane": i,
                "course": i,
                "win_rate": 6.0,
                "top2_rate": 40,
                "top3_rate": 60,
                "avg_st": 0.15,
                "motor_top2_rate": 38,
                "motor_top3_rate": 58,
                "local_win_rate": 6.0,
                "local_top2_rate": 40,
                "weight": 52.0,
            }
            for i in range(1, 7)
        ]

    def test_all_24_venues_have_profiles(self):
        self.assertEqual(len(ALL_VENUE_PROFILES), 24)

    def test_v2_returns_120_trifectas(self):
        out = analyze_race_v2({"race": {"venue": "蒲郡"}, "boats": self._boats()})
        self.assertEqual(out["model_version"], "kyoutei-navi-knowledge-v2")
        self.assertEqual(len(out["trifecta"]), 120)

    def test_course_flow_reorders_probabilities_without_losing_mass(self):
        out = analyze_race_v2({"race": {"venue": "戸田"}, "boats": self._boats()})
        total = sum(x["probability"] for x in out["trifecta"])
        self.assertAlmostEqual(total, 1.0, places=8)


if __name__ == "__main__":
    unittest.main()
