import copy
import unittest
from research.scenario_v1.scenario_research_v1 import generate, review

META={"day":"20261016","jcd":"06","rno":7,"deadline":"19:00","captured_at":"2026-10-16T18:50:00+09:00"}
OFFICIAL={"inputs":[{"lane":i,"racer_id":str(4000+i),"avg_st":0.12+i*.01,"exhibition_st":0.15,"motor_top2_rate":40} for i in range(1,7)], "preview":{"wind_speed":5,"wave_cm":10}}

class ScenarioTests(unittest.TestCase):
    def test_six_heads_and_no_probabilities(self):
        record=generate(OFFICIAL,META)
        self.assertEqual([r['lane'] for r in record['lanes']],list(range(1,7)))
        self.assertTrue(all(r['hypotheses'] for r in record['lanes']))
        self.assertTrue(all(h['trifecta_probability'] is None for r in record['lanes'] for h in r['hypotheses']))
        self.assertEqual(record['status'],'research_only')
        self.assertEqual(record['meta']['race_id'],'20261016_06_07')
        self.assertTrue(all(len(h['reactions'])==5 for r in record['lanes'] for h in r['hypotheses']))
    def test_entry_changes_course_and_scenarios(self):
        snap=copy.deepcopy(OFFICIAL)
        for row,course in zip(snap['inputs'],[1,2,3,5,6,4]):row['predicted_course']=course
        got=generate(snap,META)
        self.assertEqual(got['lanes'][5]['predicted_course'],4)
        self.assertIn('差し',[x['tactic'] for x in got['lanes'][5]['hypotheses']])
    def test_bad_snapshot_rejected(self):
        for field,value in [('finish',1),('actual_st',0.09),('payout',20000)]:
            snap=copy.deepcopy(OFFICIAL);snap['inputs'][0][field]=value
            with self.assertRaises(ValueError):generate(snap,META)
        snap=copy.deepcopy(OFFICIAL);snap['inputs'][0]['motor_top2_rate']='nan'
        self.assertEqual(generate(snap,META)['lanes'][0]['evidence'][0]['source_field'],'avg_st')
        snap=copy.deepcopy(OFFICIAL);snap['inputs'][1]['lane']=1
        with self.assertRaises(ValueError):generate(snap,META)
        with self.assertRaises(ValueError):generate(OFFICIAL,{**META,'captured_at':'2026-10-16T19:01:00+09:00'})
    def test_frozen_remains_unchanged_on_review(self):
        snap=generate(OFFICIAL,META);original=copy.deepcopy(snap)
        result=review(snap,{"race_id":"20261016_06_07","status":"settled","trifecta":"3-1-4"})
        self.assertEqual(snap,original)
        self.assertTrue(result['head_covered'])
        self.assertEqual(result['actual_trifecta'],'3-1-4')
        self.assertEqual(review(snap,{"race_id":"20261016_06_07","status":"accident"})['status'],'excluded')
        with self.assertRaises(ValueError):review(snap,{"race_id":"20261016_06_08","status":"settled","trifecta":"3-1-4"})

if __name__=='__main__':unittest.main()
