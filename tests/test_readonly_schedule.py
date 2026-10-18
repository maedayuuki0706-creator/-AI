"""Tests for the isolated, read-only official schedule endpoint."""
import unittest
from unittest.mock import patch
import sheet_feed_server as feed


class ReadOnlyScheduleTests(unittest.TestCase):
    def setUp(self):
        self.cache = patch.object(feed, "_cached", side_effect=lambda key, build: build())
        self.cache.start()

    def tearDown(self):
        self.cache.stop()

    def test_full_venues_and_deadline_sort(self):
        def fake_deadlines(day, jcd):
            self.assertEqual(day, "20261019")
            if jcd == "01":
                return [f"{8 + (i // 4):02d}:{(i % 4) * 10:02d}" for i in range(12)]
            return [f"{9 + (i // 4):02d}:{(i % 4) * 10:02d}" for i in range(12)]

        with patch.object(feed, "discover_venues", return_value=["01", "02"]), \
             patch.object(feed, "deadlines", side_effect=fake_deadlines):
            result = feed.schedule_snapshot("20261019")
        self.assertEqual(result["day"], "20261019")
        self.assertEqual(result["venues"], 2)
        self.assertEqual(len(result["races"]), 24)
        self.assertEqual(result["races"][0], {"jcd": "01", "rno": 1, "deadline": "08:00"})
        self.assertFalse(result["partial"])
        self.assertEqual(result["missing_venue_codes"], [])

    def test_partial_time_list_is_not_misrepresented_as_complete(self):
        with patch.object(feed, "discover_venues", return_value=["03"]), \
             patch.object(feed, "deadlines", return_value=["10:01", "10:10"]):
            result = feed.schedule_snapshot("20261019")
        self.assertEqual(result["races"], [])
        self.assertTrue(result["partial"])
        self.assertEqual(result["missing_venue_codes"], ["03"])

    def test_official_fetch_failure_is_not_called_non_held(self):
        with patch.object(feed, "discover_venues", return_value=["23"]), \
             patch.object(feed, "deadlines", side_effect=RuntimeError("source timeout")):
            result = feed.schedule_snapshot("20261019")
        self.assertTrue(result["partial"])
        self.assertEqual(result["venues"], 1)
        self.assertEqual(result["races"], [])
        self.assertEqual(result["missing_venue_codes"], ["23"])


if __name__ == "__main__":
    unittest.main()
