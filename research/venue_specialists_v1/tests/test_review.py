import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from research.venue_specialists_v1 import engine, review

NOW = "2026-10-17T11:01:00+09:00"


def fixture():
    payload = {
        "meta": {"day": "20261017", "jcd": "16", "rno": 7, "deadline": "11:30",
                 "captured_at": "2026-10-17T11:00:00+09:00"},
        "boats": [
            {"lane": i, "course": i, "racer_id": str(5000+i),
             "avg_st": .15, "motor_top2_rate": 40,
             "exhibition_time": 6.7+i/100}
            for i in range(1,7)]}
    f = engine.analyze(payload, venues_db={"16":{"course_win":[55,14,12,10,7,2]}},
                       mode="live", now=NOW)
    receipt = {"race_id": f["race_id"],"digest":f["digest"],
               "status":"confirmed_before_deadline",
               "checked_at":"2026-10-17T11:02:00+09:00","commit_sha":"a"*40}
    return f, receipt


class PostmortemTests(unittest.TestCase):
    def test_grades_frozen_hit_only(self):
        f, rec=fixture()
        winner=f["virtual_card"][0]["combination"]
        out=review.evaluate(f,rec,{"status":"settled","payouts":{winner:2130},
                                   "refund_lanes":[]})
        self.assertEqual(out["status"],"graded")
        self.assertEqual(out["stake_yen"],1000)
        self.assertEqual(out["return_yen"],2130)
        self.assertTrue(out["hit"])
        self.assertFalse(out["scenario_mechanism_verified"])

    def test_marks_selection_miss_without_inventing_race_mechanism(self):
        f,rec=fixture()
        remaining = [f"{x}-{y}-{z}" for x in range(1,7) for y in range(1,7)
                     for z in range(1,7) if len({x,y,z})==3 and
                     f"{x}-{y}-{z}" not in [p["combination"] for p in f["virtual_card"]]]
        out=review.evaluate(f,rec,{"status":"settled","payouts":{remaining[-1]:10200},
                                   "refund_lanes":[]})
        self.assertFalse(out["hit"])
        self.assertIn(out["selection"],("head_not_selected",
                "second_not_selected_given_head","third_not_selected_given_head_and_second"))

    def test_refund_excluded(self):
        f,rec=fixture()
        out=review.evaluate(f,rec,{"status":"settled","payouts":{"1-2-3":800},
                                   "refund_lanes":[1]})
        self.assertEqual(out["status"],"excluded")
        self.assertIsNone(out["return_yen"])

    def test_bad_receipt_and_late_checkpoint_refused(self):
        f,rec=fixture()
        res={"status":"settled","payouts":{"1-2-3":800},"refund_lanes":[]}
        rec["digest"]="changed"
        with self.assertRaises(ValueError):
            review.evaluate(f,rec,res)
        rec["digest"]=f["digest"]
        rec["checked_at"]="2026-10-17T11:31:00+09:00"
        with self.assertRaises(ValueError):
            review.evaluate(f,rec,res)

    def test_summary_counted_from_graded_only(self):
        f,rec=fixture()
        winner=f["virtual_card"][0]["combination"]
        first=review.evaluate(f,rec,{"status":"settled","payouts":{winner:1900},"refund_lanes":[]})
        with TemporaryDirectory() as tmp:
            dest=Path(tmp)/"reviews/20261017/test.json"
            dest.parent.mkdir(parents=True)
            import json
            dest.write_text(json.dumps(first),encoding="utf-8")
            stats=review.summarize(tmp,"20261017")
            self.assertEqual(stats["venues"]["16"]["graded"],1)
            self.assertEqual(stats["venues"]["16"]["roi_pct"],190.0)


if __name__=="__main__": unittest.main()
