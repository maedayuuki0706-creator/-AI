import copy,json,tempfile,subprocess,unittest
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from research.ultimate_fusion_v1 import engine as e
from research.ultimate_fusion_v1.test_engine import race
from research.ultimate_fusion_v2.capture import live,checkpoint,review

def fixture():
    now='2026-11-02T11:40:00+09:00'
    timing='締切予定時刻 '+' '.join(['12:00']*12)
    odds='<tbody class="is-p3-0">'+''.join(f'<td class="oddsPoint">{i+2}.0</td>' for i in range(120))+'</tbody>'
    pages={}
    for kind in ('racelist','beforeinfo','odds3t'):
        html=timing+(odds if kind=='odds3t' else '')
        pages[kind]={'url':live.url(kind,'20261102','23',7),'html':html,'body_sha256':sha256(html.encode()).hexdigest(),
                     'requested_at':now,'retrieved_at':now,'published_at':None}
    boats=[{**b,'avg_st':.15,'win_rate':6.,'local_win_rate':5.} for b in race()['rows']]
    preview={'exhibition_count':6,'entry_observed':True,'boats':{b['lane']:{**b,'predicted_course':b['lane'],'exhibition_st_timing':.1} for b in boats}}
    history=[]
    for day in ('20261028','20261029','20261030'):
        for rno in range(1,13):
            r=race(day=day,rno=rno,with_results=True);r['settled_at']=f'{day[:4]}-{day[4:6]}-{day[6:]}T12:30:00+09:00';history.append(r)
    return now,pages,boats,preview,history

def bundle():
    now,pages,boats,preview,history=fixture()
    with patch.object(live.parsers,'parse_racelist_boats',return_value=boats),patch.object(live.parsers,'parse_beforeinfo',return_value=preview):
        return live.assemble('20261102','23',7,pages,history,now)

def receipt(b,now='2026-11-02T11:41:00+09:00'):
    r={'race_id':b['race_id'],'bundle_sha256':b['sha256'],'report_sha256':b['report']['sha256'],
       'status':'confirmed_predeadline','observed_remote_at':now,'remote_commit':'a'*40}
    r['sha256']=e.digest(r);return r

class Forward(unittest.TestCase):
    def test_real_official_pages_parse_but_remain_postdeadline(self):
        root=Path(__file__).parents[1]/'reports/20261102_forward'
        pages={k:json.loads((root/(k+'_receipt.json')).read_text()) for k in ('racelist','beforeinfo','odds3t')}
        self.assertEqual(len(live.parsers.parse_racelist_boats(pages['racelist']['html'])),6)
        self.assertEqual(live.parsers.parse_beforeinfo(pages['beforeinfo']['html'])['exhibition_count'],6)
        self.assertEqual(len(live.parsers.parse_odds(pages['odds3t']['html'])),120)
        with self.assertRaisesRegex(ValueError,'too_late_to_predict'):
            live.assemble('20261102','24',12,pages,[],pages['odds3t']['retrieved_at'])
    def test_odds_all_120_mapping(self):
        _,p,*_=fixture();o=live.parsers.parse_odds(p['odds3t']['html'])
        self.assertEqual(set(o),set(e.COMBOS));self.assertEqual(o['1-2-3'],2);self.assertEqual(o['6-5-4'],121)
    def test_complete_bundle_preserves_raw_and_never_ev(self):
        b=bundle();checkpoint.verify_bundle(b)
        self.assertEqual(len(b['pages']),3);self.assertEqual(b['report']['features']['boats'][0]['national_win_rate'],6)
        self.assertTrue(all(x['official_odds']>=1 and x['expected_value'] is None for x in b['report']['trifecta']))
    def test_forged_race_or_raw_body_or_future_rejected(self):
        now,pages,boats,preview,history=fixture()
        for patchvalue in [{'url':live.url('odds3t','20261102','24',7)},{'html':'changed'},{'retrieved_at':'2026-11-02T11:41:00+09:00'}]:
            p=copy.deepcopy(pages);p['odds3t'].update(patchvalue)
            with self.assertRaises(ValueError):live.assemble('20261102','23',7,p,history,now)
    def test_late_capture_rejected(self):
        _,p,_,_,h=fixture()
        with self.assertRaises(ValueError):live.assemble('20261102','23',7,p,h,'2026-11-02T12:01:00+09:00')
    def test_missing_odds_fail_closed(self):
        now,p,boats,preview,h=fixture();p['odds3t']['html']=p['odds3t']['html'].replace('oddsPoint','missing',1);p['odds3t']['body_sha256']=sha256(p['odds3t']['html'].encode()).hexdigest()
        with patch.object(live.parsers,'parse_racelist_boats',return_value=boats),patch.object(live.parsers,'parse_beforeinfo',return_value=preview):
            with self.assertRaisesRegex(ValueError,'incomplete_official_odds'):live.assemble('20261102','23',7,p,h,now)
    def test_immutable_bundle(self):
        b=bundle()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'b.json';live.freeze(p,b);live.freeze(p,b)
            with self.assertRaises(ValueError):live.freeze(p,{**b,'status':'different'})
    def test_write_scope(self):
        checkpoint.allowed('A\t'+live.PREFIX+'/captures/a.json')
        for s in ['M\t'+live.PREFIX+'/a.json','D\t'+live.PREFIX+'/a.json','A\tdata/prediction_log.jsonl']:
            with self.assertRaises(ValueError):checkpoint.allowed(s)
    def test_receipt_required_and_late_excluded(self):
        b=bundle();r={'race_id':b['race_id'],'status':'settled','payouts':{'1-2-3':1000}}
        for t in ('2026-11-02T11:39:00+09:00','2026-11-02T12:01:00+09:00'):
            with self.assertRaises(ValueError):review.review(b,receipt(b,t),r,'2026-11-02T12:10:00+09:00')
    def test_results_refunds_and_no_leak(self):
        b=bundle();r={'race_id':b['race_id'],'status':'settled','payouts':{'1-2-3':1000}}
        before=e.digest(b);out=review.review(b,receipt(b),r,'2026-11-02T12:10:00+09:00')
        self.assertEqual(e.digest(b),before);self.assertEqual(out['models']['fusion']['stake_yen'],1000)
        r['refund_lanes']=[1];self.assertEqual(review.review(b,receipt(b),r,'2026-11-02T12:10:00+09:00')['status'],'excluded_or_pending')
    def test_remote_roundtrip_and_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);remote=root/'remote.git';state=root/'state'
            def run(*args):return subprocess.check_output(['git',*map(str,args)],stderr=subprocess.DEVNULL,text=True)
            run('init','--bare',remote);run('init','-b',checkpoint.BRANCH,state)
            run('-C',state,'config','user.name','test');run('-C',state,'config','user.email','test@example.test');run('-C',state,'remote','add','origin',remote)
            b=bundle();p=state/live.PREFIX/'captures'/'20261102'/(b['race_id']+'.json');live.freeze(p,b)
            receipts=checkpoint.persist(state,clock=lambda:datetime.fromisoformat('2026-11-02T11:41:00+09:00'))
            self.assertEqual(receipts[0]['status'],'confirmed_predeadline')
            self.assertEqual(checkpoint.persist(state,clock=lambda:datetime.fromisoformat('2026-11-02T11:42:00+09:00')),[])
            self.assertIn(b['race_id'],run('--git-dir',remote,'show',checkpoint.BRANCH+':'+live.PREFIX+'/receipts/'+b['race_id']+'.json'))

if __name__=='__main__':unittest.main()
