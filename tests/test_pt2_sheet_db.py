import itertools
import unittest
import pt2_sheet_db

class PT2SheetDatabaseTests(unittest.TestCase):
    def analysis(self):
        boats = [
            {"lane": lane, "predicted_course": lane, "racer_id": str(1000 + lane),
             "motor_number": lane, "motor_top2_rate": 30.0}
            for lane in range(1, 7)
        ]
        rows = [
            {"combination": "-".join(map(str, combo)), "probability": 1 / 120, "odds": 20.0}
            for combo in itertools.permutations(range(1, 7), 3)
        ]
        return {"inputs": boats, "trifecta": rows, "heads": {lane: 1 / 6 for lane in range(1, 7)}}

    def database(self):
        players = {
            str(1000 + lane): {
                "course_win": [70.0 if i == lane else 10.0 for i in range(1, 7)],
                "escape": 60.0, "sashi": 20.0, "makuri": 20.0, "makurisashi": 20.0,
            }
            for lane in range(1, 7)
        }
        players["1001"]["course_win"][0] = 90.0
        motors = {
            f"20:{lane}": {
                "top2": 30.0, "launch": "S" if lane == 1 else "B",
                "turn": "S" if lane == 1 else "B", "stretch": "S" if lane == 1 else "B",
                "grade": "S" if lane == 1 else "B",
            }
            for lane in range(1, 7)
        }
        venues = {"20": {
            "course_win": [56.9, 12.0, 12.8, 10.9, 5.9, 1.9],
            "escape": 55.1, "sashi": 12.3, "makuri": 15.5, "makurisashi": 8.7,
            "volatility": 43.1,
        }}
        return {"players": players, "motors": motors, "venues": venues,
                "meta": {"source": "test", "snapshot_at": "2026-10-05T16:56:00+09:00"}}

    def test_database_refinement_is_normalized_and_reported(self):
        result = pt2_sheet_db.enhance_analysis(self.analysis(), "20", self.database())
        self.assertTrue(result["sheet_database"]["enabled"])
        self.assertEqual(result["sheet_database"]["player_matches"], 6)
        self.assertEqual(result["sheet_database"]["motor_matches"], 6)
        self.assertTrue(result["sheet_database"]["venue_match"])
        self.assertAlmostEqual(sum(row["probability"] for row in result["trifecta"]), 1.0, places=9)
        self.assertGreater(result["heads"][1], 1 / 6)

    def test_missing_snapshot_falls_back_without_breaking_prediction(self):
        result = pt2_sheet_db.enhance_analysis(
            self.analysis(), "20", {"players": {}, "motors": {}, "venues": {}, "meta": {}}
        )
        self.assertFalse(result["sheet_database"]["enabled"])
        self.assertEqual(result["sheet_database"]["player_matches"], 0)
        self.assertEqual(result["sheet_database"]["motor_matches"], 0)
        self.assertFalse(result["sheet_database"]["venue_match"])
        self.assertAlmostEqual(result["heads"][1], 1 / 6, places=9)

    def test_venue_only_snapshot_reports_fallback(self):
        db = {"players": {}, "motors": {}, "venues": self.database()["venues"],
              "meta": {"source": "test", "snapshot_at": "2026-10-07T12:00:00+09:00"}}
        result = pt2_sheet_db.enhance_analysis(self.analysis(), "20", db)
        self.assertFalse(result["sheet_database"]["enabled"])
        self.assertTrue(result["sheet_database"]["venue_match"])
        self.assertEqual(result["sheet_database"]["player_coverage_pct"], 0.0)
        self.assertEqual(result["sheet_database"]["motor_coverage_pct"], 0.0)
        self.assertAlmostEqual(result["heads"][1], 1 / 6, places=9)

if __name__ == "__main__":
    unittest.main()
