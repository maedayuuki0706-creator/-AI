import json
import tempfile
import unittest
from pathlib import Path
from analytics import build_report, summarize, wilson


def row(i,**kw):
    return {'lane':i,'racer_id':f'{4000+i}','name':f'選手{i}',
            'current_class':'A2','actual_course':kw.get('actual_course',i),
            'actual_st':kw.get('actual_st',0.10+i*0.01),
            'finish':kw.get('finish',i),'exhibition_course':kw.get('exhibition_course',i)}


class CourseStatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.archive=self.root/'data'
        self.target=self.root/'target.json'
        self.target.write_text(json.dumps({'day':'20261104','jcd':'07','rno':10,'rows':[row(i) for i in range(1,7)],'settled':True}),encoding='utf8')

    def tearDown(self):self.tmp.cleanup()

    def put(self,day,rno=1,venue='07',rows=None,settled=True):
        folder=self.archive/day;folder.mkdir(parents=True,exist_ok=True)
        (folder/f'{venue}_{rno:02d}.json').write_text(json.dumps({'day':day,'jcd':venue,'rno':rno,'rows':rows or [row(i) for i in range(1,7)],'settled':settled}),encoding='utf8')

    def test_only_prior_day_and_course_actual_not_lane(self):
        self.put('20261103',1,rows=[row(1,actual_course=2),row(2,actual_course=1)]+[row(i) for i in range(3,7)])
        self.put('20261104',1) # same day must NOT train
        self.put('20261105',1) # future must NOT train
        rep=build_report(self.archive,self.target)
        first=rep['racers'][0]
        self.assertEqual(first['courses'][0]['year_observed']['n'],0)
        self.assertEqual(first['courses'][1]['year_observed']['n'],1)
        self.assertEqual(first['courses'][1]['year_observed']['first_pct'],100)
        self.assertIsNone(first['ai_top3_probability'])

    def test_each_course_last_ten_runs_not_recent_ten_total(self):
        for d in range(1,14):
            rows=[row(i) for i in range(1,7)]
            self.put(f'202610{d:02d}',rows=rows)
        rep=build_report(self.archive,self.target)
        s=rep['racers'][0]['courses'][0]
        self.assertEqual(s['recent10']['n'],10)
        self.assertEqual(s['year_observed']['n'],13)
        self.assertEqual(s['recent10']['st_mean'],0.11)
        self.assertEqual(s['recent10']['first_pct'],100)
        self.assertEqual(s['recent10']['top3_pct'],100)

    def test_local_and_venue_average_are_separate(self):
        self.put('20261102',venue='07')
        self.put('20261103',venue='06')
        rep=build_report(self.archive,self.target)
        c=rep['racers'][0]['courses'][0]
        self.assertEqual(c['year_observed']['n'],2)
        self.assertEqual(c['local_year_observed']['n'],1)
        self.assertEqual(c['venue_course_benchmark']['n'],1)

    def test_no_settlement_no_bad_finish_no_st_infinite(self):
        self.put('20261102',settled=False)
        rs=[row(1,actual_st=-0.2)]+[row(i) for i in range(2,7)]
        rs[1]['finish']='F'
        self.put('20261103',rows=rs)
        rep=build_report(self.archive,self.target)
        self.assertEqual(rep['racers'][0]['courses'][0]['recent10']['n'],1)
        self.assertEqual(rep['racers'][0]['courses'][0]['recent10']['st_n'],0)
        self.assertEqual(rep['racers'][1]['courses'][1]['recent10']['n'],0)

    def test_points_are_basic_not_official_and_wilson(self):
        x=summarize([{'finish':1,'st':0.10},{'finish':3,'st':0.20}])
        self.assertEqual(x['win_rate_points_basic'],8)
        self.assertEqual(x['first_pct'],50)
        self.assertEqual(x['top3_pct'],100)
        self.assertEqual(x['st_fast_015_pct'],50)
        self.assertLess(wilson(10,10)[0],100)

    def test_missing_history_null_not_zero(self):
        rep=build_report(self.archive,self.target)
        c=rep['racers'][0]['courses'][0]['recent10']
        self.assertEqual(c['n'],0)
        self.assertIsNone(c['top3_pct'])
        self.assertFalse(rep['collection_coverage']['one_year_complete'])

if __name__=='__main__':unittest.main()
