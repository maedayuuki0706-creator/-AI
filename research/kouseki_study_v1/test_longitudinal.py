import sqlite3
import unittest
from analytics import is_six
from analyst_context import rate
from longitudinal import follower, similar, scenarios
from desk import exhibit
from test_analyst_context import race


class ResearchDeskTests(unittest.TestCase):
    def test_follower_is_conditional_on_course_method_and_epoch(self):
        rows=[dict(attacker=4,second=s,holdout=h,deciding_method=m,n=n) for s,h,m,n in
              [(5,1,'まくり',2),(1,1,'まくり',8),(5,0,'まくり',100),(5,1,'抜き',11)]]
        self.assertEqual(follower(rows,1,True),rate(2,10))
        self.assertEqual(follower(rows,1,False),rate(11,11))

    def test_rank_colors_per_column_ties_missing(self):
        out=exhibit(['直線','一周'],[[1,2,2,3,4,5],[1,None,2,3,4,5]])
        self.assertEqual(out.count('class="r1"'),1)
        self.assertEqual(out.count('class="r2"'),2)
        self.assertEqual(out.count('class="rNone"'),6)

    def test_similar_uses_only_history_and_pre_race_target_fields(self):
        t=race('20261114'); prior=race('20261113')
        for r in [t,prior]:
            for b in r['rows']:b['current_class']='A1'
        prior.update(venue='08',race_no=1,method='差し')
        matches=similar([prior,dict(prior,day=t['day'])],t)
        self.assertEqual(len(matches),1);self.assertEqual(matches[0][0],0)
        for b in t['rows']: b.update(finish=0,actual_course=0,actual_st=9)
        self.assertEqual(similar([prior],t),matches)

    def test_invalid_lane_types(self):
        t=race('20261114');t['rows'][0]['lane']=True
        self.assertFalse(is_six(t['rows']))
