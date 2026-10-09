import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import manshu_shadow_watch as m

class WatchTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 10, 11, 20, tzinfo=ZoneInfo("Asia/Tokyo"))
        self.sample = {
            "day": "20261010", "jcd": "16", "rno": 5, "venue": "児島",
            "deadline": "11:40", "settled": False, "captured_at": "2026-10-10T11:15:00+09:00",
            "rows": [
                {"lane": i, "exhibition_st": 0.21 if i == 1 else 0.08,
                 "exhibition_time": 7.01 if i == 1 else 6.81,
                 "exhibition_rank": 6 if i == 1 else i-1,
                 "wind_m": 4, "wave_cm": 4, "actual_course": None,
                 "actual_st": None, "finish": None} for i in range(1, 7)
            ]
        }
    def test_guard_before_deadline(self):
        x = m.classify(self.sample, self.now)
        self.assertTrue(x["alert"])
        self.assertIn("イン敗北警戒", x["types"])
        self.assertEqual(x["pre_wave_cm"], 4)
        self.assertIsNone(m.classify({**self.sample, "settled": True}, self.now))
        self.assertIsNone(m.classify(self.sample, datetime(2026,10,10,11,41,tzinfo=ZoneInfo("Asia/Tokyo"))))
        self.sample["rows"][0]["finish"] = 1
        self.assertIsNone(m.classify(self.sample, self.now))
    def test_outcomes_are_posthoc(self):
        x = m.classify(self.sample, self.now)
        self.assertIsNone(x["outcome"])
        self.assertFalse(m.adjudicate(x, {}))
        self.assertTrue(m.adjudicate(x, {"16:5": {"status":"settled","payouts":{"3-4-5":12660}}}))
        self.assertFalse(m.adjudicate(x, {"16:5": {"status":"settled","payouts":{"3-4-5":12660}}}))
        self.assertEqual(m.summarize("20261010", {x["key"]:x})["alert_manshu_races"], 1)
    def test_idempotent_and_unmodified_history(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            src=base/"exhibition"/"20261010"
            src.mkdir(parents=True)
            payout=base/"official"
            payout.mkdir()
            state=base/"state"
            file=src/"16_05.json"
            file.write_text(json.dumps(self.sample), encoding="utf-8")
            self.assertEqual(m.run(src.parent,payout,state,self.now)[0]["alert_races"], 1)
            self.sample["rows"][0]["wave_cm"] = 9
            file.write_text(json.dumps(self.sample), encoding="utf-8")
            self.assertEqual(m.run(src.parent,payout,state,self.now)[0]["alert_races"], 1)
            record=json.loads((state/"20261010.json").read_text())
            self.assertEqual(record["entries"]["20261010_16_05"]["pre_wave_cm"], 4)

if __name__ == "__main__":
    unittest.main()
