import copy,json,tempfile,unittest
import subprocess
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch
from research.edogawa_phase2 import acquire,study,model,shadow,validate
from research.scenario_v2 import engine as scenario

def snapshot():
    return {'meta':{'day':'20261019','jcd':'03','rno':1,'deadline':'11:10','captured_at':'2026-10-19T11:00:00+09:00'},
        'boats':[{'lane':i,'course':i,'racer_id':str(4000+i),'name':f'試験選手{i}','avg_st':.12+i*.01,'exhibition_time':6.7+i*.01,'motor_top2_rate':30} for i in range(1,7)],'source':{},'environment':{'wind_speed':3}}
def training():
    return [{'race_id':'2026063003'+f'{i:02}','date':'2026-06-30','normal_eligible':True,'official_verified':True,'method':'逃げ','boats':[{'lane':j,'course':j,'finish':j} for j in range(1,7)]} for i in range(1,13)]
def fitted():return model.fit(training())
NOW='2026-10-19T11:01:00+09:00'
def at(stamp):return lambda:datetime.fromisoformat(stamp)

class Phase2(unittest.TestCase):
    def test_fixed_training_excludes_future_and_mirror(self):
        rs=training();rs.append({**rs[0],'date':'2026-07-01'});rs.append({**rs[0],'official_verified':False})
        self.assertEqual(model.fit(rs)['training_n'],12)
    def test_empty_official_training_rejected(self):
        with self.assertRaises(ValueError):model.fit([])
    def test_model_tamper_rejected(self):
        f=fitted();f['training_n']+=1
        with self.assertRaises(ValueError):model.course_scores(f,'A')
    def test_C_is_blocked(self):
        with self.assertRaises(ValueError):model.predict(snapshot(),fitted(),'C',mode='replay',now=NOW)
    def test_A_B_ten_unique_and_six_paths(self):
        for v in ['A','B']:
            p=model.predict(snapshot(),fitted(),v,mode='replay',now=NOW)
            self.assertEqual(len({x['combination'] for x in p['virtual_card']}),10)
            self.assertEqual(len(p['lanes']),6)
            self.assertTrue(all(x['win_paths'] and x['loss_paths'] for x in p['lanes']))
    def test_five_reactions_and_separate_attack_origin(self):
        p=model.predict(snapshot(),fitted(),'B',mode='replay',now=NOW)
        hs=[h for b in p['lanes'] for h in b['hypotheses']]
        self.assertTrue(all(len(h['reactions'])==5 for h in hs))
        self.assertTrue(any(h['winner_lane']!=h['attack_origin_lane'] for h in hs))
    def test_replay_never_prospective(self):
        self.assertEqual(model.predict(snapshot(),fitted(),'B',mode='replay',now=NOW)['status'],'retrospective_replay')
    def test_nested_outcomes_rejected(self):
        for key in ['actual_st','method','trifecta','first']:
            s=snapshot();s['source']['nested']={key:'bad'}
            with self.assertRaises(ValueError):model.predict(s,fitted(),'A',mode='replay',now=NOW)
    def test_late_capture_no_original(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):shadow.capture(snapshot(),fitted(),d,clock=at('2026-10-19T11:11:00+09:00'),code_sha='a'*40)
            self.assertFalse(list(Path(d).rglob('*.json')))
    def test_incomplete_six_data(self):
        s=snapshot();s['boats'].pop()
        with self.assertRaises(ValueError):model.predict(s,fitted(),'A',mode='live',now=NOW)
    def test_exhibition_missing_capture_recorded_not_original(self):
        s=snapshot();s['boats'][2]['exhibition_time']=None
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):shadow.capture(s,fitted(),d,clock=at(NOW),code_sha='a'*40)
            self.assertFalse(list(Path(d).rglob('*.json')))
    def test_future_model_no_live_capture(self):
        f=fitted();f['fitted_at']='2026-10-20T00:00:00+09:00';f['digest']=scenario.digest({k:v for k,v in f.items() if k!='digest'})
        with self.assertRaises(ValueError):model.predict(snapshot(),f,'A',mode='live',now=NOW)
    def test_duplicate_and_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            f=fitted();a=shadow.capture(snapshot(),f,d,clock=at(NOW),code_sha='a'*40)
            b=shadow.capture(snapshot(),f,d,clock=at(NOW),code_sha='a'*40);self.assertEqual(a,b)
            s=snapshot();s['boats'][0]['avg_st']=.25
            with self.assertRaises(ValueError):shadow.capture(s,f,d,clock=at(NOW),code_sha='a'*40)
    def test_corrupt_original_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            a=shadow.capture(snapshot(),fitted(),d,clock=at(NOW),code_sha='a'*40)
            path=next(Path(d).rglob('*.json'));path.write_text('{}')
            with self.assertRaises(ValueError):shadow.capture(snapshot(),fitted(),d,clock=at(NOW),code_sha='a'*40)
    def test_receipt_remote_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            a=shadow.capture(snapshot(),fitted(),d,clock=at(NOW),code_sha='a'*40)
            with patch.object(shadow,'git',side_effect=['a'*40,'{}']):
                with self.assertRaises(ValueError):shadow.receipt(d,a,'a'*40,clock=at(NOW))
    def test_late_receipt_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            a=shadow.capture(snapshot(),fitted(),d,clock=at(NOW),code_sha='a'*40)
            with patch.object(shadow,'git',side_effect=['a'*40,json.dumps(a)]):
                r=shadow.receipt(d,a,'a'*40,clock=at('2026-10-19T11:11:00+09:00'))
            self.assertEqual(r['status'],'late_receipt_excluded')
    def test_write_once_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';acquire.put(p,b'a');acquire.put(p,b'a')
            with self.assertRaises(ValueError):acquire.put(p,b'b')
    def test_review_without_receipt_forbidden(self):
        with tempfile.TemporaryDirectory() as d:
            a=shadow.capture(snapshot(),fitted(),d,clock=at(NOW),code_sha='a'*40)
            with self.assertRaises(ValueError):shadow.review_bundle(a,{},d)
    def test_unknown_money_and_video_stay_unknown(self):
        p=model.predict(snapshot(),fitted(),'A',mode='replay',now=NOW)
        r=model.evaluate(p,{'race_id':p['meta']['race_id'],'observed_at':'2026-10-19T11:20:00+09:00','trifecta':'1-2-3','payout_per_100':500,'method':'逃げ'})
        self.assertIsNone(r['return_yen']);self.assertIsNone(r['roi']);self.assertIsNone(r['attack_origin_correct'])
    def test_explicit_odds_and_refund_required(self):
        p=model.predict(snapshot(),fitted(),'A',mode='replay',now=NOW)
        result={'race_id':p['meta']['race_id'],'observed_at':'2026-10-19T11:20:00+09:00','trifecta':p['primary_prediction'],'payout_per_100':500,'method':'逃げ','normal_verified':True,'refund_lanes':[]}
        r=model.evaluate(p,result);self.assertEqual(r['return_yen'],500);self.assertIsNone(r['roi'])
        result['odds_snapshot']={'verified':True};r=model.evaluate(p,result);self.assertEqual(r['roi'],.5);self.assertTrue(r['torigami'])
    def test_day_uncertainty_cannot_claim_improvement(self):
        s=validate.paired_uncertainty([{'日付':'20261018','改良的中':1,'既存的中':0}]*12)
        self.assertIn('判定不能',s['status'])
    def test_split_boundaries(self):
        self.assertEqual([study.split(x) for x in ['2026-06-30','2026-07-01','2026-09-30','2026-10-01']],['学習','検証','検証','最終評価'])
    def test_official_priority_and_abnormal_not_filled(self):
        orig={'race_id':'202510180301','date':'2025-10-18','data_source':'mirror','sha256':'x','first':'1',**{k:'' for k in study.POSITIONS[1:]}}
        off={**orig,'first':2,'sha256':'a','boats':[{'lane':i,'course':i,'finish':1 if i==2 else None,'status':'01' if i==2 else 'F1'} for i in range(1,7)]}
        rs,ds,missing,dups,extra=study.audit([orig],[{'races':[off]}]);self.assertEqual(rs[0]['first'],2);self.assertFalse(rs[0]['normal_eligible']);self.assertTrue(rs[0]['abnormal_confirmed']);self.assertTrue(ds)
    def test_wilson_zero_and_small(self):
        self.assertEqual(study.wilson(0,0),(None,None));lo,hi=study.wilson(1,1);self.assertLess(lo,.5);self.assertAlmostEqual(hi,1)
    def test_plain_F_official_row_and_fullwidth_payout(self):
        txt='03KBGN\n   1R  試験 H1800m 晴 風 北 3m 波 5cm\n ﾚｰｽﾀｲﾑ 逃げ\n'
        for i in range(1,7):
            status='F' if i==6 else f'{i:02}';st='F0.01' if i==6 else '0.12'
            txt+=f'  {status}  {i} {4000+i} 試験選手 {i+10}  {i+20}  6.90   {i}    {st}     1.51.2\n'
        txt+=' ３連単 1-2-3 500 人気 1\n03KEND\n'
        rows=acquire.parse_text('2026-06-30',txt,'https://official.example.invalid','a'*64,'2026-10-18T00:00:00+00:00')
        self.assertEqual(len(rows[0]['boats']),6);self.assertEqual(rows[0]['boats'][-1]['status'],'F');self.assertEqual(rows[0]['boats'][-1]['actual_st'],-.01);self.assertEqual(rows[0]['payout_per_100'],500)
    def test_real_bare_git_capture_receipt_result_separation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);remote=root/'remote.git';state=root/'state'
            def cmd(*xs):return subprocess.check_output(['git',*map(str,xs)],stderr=subprocess.PIPE,text=True).strip()
            cmd('init','--bare',remote);cmd('clone',remote,state)
            cmd('-C',state,'config','user.name','Research Test');cmd('-C',state,'config','user.email','test@example.invalid')
            (state/'seed.txt').write_text('fixture only');cmd('-C',state,'add','seed.txt');cmd('-C',state,'commit','-m','seed')
            cmd('-C',state,'push','origin','HEAD:refs/heads/'+shadow.BRANCH)
            a=shadow.capture(snapshot(),fitted(),state,clock=at(NOW),code_sha='a'*40)
            original=next((state/shadow.PREFIX/'forecasts').rglob('*.json'));before=original.read_bytes()
            sha=shadow.persist(state);rec=shadow.receipt(state,a,sha,clock=at('2026-10-19T11:02:00+09:00'));shadow.persist(state)
            result={'race_id':a['race_id'],'observed_at':'2026-10-19T11:20:00+09:00','trifecta':'1-2-3','method':'逃げ','payout_per_100':500,'refund_lanes':[],'normal_verified':True}
            shadow.review_bundle(a,result,state,confirmed_receipt=rec);shadow.persist(state)
            self.assertEqual(before,original.read_bytes())
            self.assertTrue((state/shadow.PREFIX/'results/20261019/20261019_03_01.json').exists())
            self.assertEqual(cmd('--git-dir',remote,'show',sha+':'+str(original.relative_to(state))),before.decode().strip())
            (state/'seed.txt').write_text('must not push')
            with self.assertRaises(ValueError):shadow.persist(state)

if __name__=='__main__':unittest.main()
