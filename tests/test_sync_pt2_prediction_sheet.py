import unittest
from datetime import datetime

import sync_pt2_prediction_sheet as view


class PT2PredictionSheetTests(unittest.TestCase):
    def record(self):
        cards = {
            "balanced": {
                "main_picks": ["1-3-2", "1-3-4", "1-3-6"],
                "cover_picks": ["1-2-3", "3-1-2"],
                "picks": ["1-3-2", "1-3-4", "1-3-6", "1-2-3", "3-1-2"],
                "point_count": 5,
            },
            "probability": {
                "main_picks": ["1-3-2", "1-3-4"],
                "cover_picks": ["1-2-3", "1-2-4"],
                "picks": ["1-3-2", "1-3-4", "1-2-3", "1-2-4"],
                "point_count": 4,
            },
            "value": {
                "main_picks": ["5-1-2", "2-4-1"],
                "cover_picks": ["1-3-6"],
                "picks": ["5-1-2", "2-4-1", "1-3-6"],
                "point_count": 3,
            },
            "longshot": {
                "main_picks": ["5-1-2", "2-4-1"],
                "cover_picks": ["1-6-3"],
                "picks": ["5-1-2", "2-4-1", "1-6-3"],
                "point_count": 3,
                "pick_metrics": [
                    {"combination": "5-1-2", "odds": 105.8},
                    {"combination": "2-4-1", "odds": 388.7},
                    {"combination": "1-6-3", "odds": 70.0},
                ],
            },
        }
        return {
            "key": "20261007_24_08",
            "venue": "大村",
            "rno": 8,
            "deadline": "18:10",
            "created_at": "2026-10-07T17:55:00+09:00",
            "models": {
                "prototype2": {
                    "model_version": "new-pt2-full-sheet-db-v2",
                    "strategy_cards": {"version": "pt2-multi-strategy-v1", "cards": cards},
                    "database": {
                        "player_matches": 6,
                        "motor_matches": 6,
                        "venue_volatility": 44.2,
                        "probability_audit": {
                            "adjusted_heads": {
                                "1": 0.48, "2": 0.13, "3": 0.18,
                                "4": 0.09, "5": 0.08, "6": 0.04,
                            }
                        },
                    },
                }
            },
        }

    def test_compacts_common_prefix(self):
        self.assertEqual(
            view._compact_formations(["1-3-2", "1-3-4", "1-3-6"]),
            ["1-3-246"],
        )

    def test_payload_contains_four_strategy_panels(self):
        payload = view.build_payload(self.record())["values"]
        self.assertIn("1-3-246", payload["B7"])
        self.assertIn("5-1-2", payload["B17"])
        self.assertIn("2-4-1", payload["B22"])
        self.assertEqual(payload["A29"], "1号艇")
        self.assertEqual(payload["G29"], "6/6 選手\n6/6 M")
        self.assertIn("5-1-2", payload["K29"])
        self.assertIn("2-4-1", payload["K29"])

    def test_payload_selector_contains_race_and_deadline(self):
        payload = view.build_payload(self.record())
        self.assertEqual(payload["selector"], "大村 8R｜18:10")
        self.assertEqual(payload["helper_row"][0], "大村 8R｜18:10")
        self.assertEqual(payload["helper_row"][1], "20261007_24_08")

    def test_prediction_log_row_preserves_key_and_cards(self):
        record = self.record()
        payload = view.build_payload(record)
        row = view._prediction_log_row(
            record,
            payload,
            saved_at=datetime.fromisoformat("2026-10-07T18:30:00+09:00"),
        )
        self.assertEqual(len(row), len(view.LOG_HEADERS))
        self.assertEqual(row[1], "20261007")
        self.assertEqual(row[2], "大村")
        self.assertEqual(row[3], "8")
        self.assertEqual(row[5], "20261007_24_08")
        self.assertIn("5-1-2", row[14])
        self.assertEqual(row[29:], ["", "", "", "", "", ""])

    def test_deadline_parser_uses_jst(self):
        deadline = view._deadline_at(self.record())
        self.assertEqual(deadline.isoformat(), "2026-10-07T18:10:00+09:00")

    def test_index_uses_db_adjusted_head_probability(self):
        payload = view.build_payload(self.record())["values"]
        self.assertEqual(payload["A5"], "31")
        self.assertEqual(payload["K5"], "-13")


if __name__ == "__main__":
    unittest.main()
