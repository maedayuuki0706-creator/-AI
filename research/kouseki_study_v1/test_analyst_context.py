import json
import tempfile
import unittest
from pathlib import Path
from analyst_context import build_context, pre_race_exhibition, read_history


def race(day, number=1, method="まくり", settled=True):
    # Frame and actual course differ. Winner is frame 3, actual course 4.
    courses = [1, 2, 4, 3, 5, 6]
    finishes = [3, 5, 1, 6, 2, 4]
    return {"day":day,"jcd":"08","rno":number,"settled":settled,
            "rows":[{"lane":i,"racer_id":str(4000+i),"actual_course":courses[i-1],
                     "finish":finishes[i-1],"method":method,"exhibition_course":i,
                     "exhibition_time":6.7+i/100,"wind_m":2,"wave_cm":1}
                    for i in range(1,7)]}


class AnalystContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.target = race("20261103")
    def tearDown(self):
        self.tmp.cleanup()
    def put(self, r):
        p=self.root/r["day"]/f'{r["jcd"]}_{r["rno"]:02d}.json'
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(r),encoding="utf8")

    def test_actual_course_not_frame_and_no_future(self):
        self.put(race("20261102"))
        self.put(race("20261103"))
        self.put(race("20261104"))
        v=build_context(self.root,self.target)
        self.assertEqual(v["history_audit"]["included_races"],1)
        self.assertEqual(v["venue"]["patterns"][3]["frequency"]["count"],1)
        self.assertEqual(v["venue"]["patterns"][3]["second_third_course_counts"],[{"courses":[5,1],"count":1}])
        self.assertEqual(v["racers"][2]["courses"][3]["national"]["winning_methods"]["まくり"]["count"],1)

    def test_missing_method_does_not_create_false_zero(self):
        self.put(race("20261102",method=None))
        v=build_context(self.root,self.target)
        self.assertEqual(v["venue"]["methods"]["known_method"],0)
        self.assertIsNone(v["venue"]["methods"]["method_rates"]["逃げ"]["pct"])
        self.assertEqual(v["history_audit"]["missing_method"],1)

    def test_incomplete_excluded(self):
        bad=race("20261102")
        bad["rows"][1]["finish"]=3
        self.put(bad)
        self.put(race("20261101",settled=False))
        rs,audit=read_history(self.root,"20261103")
        self.assertEqual(len(rs),0)
        self.assertEqual(audit["excluded_incomplete_or_invalid"],2)

    def test_target_result_does_not_change_context(self):
        self.put(race("20261102"))
        a=build_context(self.root,self.target)
        for b in self.target["rows"]:
            b.update(finish=99,actual_course=99,actual_st=0.99,method="差し")
        self.assertEqual(a,build_context(self.root,self.target))

    def test_missing_exhibition_and_inconsistent_weather(self):
        self.target["rows"][0]["exhibition_time"]=None
        self.target["rows"][0]["wind_m"]=4
        v=pre_race_exhibition(self.target)
        self.assertIsNone(v["wind_m"])
        self.assertTrue(all(b["exhibition_rank"] is None for b in v["boats"]))

    def test_complete_exhibition_rank(self):
        v=pre_race_exhibition(self.target)
        self.assertEqual([b["exhibition_rank"] for b in v["boats"]],list(range(1,7)))
        self.assertEqual(v["wind_m"],2)


if __name__=="__main__":
    unittest.main()
