import json
import tempfile
import unittest
from pathlib import Path
from coverage_audit import coverage

class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.cards=self.root/"cards"; self.cards.mkdir()
        self.archive=self.root/"archive"; self.archive.mkdir()
        self.day="20261119"
    def tearDown(self):
        self.tmp.cleanup()
    def card(self,complete=True):
        data={"day":self.day,"complete":complete,"races":{"08:1":{"jcd":"08","rno":1},"08:2":{"jcd":"08","rno":2}}}
        (self.cards/f"{self.day}.json").write_text(json.dumps(data),encoding="utf8")
    def race(self,n=1,settled=True,missing=False,abnormal=False):
        rows=[{"lane":i,"racer_id":str(4000+i),"finish":i,"actual_course":i,"actual_st":.15,
               "exhibition_time":6.8,"wind_m":2,"wave_cm":1,"method":"逃げ"} for i in range(1,7)]
        if missing: rows[3]["exhibition_time"]=None
        if abnormal: rows[4]["finish"]="F"
        p=self.archive/self.day/f"08_{n:02}.json";p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps({"day":self.day,"jcd":"08","rno":n,"settled":settled,"rows":rows}),encoding="utf8")
    def report(self):
        return coverage(self.cards,self.archive,self.day,self.day)
    def test_unknown_manifest_never_zero_schedule(self):
        self.assertIsNone(self.report()["days"][0]["expected"])
        self.card(False)
        self.assertEqual(self.report()["totals"]["unknown_manifest_days"],1)
    def test_missing_race_and_field(self):
        self.card(); self.race(missing=True)
        r=self.report()
        self.assertEqual(r["totals"]["expected"],2)
        self.assertEqual(r["totals"]["missing_archive"],1)
        self.assertEqual(r["days"][0]["races"][0]["issues"],[{"field":"exhibition_time","lanes":[4]}])
        self.assertFalse(r["clean_normal_result_subset"])
        self.assertEqual(len(r["all_24_venues"]),24)
    def test_abnormal_and_unsettled_distinct(self):
        self.card(); self.race(abnormal=True); self.race(2,settled=False)
        r=self.report()["totals"]
        self.assertEqual(r["abnormal_or_incomplete_result"],1)
        self.assertEqual(r["unsettled_or_unverified"],1)
    def test_all_normal_and_unexpected(self):
        self.card();self.race();self.race(2)
        self.assertTrue(self.report()["clean_normal_result_subset"])
        self.race(3)
        self.assertEqual(self.report()["days"][0]["unexpected_files"],["08_03"])
        self.assertFalse(self.report()["clean_normal_result_subset"])

if __name__=="__main__": unittest.main()
