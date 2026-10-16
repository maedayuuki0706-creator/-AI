import json
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zoneinfo import ZoneInfo
from research.scenario_v2 import collector

JST = ZoneInfo("Asia/Tokyo")
BASE = datetime(2026, 10, 17, 18, 40, tzinfo=JST)


class FakeSource:
    def __init__(self, complete=True):
        self.queries = 0
        self.complete = complete

    def parse_racelist_boats(self, day, jcd, rno):
        self.queries += 1
        return [{"lane": lane, "racer_id": str(4000+lane), "avg_st": 0.16,
                 "motor_top2_rate": 40} for lane in range(1, 7)]

    def official_url(self, *args):
        return "https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd=20261017"

    def fetch(self, url):
        self.queries += 1
        return "fake fixed official HTML"

    def parse_beforeinfo(self, html):
        return {"entry_observed": True, "exhibition_count": 6 if self.complete else 5,
                "wind_speed": 3.0, "wave_cm": 3.0,
                "boats": {lane: {"exhibition_time": 6.7+lane/100,
                                  "predicted_course": lane, "exhibition_st_timing": .08+lane/100}
                          for lane in range(1,7)}}


class LogFirstTests(unittest.TestCase):
    def test_atomic_freeze_idempotent(self):
        with TemporaryDirectory() as tmp:
            source = FakeSource()
            got = collector.collect_once("20261017", "06", 7, "19:00", tmp,
                                         clock=lambda: BASE, source=source)
            self.assertEqual(got["status"], "locally_frozen_uncheckpointed")
            self.assertEqual(source.queries, 2)
            frozen = Path(tmp) / "forecasts/20261017/20261017_06_07.json"
            data = json.loads(frozen.read_text())
            self.assertEqual(data["mode"], "prospective_uncheckpointed")
            self.assertEqual(len(data["lanes"]), 6)
            again = collector.collect_once("20261017", "06", 7, "19:00", tmp,
                                           clock=lambda: BASE, source=source)
            self.assertEqual(again["status"], "already_frozen")
            self.assertEqual(source.queries, 2)

    def test_late_or_missing_inputs_not_frozen(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                collector.collect_once("20261017", "06", 7, "19:00", tmp,
                    clock=lambda: BASE+timedelta(minutes=19), source=FakeSource())
            with self.assertRaises(ValueError):
                collector.collect_once("20261017", "06", 7, "19:00", tmp,
                    clock=lambda: BASE, source=FakeSource(complete=False))
            self.assertFalse(list(Path(tmp).rglob("*07.json")))

    def test_immutable_forecast_and_conflicts(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/"x.json"
            self.assertTrue(collector.save_immutable(path, {"id": 1}))
            self.assertFalse(collector.save_immutable(path, {"id": 1}))
            with self.assertRaises(ValueError):
                collector.save_immutable(path, {"id": 2})

    def test_confirmation_requires_remote_match_and_early_commit(self):
        with TemporaryDirectory() as tmp:
            collector.collect_once("20261017", "06", 7, "19:00", tmp,
                                   clock=lambda: BASE, source=FakeSource())
            body = (Path(tmp)/"forecasts/20261017/20261017_06_07.json").read_text()
            sha = "a"*40
            with self.assertRaises(ValueError):
                collector.verify_remote_receipt(tmp,"20261017_06_07",sha,
                                                BASE.isoformat(),lambda *_: "{}")
            good = collector.verify_remote_receipt(tmp,"20261017_06_07",sha,
                                                  (BASE+timedelta(minutes=2)).isoformat(),
                                                  lambda *_: body)
            self.assertEqual(good["status"], "confirmed_before_deadline")
            self.assertTrue((Path(tmp)/"receipts/20261017/20261017_06_07.json").is_file())

    def test_bogus_commit_fails_closed(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                collector.verify_remote_receipt(tmp,"20261017_06_07","nope",
                                                BASE.isoformat(),lambda *_:"{}")


if __name__ == "__main__":
    unittest.main()
