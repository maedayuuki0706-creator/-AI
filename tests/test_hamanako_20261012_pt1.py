"""Pure tests for the one-day PT1 special. All network calls are mocked."""
import unittest
from unittest.mock import patch
from datetime import datetime

import hamanako_20261012_pt1 as m


def sample_live():
    models = {
        "existing": {"picks": ["1-2-3", "1-3-2", "3-1-4"]},
        "hiyori": {"picks": ["1-2-3", "4-1-5", "3-1-4"]},
        "prototype1": {"picks": ["1-2-3", "1-3-2", "1-2-4"],
                       "box_lanes": [1, 2, 3]},
        "prototype2": {"picks": ["1-2-3", "3-1-4", "4-1-5"]},
        "prototype3": {"picks": ["1-2-3", "3-1-4", "4-1-5"]},
    }
    return {
        "models": models, "selectors": {"中穴選別": ["4-1-5"], "穴選別": ["3-1-4"]},
        "db_picks": ["1-2-3", "3-1-4", "4-1-5"],
        "db_info": {"enabled": True, "snapshot_at": "2026-10-11T20:00+09:00"},
        "deadline": "10:58",
        "odds": {"1-2-3": 15., "1-3-2": 18., "3-1-4": 106., "4-1-5": 110.},
        "official": {
            "inputs": [
                {"lane": lane, "name": f"選手{lane}", "current_class": "A1" if lane == 1 else "B1",
                 "motor_top2_rate": 30.0, "exhibition_st": .10 + lane / 100}
                for lane in range(1, 7)
            ],
            "preview": {"wind_speed": 4, "wave_cm": 3,
                        "tide": {"available": True, "phase": "rising",
                                 "station": "舞阪", "nearest_turn_minutes": 43}},
        },
    }


class HamanakoOneDayTests(unittest.TestCase):
    def test_unique_and_no_invalid_combos(self):
        self.assertEqual(m.distinct(["1-2-3", "1-2-3", "1-1-2", "0-2-3", "3-1-4"]),
                         ["1-2-3", "3-1-4"])

    def test_message_has_requested_sections(self):
        content = m.format_message(m.DAY, 1, sample_live())
        for section in ("浜名湖1R", "根拠・展開予想", "本線", "抑え", "3艇BOX",
                        "DB総合予想", "天候・潮の影響", "上げ潮"):
            self.assertIn(section, content)
        self.assertLessEqual(len(content), 1950)
        self.assertIn("123", content)
        self.assertIn("5AI一致", content)

    def test_compression_is_exact_and_duplicate_free(self):
        picks = ["1-2-4", "1-2-5", "1-3-4", "1-3-5", "1-2-4"]
        compressed = m.compress_exact(picks)
        expanded = []
        for line in compressed:
            first, seconds, thirds = line.split("-")
            expanded += [f"{first}-{b}-{c}" for b in seconds for c in thirds]
        self.assertEqual(set(expanded), set(picks))
        self.assertEqual(len(expanded), len(set(expanded)))
        self.assertIn("1-23-45", compressed)

    def test_no_false_tide_assertion(self):
        s = m.format_conditions({"wind_speed": None, "wave_cm": None,
                                 "tide": {"available": False}})
        self.assertIn("未取得", s)
        self.assertIn("風向は未判定", s)
        self.assertNotIn("上げ潮", s)

    def test_no_automatic_retry_when_receipt_exists(self):
        from urllib.error import HTTPError
        exc = HTTPError("url", 422, "already exists", {}, None)
        with patch.object(m, "github_request", side_effect=exc):
            self.assertEqual(m.reserve(1, "message"), (None, None))

    def test_no_real_post_on_dry_run(self):
        with patch.object(m, "build_live", return_value=(sample_live(), "ready")), \
             patch.object(m, "reserve") as reserve, \
             patch.object(m, "discord_post") as send:
            self.assertTrue(m.process_one(m.DAY, 1, "10:58", dry_run=True))
            reserve.assert_not_called()
            send.assert_not_called()

    def test_post_claim_ack_and_receipt(self):
        with patch.dict(m.os.environ, {"PROTO1_DISCORD_WEBHOOK_URL": "https://example.invalid/webhook",
                                        "GITHUB_TOKEN": "dummy",
                                        "GITHUB_REPOSITORY": "maedayuuki0706-creator/-AI"}), \
             patch.object(m, "build_live", return_value=(sample_live(), "ready")), \
             patch.object(m, "reserve", return_value=("path", "sha")) as reserve, \
             patch.object(m, "discord_post", return_value="123456789") as send, \
             patch.object(m, "mark_delivered") as mark:
            self.assertTrue(m.process_one(m.DAY, 1, "10:58"))
            reserve.assert_called_once()
            send.assert_called_once()
            mark.assert_called_once_with("path", "sha", 1, "123456789")


if __name__ == "__main__":
    unittest.main()
