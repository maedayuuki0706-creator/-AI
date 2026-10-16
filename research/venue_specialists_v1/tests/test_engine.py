import json
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zoneinfo import ZoneInfo

from research.venue_specialists_v1 import engine, run

JST = ZoneInfo("Asia/Tokyo")
PRIOR = {"course_win": [56, 14, 12, 9, 6, 3]}
VENUE_STATS = {c: PRIOR for c in ("16", "03", "23", "06")}


def fixture(code="16", day="20261017"):
    return {"meta": {"day": day, "jcd": code, "rno": 7, "deadline": "11:30",
                     "captured_at": day[:4]+"-"+day[4:6]+"-"+day[6:]+"T11:00:00+09:00"},
            "boats": [
                {"lane": c, "course": c, "racer_id": str(4000+c),
                 "name": "テスト", "avg_st": .15+c/100, "motor_top2_rate": 30+c*3,
                 "motor_number": c, "exhibition_time": 6.7+c/100,
                 "exhibition_st": .06+c/100}
                for c in range(1, 7)],
            "source": {"provider": "synthetic_fixture"},
            "environment": {"wind_speed": 5, "wind_direction": None,
                            "wave_cm": 8,
                            "tide": {"available": True, "status": "estimate"}}}


class EngineTests(unittest.TestCase):
    def _analyze(self, code, day, **kw):
        return engine.analyze(fixture(code, day), venues_db=VENUE_STATS,
                              mode="replay", now="2026-10-27T12:00:00+09:00", **kw)

    def test_all_four_venues_and_six_lanes(self):
        for code, day in (("16","20261017"), ("03","20261017"),
                          ("23","20261018"), ("06","20261021")):
            with self.subTest(code=code):
                obj = self._analyze(code, day)
                self.assertEqual(len(obj["lane_audits"]), 6)
                self.assertEqual(len(obj["virtual_card"]), 10)
                self.assertEqual(len(set(x["combination"] for x in obj["virtual_card"])), 10)
                self.assertFalse(obj["probabilities_calibrated"])
                self.assertEqual(obj["stake_yen"], 1000)

    def test_future_venues_do_not_start_early(self):
        for code in ("23","06"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                self._analyze(code,"20261017")

    def test_freshwater_tide_excluded_even_if_supplied(self):
        karatsu = self._analyze("23","20261018")
        self.assertIsNone(karatsu["environment"]["tide"])
        self.assertFalse(karatsu["tide_eligible"])
        for row in karatsu["lane_audits"]:
            self.assertEqual(row["components"]["tidal_conditions"]["status"],
                             "freshwater_excluded")
        sea = self._analyze("16","20261017")
        self.assertTrue(sea["tide_eligible"])
        self.assertIsNotNone(sea["environment"]["tide"])

    def test_unvalidated_wind_tide_wave_do_not_change_scores(self):
        a = fixture()
        b = fixture()
        b["environment"].update({"wind_speed": 9, "wave_cm": 20, "tide": {"available": False}})
        x = engine.analyze(a, venues_db=VENUE_STATS, mode="replay",
                           now="2026-10-27T12:00:00+09:00")
        y = engine.analyze(b, venues_db=VENUE_STATS, mode="replay",
                           now="2026-10-27T12:00:00+09:00")
        self.assertEqual([r["score"] for r in x["lane_audits"]],
                         [r["score"] for r in y["lane_audits"]])

    def test_conditional_only_with_history_and_holdout(self):
        x = fixture()
        x["environment"]["validated_buckets"] = {"wind": "headwind_5"}
        effect = {"wind": [{"course": 2, "observed_bucket": "headwind_5",
                            "sample_races": 500, "training_end": "2026-10-10",
                            "validated_at": "2026-10-14",
                            "validation_status": "holdout_passed",
                            "excess_log_score": .14, "evidence_id": "synthetic"}]}
        predicted = engine.analyze(x, venues_db=VENUE_STATS, conditioned=effect,
                                   mode="replay", now="2026-10-27T12:00:00+09:00")
        matched = [l for l in predicted["lane_audits"] if l["course"] == 2][0]
        self.assertGreater(matched["components"]["wind_conditions"]["adjustment"], 0)
        effect["wind"][0]["sample_races"] = 12
        not_enough = engine.analyze(x, venues_db=VENUE_STATS, conditioned=effect,
                                    mode="replay", now="2026-10-27T12:00:00+09:00")
        self.assertEqual(not_enough["lane_audits"][1]["components"]["wind_conditions"]["adjustment"],0)

    def test_missing_course_prior_no_invented_card(self):
        x = engine.analyze(fixture(), mode="replay", now="2026-10-27T12:00:00+09:00")
        self.assertEqual(x["virtual_card"], [])
        self.assertEqual(x["card_status"], "missing_course_prior")

    def test_frozen_datetime_guard(self):
        with self.assertRaises(ValueError):
            engine.analyze(fixture(), venues_db=VENUE_STATS, mode="live",
                           now="2026-10-17T12:00:00+09:00")


class FakeOfficial:
    def parse_racelist_boats(self, day, jcd, rno):
        return [{"lane": i, "racer_id": str(4000+i), "name": "x",
                 "avg_st": .15, "motor_top2_rate": 40, "motor_number": i}
                for i in range(1,7)]

    def official_url(self, *args):
        return "https://www.boatrace.jp/owpc/pc/race/beforeinfo"

    def fetch(self, url):
        return "<html>fake preview</html>"

    def parse_beforeinfo(self, html):
        return {"entry_observed": True, "exhibition_count": 6, "wind_speed": 4,
                "wave_cm": 3, "boats": {
                     i: {"predicted_course": i, "exhibition_time": 6.7+i/100}
                     for i in range(1,7)}}

    def deadlines(self, day, code):
        return ["10:25"]


class FakeTide:
    @staticmethod
    def get_tide_context(*args):
        return {"applicable": True, "available": True, "status": "estimated"}


class CollectorTests(unittest.TestCase):
    def test_locally_frozen_then_no_overwrite(self):
        time = datetime(2026,10,17,10,0,tzinfo=JST)
        with TemporaryDirectory() as tmp:
            args = ("20261017","16",1,"10:25",tmp)
            result=run.collect_race(*args,clock=lambda:time,official=FakeOfficial(),
                                    tide_source=FakeTide(),venue_stats=VENUE_STATS)
            self.assertEqual(result["status"],"locally_frozen_uncheckpointed")
            self.assertTrue((Path(tmp)/"forecasts/20261017/20261017_16_01.json").exists())
            self.assertEqual(run.collect_race(*args,clock=lambda:time,official=FakeOfficial(),
                                              venue_stats=VENUE_STATS)["status"],"already_frozen")

    def test_collector_rejects_late_forecast(self):
        time = datetime(2026,10,17,10,24,tzinfo=JST)
        with TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            run.collect_race("20261017","16",1,"10:25",tmp,
                             clock=lambda: time,official=FakeOfficial(),
                             venue_stats=VENUE_STATS)

    def test_schedule_has_launch_gate(self):
        moment=datetime(2026,10,17,10,0,tzinfo=JST)
        events,errors=run.schedule("20261017",official=FakeOfficial(),clock=lambda:moment)
        self.assertEqual({item[1] for item in events},{"16","03"})
        self.assertEqual(errors,[])

    def test_invalid_receipt_does_not_confirm(self):
        moment=datetime(2026,10,17,10,0,tzinfo=JST)
        with TemporaryDirectory() as tmp:
            run.collect_race("20261017","16",1,"10:25",tmp,clock=lambda:moment,
                             official=FakeOfficial(),tide_source=FakeTide(),
                             venue_stats=VENUE_STATS)
            with self.assertRaises(ValueError):
                run.verify_commit(tmp,"a"*40,git_show=lambda *_:"{}",
                                  confirmed_at=moment+timedelta(minutes=5))


if __name__ == "__main__":
    unittest.main()
