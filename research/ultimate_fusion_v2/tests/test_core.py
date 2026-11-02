import copy
import tempfile
import unittest
from research.ultimate_fusion_v1 import engine as v1
from research.ultimate_fusion_v1.test_engine import race
from research.ultimate_fusion_v2.core import integrate,fit,predict,save_immutable

class IntegrationTest(unittest.TestCase):
    def setUp(self):
        self.s=v1.prepare_live(race())
        self.o={'race_id':self.s['race_id'],'lane':1,'racer_id':'4001','field':'lap_time',
                'value':36.1,'source_url':'https://www.boatrace-karatsu.jp/display',
                'retrieved_at':'2026-11-02T11:41:00+09:00','available_at':'2026-11-02T11:41:00+09:00',
                'published_at':None}
    def test_missing_is_null(self):
        j=integrate(self.s,[]);self.assertIsNone(j['boats'][0]['lap_time'])
    def test_join_and_trace(self):
        j=integrate(self.s,[self.o]);self.assertEqual(j['boats'][0]['lap_time'],36.1);self.assertEqual(len(j['provenance']),1)
    def test_after_prediction_before_deadline_rejected(self):
        self.o['available_at']='2026-11-02T11:43:00+09:00'
        self.assertIsNone(integrate(self.s,[self.o])['boats'][0]['lap_time'])
    def test_identity_host_invalid_and_outcome(self):
        for patch in [{'racer_id':'9999'},{'race_id':'wrong'},{'source_url':'https://boatrace.jp.evil.test'}, {'field':'actual_st'}, {'value':float('inf')}]:
            o={**self.o,**patch}
            if patch.get('value')==float('inf'):
                with self.assertRaises(ValueError):integrate(self.s,[o])
            else:self.assertFalse(integrate(self.s,[o])['audit'][0]['accepted'])
    def test_motor_period_required(self):
        o={**self.o,'field':'motor_top2_rate','value':40,'motor_number':10}
        self.assertFalse(integrate(self.s,[o])['audit'][0]['accepted'])
        o['motor_cycle']='2026-05-01';self.assertTrue(integrate(self.s,[o])['audit'][0]['accepted'])
    def test_conflicts_do_not_choose_order(self):
        a={**self.o,'value':37}
        for obs in [[a,self.o],[self.o,a]]:self.assertIsNone(integrate(self.s,obs)['boats'][0]['lap_time'])
    def test_future_original_v1_closed(self):
        f={'race_id':self.s['race_id'],'status':'ok','rows':self.s['boats'],
           'acquisition':{'source_family':'venue_official_verified','retrieved_at':'2026-11-02T11:43:00+09:00','published_at':'2026-11-02T11:40:00+09:00'}}
        self.assertIsNone(v1.original_exhibition(f,self.s)['measurements'])
    def test_training_time_and_duplicates(self):
        past=race(day='20261101',with_results=True);past['settled_at']='2026-11-01T12:15:00+09:00'
        future=copy.deepcopy(past);future['rno']=2;future['settled_at']='2026-11-02T12:15:00+09:00'
        m=fit([past,past,future,race(with_results=True)],'20261102','23')
        self.assertEqual(m['training_races'],1)
    def test_predict_120_no_ev_reuse_six_paths(self):
        m=fit([],'20261102','23');r=predict(self.s,m,now=self.s['snapshot_at'])
        self.assertEqual(len(r['trifecta']),120);self.assertEqual(len(r['scenario']['lanes']),6)
        self.assertTrue(all(x['probability'] is None and x['expected_value'] is None for x in r['trifecta']))
        self.assertFalse(r['ready_for_betting']);self.assertEqual(len(r['research_picks']),10)
    def test_duplicate_entry_rejected(self):
        raw=race();raw['rows'][1]['exhibition_course']=1;s=v1.prepare_live(raw)
        with self.assertRaises(ValueError):predict(s,fit([],'20261102','23'),now=s['snapshot_at'])
    def test_tampering_and_stale_rejected(self):
        m=fit([],'20261102','23')
        with self.assertRaises(ValueError):predict(self.s,m,now='2026-11-02T11:50:00+09:00')
        self.s['boats'][0]['name']='changed'
        with self.assertRaises(ValueError):predict(self.s,m,now=self.s['snapshot_at'])
    def test_immutable_and_replay_namespace(self):
        r=predict(self.s,fit([],'20261102','23'),now=self.s['snapshot_at'],mode='replay')
        with tempfile.TemporaryDirectory() as d:
            p=save_immutable(r,d);self.assertEqual(p.parent.name,'replay');save_immutable(r,d)
            r['decision']='changed';r['sha256']=v1.digest({k:v for k,v in r.items() if k!='sha256'})
            with self.assertRaises(ValueError):save_immutable(r,d)

if __name__=='__main__':unittest.main()
