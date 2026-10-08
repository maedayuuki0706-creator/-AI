"""Offline regression: delta writes must preserve all settled AI history."""
import unittest

from sync_realtime_ai_stats import LOG_HEADER, write_log


def record(day, ai, hits=0):
    row = [day, "2026-10-08T18:00:00+09:00", "桐生", 1,
           ai, "PT", 8, 800, hits * 3000, hits * 3000 - 800,
           "○" if hits else "×"]
    return row + [""] * (len(LOG_HEADER) - len(row))


class Sheet:
    def __init__(self, values):
        self.values = [list(row) for row in values]
        self.row_count = max(50, len(self.values) + 10)
        self.writes = []
        self.clears = []

    def get_all_values(self):
        # gspread returns all values as strings, dropping trailing empty cells.
        result = []
        for row in self.values:
            trimmed = [str(v) if v is not None else "" for v in row]
            while trimmed and trimmed[-1] == "":
                trimmed.pop()
            result.append(trimmed)
        while result and not result[-1]:
            result.pop()
        return result

    def add_rows(self, count):
        self.row_count += count

    def update(self, values, location, raw=True):
        assert location.startswith("A"), location
        start = int(location[1:]) - 1
        self.writes.append((start, values))
        while len(self.values) < start + len(values):
            self.values.append([])
        for i, row in enumerate(values):
            self.values[start + i] = list(row)

    def batch_clear(self, ranges):
        self.clears += ranges
        for item in ranges:
            start = int(item.split(":")[0][1:]) - 1
            end = int(item.split(":")[1][1:])
            for i in range(start, min(end, len(self.values))):
                self.values[i] = []

    def clear(self):
        raise AssertionError("Whole-sheet clear would erase unrelated history")


class RealtimeLogDeltaTests(unittest.TestCase):
    def test_unchanged_log_does_no_write(self):
        day = "20261008"
        ws = Sheet([LOG_HEADER, record(day, "PT1")])
        write_log(ws, day, [record(day, "PT1")])
        self.assertEqual(ws.writes, [])
        self.assertEqual(ws.clears, [])

    def test_append_only_sends_one_new_row_not_entire_log(self):
        day = "20261008"
        older = record("20261007", "メインくん")
        current = record(day, "PT1")
        added = record(day, "PT2")
        ws = Sheet([LOG_HEADER, older, current])
        write_log(ws, day, [current, added])
        self.assertEqual(len(ws.writes), 1)
        self.assertEqual(ws.writes[0][0], 3)
        self.assertEqual(ws.values[1], older)
        self.assertEqual(ws.values[3], added)
        self.assertEqual(ws.clears, [])

    def test_corrected_result_and_shortened_tail_preserve_other_days(self):
        day = "20261008"
        older = record("20261007", "穴くん")
        current = record(day, "PT1")
        changed = record(day, "PT1", hits=1)
        ws = Sheet([LOG_HEADER, older, current, record(day, "PT2")])
        write_log(ws, day, [changed])
        self.assertEqual(ws.values[1], older)
        self.assertEqual(ws.values[2], changed)
        self.assertEqual(ws.clears, ["A4:T4"])

    def test_reported_blank_cells_clear_old_values(self):
        day = "20261008"
        original = record(day, "PT1")
        original[-1] = "v1"
        replacement = record(day, "PT1")
        ws = Sheet([LOG_HEADER, original])
        write_log(ws, day, [replacement])
        self.assertEqual(ws.values[1][-1], "")


if __name__ == "__main__":
    unittest.main()
