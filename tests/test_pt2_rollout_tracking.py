import unittest

import prototype12_delivery as delivery
import prototype_scoreboard as scoreboard


class PT2RolloutTrackingTests(unittest.TestCase):
    def test_rollout_metadata_records_full_db_identity(self):
        model = {
            "database": {
                "enabled": True,
                "schema_version": "pt2-sheet-db-v2",
                "snapshot_at": "2026-10-07T13:02:56+09:00",
                "snapshot_player_count": 1660,
                "snapshot_motor_count": 1505,
                "snapshot_venue_count": 24,
                "player_matches": 6,
                "motor_matches": 6,
            }
        }
        meta = delivery.pt2_rollout_metadata(model)
        self.assertEqual(meta["model_version"], delivery.PT2_MODEL_VERSION)
        self.assertEqual(meta["version_label"], "新PT2")
        self.assertEqual(meta["db_snapshot_player_count"], 1660)
        self.assertEqual(meta["db_snapshot_motor_count"], 1505)
        self.assertEqual(meta["db_player_matches"], 6)
        self.assertEqual(meta["db_motor_matches"], 6)
        self.assertTrue(meta["db_enabled"])

    def test_pre_tag_full_db_snapshot_is_classified_as_new(self):
        model = {"database": {"snapshot_at": "2026-10-07T13:02:56.865+09:00"}}
        self.assertEqual(delivery.pt2_model_version(model), delivery.PT2_MODEL_VERSION)
        self.assertEqual(scoreboard.pt2_model_version(model), scoreboard.PT2_NEW_VERSION)

        old = {"database": {"snapshot_at": "2026-10-05T16:56:44+09:00"}}
        self.assertEqual(delivery.pt2_model_version(old), delivery.PT2_LEGACY_VERSION)
        self.assertEqual(scoreboard.pt2_model_version(old), scoreboard.PT2_LEGACY_VERSION)

    def test_learning_audit_tracks_db_added_pick(self):
        official = {
            "trifecta": [
                {"combination": "1-2-3", "probability": 0.10, "odds": 8.0},
                {"combination": "1-3-2", "probability": 0.05, "odds": 20.0},
            ]
        }
        pt2 = {
            "trifecta": [
                {"combination": "1-2-3", "probability": 0.08, "odds": 8.0, "expected_value": 0.64},
                {"combination": "1-3-2", "probability": 0.07, "odds": 20.0, "expected_value": 1.4},
            ],
            "sheet_database": {
                "lane_factors": {"1": {"factor": 1.01, "signals": ["course=60.0/55.0"]}},
                "probability_audit": {
                    "base_probability": {"1-2-3": 0.10, "1-3-2": 0.05},
                    "head_delta_pp": {"1": 0.0},
                    "top_combination_shifts": [],
                },
            },
        }
        model = {
            "picks": ["1-3-2"],
            "main_picks": ["1-3-2"],
            "cover_picks": [],
        }
        audit = delivery.pt2_learning_audit(
            official, pt2, ["1-2-3"], ["1-2-3", "1-3-2"], model
        )
        self.assertEqual(audit["added_by_db"], ["1-3-2"])
        row = audit["pick_explanations"][0]
        self.assertTrue(row["added_by_db"])
        self.assertEqual(row["delta_pp"], 2.0)
        self.assertEqual(row["base_ev"], 1.0)
        self.assertEqual(row["adjusted_ev"], 1.4)

    def test_message_distinguishes_legacy_and_new_pt2(self):
        base_model = {
            "main_picks": ["1-2-3"],
            "cover_picks": ["1-3-2"],
            "point_count": 2,
            "grade": "A",
            "database": {
                "enabled": True,
                "player_matches": 6,
                "motor_matches": 6,
                "venue_match": True,
            },
        }
        record = {
            "venue": "徳山",
            "rno": 10,
            "deadline": "13:30",
            "models": {"prototype2": dict(base_model)},
        }
        legacy = delivery.model_message(record, "prototype2")
        self.assertIn("旧PT2", legacy)

        record["models"]["prototype2"].update({
            "model_version": delivery.PT2_MODEL_VERSION,
            "version_label": delivery.PT2_VERSION_LABEL,
        })
        new = delivery.model_message(record, "prototype2")
        self.assertIn("新PT2", new)


if __name__ == "__main__":
    unittest.main()
