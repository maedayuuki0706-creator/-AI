import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from . import core
from .runner import parse_result, collect_source
from .sheets import payloads

def fixture():
    # Synthetic fixtures are only used locally, never in user performance logs.
    rows=[{'combination':c,'probability':1/120,'odds':168} for c in core.COMBINATIONS]
    model={'trifecta':rows,'heads':{str(i):1/6 for i in range(1,7)},'main_picks':['1-2-3'],'cover_picks':[],'picks':['1-2-3'],'model_version':'test'}
    return {'key':'20261014_06_12','day':'20261014','deadline':'16:36','jcd':'06','rno':12,'venue':'浜名湖','created_at':'2026-10-14T16:15:00+09:00','models':{'prototype2':model,'prototype1':{'race_shape':{'best_attack_lane':4}}}}

class ResearchTest(unittest.TestCase):
    def test_ev_boundary_missing_and_percent(self):
        self.assertAlmostEqual(core.ev(.02,70),1.4)
        self.assertIsNone(core.ev(None,70));self.assertIsNone(core.ev(2,70));self.assertIsNone(core.ev(.02,-1))

    def test_full120_normalized_independent_models(self):
        fs=core.build_snapshots(fixture(),'a'*40,'2026-10-14T16:20:00+09:00')
        self.assertEqual(len(fs),6)
        for f in fs[:2]:
            self.assertEqual(len(f['tickets']),120)
            self.assertAlmostEqual(sum(t['probability'] for t in f['tickets']),1)
        self.assertNotEqual(fs[0]['tickets'],fs[1]['tickets'])
        self.assertTrue(all(f['availability']=='未取得／標本不足' for f in fs[2:]))

    def test_post_deadline_replay_and_no_late_features(self):
        fs=core.build_snapshots(fixture(),'a','2026-10-14T16:36:00+09:00',features={'observed_at':'2026-10-14T16:40:00+09:00','boats':{'1':{'avg_st':.01}}})
        self.assertTrue(all(f['cohort']=='過去再計算' and not f['features'] for f in fs))

    def test_receipt_required_for_live_metrics(self):
        f=core.build_snapshots(fixture(),'a','2026-10-14T16:20:00+09:00')[0]
        r=core.evaluate(f,{'status':'settled','payouts':{'1-2-3':6000},'refund_lanes':[]},'2026-10-14T16:50:00+09:00')
        self.assertEqual(core.metrics([f],[r],[]),[])
        late=core.seal_live(f,'2026-10-14T16:36:00+09:00');self.assertFalse(late['eligible_live'])
        ok=core.seal_live(f,'2026-10-14T16:21:00+09:00');self.assertTrue(ok['eligible_live'])
        m=next(x for x in core.metrics([f],[r],[ok]) if x['model']==f['model'] and x['group']=='総計' and x['threshold']==1.4)
        self.assertEqual(m['bets'],120);self.assertEqual(m['investment'],12000);self.assertEqual(m['payout'],6000);self.assertEqual(m['roi'],.5)

    def test_idempotent_forecast_and_result_never_rewrite(self):
        with tempfile.TemporaryDirectory() as root:
            src=fixture();off={'status':'settled','payouts':{'1-2-3':6000},'refund_lanes':[]}
            first=collect_source(src,'a','2026-10-14T17:00:00+09:00',root,replay=True,official=off)
            before={str(p):p.read_bytes() for p in Path(root).glob('**/*.json')}
            src['models']['prototype2']['trifecta'][0]['odds']=999
            again=collect_source(src,'b','2026-10-14T18:00:00+09:00',root,replay=True,official=off)
            self.assertEqual(first['new_records'],6);self.assertEqual(again['duplicates'],6)
            self.assertEqual(before,{str(p):p.read_bytes() for p in Path(root).glob('**/*.json')})

    def test_refund_exclusion_and_special(self):
        ticket={'combination':'1-2-3'}
        self.assertEqual(core.payoff(ticket,{'status':'settled','payouts':{},'refund_lanes':[2]}),(0,0,False))
        self.assertEqual(core.payoff(ticket,{'status':'void'}),(0,0,False))
        self.assertEqual(core.payoff(ticket,{'status':'special','special_per_100':70}),(100,70,False))

    def test_real_result_parser_structure(self):
        raw='<tbody><tr><td>3連単</td><td><span>1</span>-<span>2</span>-<span>4</span></td><td>¥4,120</td></tr></tbody>'
        self.assertEqual(parse_result(raw)['payouts'],{'1-2-4':4120})
        self.assertEqual(parse_result('<body>発売中</body>')['status'],'pending')

    def test_payloads_are_scoped_and_star_fixed(self):
        fs=core.build_snapshots(fixture(),'a','2026-10-14T17:00:00+09:00',replay=True)
        batches=payloads(fs,[],[])
        for batch in batches:
            for request in batch:self.assertEqual(len(request),1)
        self.assertTrue(all(t['mark']=='★EV1.4+' for t in fs[0]['tickets']))
        self.assertFalse(any('Webhook' in core.dumps(x) or 'discord' in core.dumps(x).lower() for x in batches))

if __name__=='__main__':unittest.main()
