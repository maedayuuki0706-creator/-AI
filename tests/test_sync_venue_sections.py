"""Safety regression for 24 venue tabs: race IDs, duplicates, manual slots."""
import unittest
from unittest.mock import patch
from sync_venue_sections import (
    day, section_window, official_result_records, calculated_cells,
    valid_runs, build_new_roster, VENUES,
)


def result(dt="20261008", rno=3, rid="1234", finish="1"):
    return dict(start="20261006", day=dt, rno=rno, rid=rid,
                lane="4", course="3", st="0.12", finish=finish, method="まくり")


def existing(rid="1234", start="2026/10/06"):
    row = [""] * 55
    row[0], row[1], row[2], row[3] = "田中", rid, start, "2026/10/11"
    row[15:19] = ["0", "0", "0", "0"]
    return row


class VenueSyncTests(unittest.TestCase):
    def test_date_normalizer(self):
        self.assertEqual(day("2026/10/08"), "20261008")
        self.assertEqual(day("20261008"), "20261008")
        self.assertEqual(day("bad"), "")

    def test_meeting_window_requires_full_official_proof(self):
        self.assertEqual(section_window("20261008", "10月6日初日 10月11日最終日"),
                         ("20261006", "20261011"))
        self.assertIsNone(section_window("20261008", "10月6日初日"))

    def test_new_finished_race_updates_only_summary_and_slot(self):
        row = existing()
        proposed, conflict = calculated_cells(row, [result()])
        self.assertFalse(conflict)
        self.assertEqual(proposed[5], 1)  # S, series races
        self.assertEqual(proposed[2], 1)  # P, first places
        self.assertEqual(proposed[6:12], [3, 4, 3, "0.12", "1", "まくり"])
        self.assertEqual(row[19], "")  # Original row still untouched.

    def test_identical_result_is_a_noop(self):
        row = existing()
        first, _ = calculated_cells(row, [result()])
        row[13:55] = first
        second, conflict = calculated_cells(row, [result()])
        self.assertFalse(conflict)
        self.assertIsNone(second)

    def test_existing_conflicting_race_never_overwritten(self):
        row = existing()
        row[19] = "7"  # Different manual race number in slot 1.
        row[18] = "1"
        proposed, conflict = calculated_cells(row, [result()])
        self.assertIsNone(proposed)
        self.assertTrue(conflict)

    def test_source_cannot_reduce_manual_settled_count(self):
        row = existing()
        row[18] = "9"
        proposed, conflict = calculated_cells(row, [result()])
        self.assertIsNone(proposed)
        self.assertFalse(conflict)

    def test_complementary_duplicate_keeps_verified_st(self):
        f = [""] * 43
        for i, val in [(0, "桐生"), (1, "2026/10/06"), (2, "2026/10/08"),
                       (4, "1234"), (9, "3"), (11, "4"), (16, "0.18"),
                       (17, "2"), (36, "4"), (42, "逃げ")]:
            f[i] = val
        raw = ["20261008", "桐生", "3", "4", "1234", "田中",
               "1", "3", "0.12", "まくり", "", "", "", "", "1"]
        loaded = official_result_records([[], f], [[], raw])
        self.assertEqual(len(loaded["桐生"]["1234"]), 1)
        self.assertEqual(loaded["桐生"]["1234"][0]["st"], "0.12")
        self.assertEqual(loaded["桐生"]["1234"][0]["finish"], "1")

    def test_unconfirmed_raw_is_ignored(self):
        raw = ["20261008", "桐生", "3", "4", "1234", "田中",
               "1", "3", "0.12", "まくり", "", "", "", "", "0"]
        loaded = official_result_records([], [[], raw])
        self.assertFalse(loaded.get("桐生"))

    def test_venue_roster_requires_complete_official_field(self):
        with patch("sync_venue_sections.official.parse_racelist_boats", return_value=[]):
            roster = build_new_roster("20261008", "01", "20261008", "20261013",
                                      "official", "一般", {}, {})
        self.assertEqual(roster, [])


if __name__ == "__main__":
    unittest.main()
