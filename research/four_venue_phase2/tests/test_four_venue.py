import copy,json,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from research.four_venue_phase2 import collect,model,shadow,resource_guard
from research.edogawa_phase2.tests.test_phase2 import snapshot,training,at,NOW
from research.scenario_v2 import engine as scenario

def fitted(j='03'):
    rows=training()
    for r in rows:r['race_id']=r['race_id'][:8]+j+r['race_id'][10:];r['venue_code']=j
    return model.fit(rows,j)

def snap(j='03'):
    r=snapshot();r['meta']['jcd']=j;return r

TEXT='''16KBGN
  1R 一般 H1800m 晴 風 北西 3m 波 5cm
 着 艇 登番 選手名 モーター ボート 展示 進入 ST ﾚｰｽﾀｲﾑ 差し
 01 2 4002 試験選手二 12 13 6.80 1 0.12 1.50.0
 02 1 4001 試験選手一 14 15 6.81 2 0.13 1.51.0
 03 3 4003 試験選手三 16 17 6.82 3 0.14 1.52.0
 04 4 4004 試験選手四 18 19 6.83 4 0.15 1.53.0
 05 5 4005 試験選手五 20 21 6.84 5 0.16 1.54.0
 06 6 4006 試験選手六 22 23 6.85 6 0.17 1.55.0
 ３連単 2-1-3 1500
16KEND
'''
META={'source_url':'https://www1.mbrace.or.jp/test.lzh','sha256':'a'*64,'observed_at':'2026-10-18T00:00:00Z'}

class FourVenue(unittest.TestCase):
    def test_official_adapter_preserves_identity_and_entry(self):
        rows,cov=collect.parse_venue('2026-10-17',TEXT,META,'16');r=rows[0]
        self.assertEqual(r['race_id'],'202610171601');self.assertEqual(r['first'],2)
        self.assertEqual(r['boats'][0]['course'],1);self.assertEqual(r['boats'][0]['lane'],2)
        self.assertEqual(r['sha256'],'a'*64);self.assertEqual(r['payout_per_100'],1500)
        self.assertEqual(cov['race_headers'],1);self.assertTrue(TEXT.startswith('16KBGN'))
    def test_missing_venue_section_no_fabricated_races(self):
        rows,cov=collect.parse_venue('2026-10-17',TEXT,META,'06')
        self.assertEqual(rows,[]);self.assertFalse(cov['section_present'])
    def test_F_is_status_not_fabricated_finish(self):
        txt=TEXT.replace('06 6 4006',' F 6 4006').replace('6 0.17','6 F0.01')
        rows,_=collect.parse_venue('2026-10-17',txt,META,'16');b=rows[0]['boats'][-1]
        self.assertIsNone(b['finish']);self.assertEqual(b['status'],'F');self.assertEqual(b['actual_st'],-.01)
    def test_unobserved_averageST_class_tide_remain_missing(self):
        rows,_=collect.parse_venue('2026-10-17',TEXT,META,'16')
        self.assertIsNone(rows[0]['tide']);self.assertIsNone(rows[0]['boats'][0]['average_st']);self.assertIsNone(rows[0]['boats'][0]['racer_class'])
    def test_each_venue_has_separate_training_and_six_paths(self):
        for j in collect.VENUES:
            f=fitted(j);self.assertEqual(f['training_n'],12)
            for v in ['A','B']:
                r=model.predict(snap(j),f,v,mode='replay',now=NOW)
                self.assertEqual(len(r['lanes']),6);self.assertEqual(len({x['combination'] for x in r['virtual_card']}),10)
                self.assertTrue(all(b['win_paths'] and b['loss_paths'] and b['alternative_scenarios'] for b in r['lanes']))
                self.assertEqual(len(r['not_selected']),110)
    def test_wrong_venue_model_rejected(self):
        with self.assertRaises(ValueError):model.predict(snap('23'),fitted('16'),'A',mode='replay',now=NOW)
    def test_cross_venue_training_rejected(self):
        f=fitted();f['training_race_ids'].append('202606301601');f['digest']=scenario.digest({k:v for k,v in f.items() if k!='digest'})
        with self.assertRaises(ValueError):model.check_model(f)
    def test_future_training_and_mirror_excluded(self):
        rs=training();rs+=[{**rs[0],'date':'2026-07-01'},{**rs[0],'official_verified':False}]
        self.assertEqual(model.fit(rs,'03')['training_n'],12)
    def test_C_blocked_all_venues(self):
        for j in collect.VENUES:
            with self.assertRaises(ValueError):model.predict(snap(j),fitted(j),'C',mode='replay',now=NOW)
    def test_postrace_labels_rejected(self):
        for key in ['actual_st','method','first','trifecta']:
            s=snap('06');s['source']['nested']={key:1}
            with self.assertRaises(ValueError):model.predict(s,fitted('06'),'B',mode='replay',now=NOW)
    def test_winner_and_attacker_distinct_and_five_reactions(self):
        r=model.predict(snap('23'),fitted('23'),'B',mode='replay',now=NOW)
        hs=[h for b in r['lanes'] for h in b['hypotheses']]
        self.assertTrue(any(h['winner_lane']!=h['attack_origin_lane'] for h in hs));self.assertTrue(all(len(h['reactions'])==5 for h in hs))
    def test_late_missing_exhibition_no_original(self):
        for s,now in [(snap(),'2026-10-19T11:11:00+09:00'),(snap(),NOW)]:
            if now==NOW:s['boats'][0]['exhibition_time']=None
            with tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError):shadow.capture(s,fitted(),d,clock=at(now),code_sha='b'*40)
                self.assertFalse(list(Path(d).rglob('*.json')))
    def test_duplicate_same_and_conflicting(self):
        with tempfile.TemporaryDirectory() as d:
            f=fitted();a=shadow.capture(snap(),f,d,clock=at(NOW),code_sha='b'*40)
            b=shadow.capture(snap(),f,d,clock=at(NOW),code_sha='b'*40);self.assertEqual(a,b)
            s=snap();s['boats'][0]['avg_st']=.3
            with self.assertRaises(ValueError):shadow.capture(s,f,d,clock=at(NOW),code_sha='b'*40)
    def test_unknown_finance_and_video(self):
        r=model.predict(snap('06'),fitted('06'),'A',mode='replay',now=NOW)
        ev=model.evaluate(r,{'race_id':r['meta']['race_id'],'observed_at':'2026-10-19T12:00:00+09:00','trifecta':'1-2-3','payout_per_100':500,'method':'逃げ'})
        self.assertIsNone(ev['roi']);self.assertIsNone(ev['return_yen']);self.assertIsNone(ev['attack_origin_correct'])
    def test_preflight_generates_nothing(self):
        for j in collect.VENUES:
            r=shadow.preflight(fitted(j));self.assertEqual(r['writes'],0);self.assertEqual(r['generated'],0);self.assertFalse(r['schedule_enabled'])
    def test_real_remote_receipt_and_separate_result(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);remote=root/'remote.git';state=root/'state'
            def run(*args):return subprocess.check_output(['git',*map(str,args)],stderr=subprocess.STDOUT,text=True).strip()
            run('init','--bare',remote);run('clone',remote,state);run('-C',state,'switch','-c',shadow.BRANCH)
            run('-C',state,'config','user.email','test@example.invalid');run('-C',state,'config','user.name','Research test')
            run('-C',state,'commit','--allow-empty','-m','init')
            b=shadow.capture(snap('16'),fitted('16'),state,clock=at(NOW),code_sha='b'*40)
            original=next((state/shadow.PREFIX/'forecasts').rglob('*.json')).read_bytes()
            sha=shadow.persist(state);rec=shadow.receipt(state,b,sha,clock=at(NOW));shadow.persist(state)
            self.assertEqual(rec['status'],'confirmed_before_deadline')
            result={'race_id':b['race_id'],'observed_at':'2026-10-19T12:00:00+09:00','trifecta':'1-2-3','payout_per_100':500,'method':'逃げ','normal_verified':True,'refund_lanes':[]}
            review=shadow.review_bundle(state,b,result,rec);shadow.persist(state)
            self.assertEqual(review['cohort'],'通常確認済');self.assertEqual(next((state/shadow.PREFIX/'forecasts').rglob('*.json')).read_bytes(),original)
            self.assertEqual(len(list((state/shadow.PREFIX/'results').rglob('*.json'))),1)
    def test_push_retry_retains_original(self):
        with tempfile.TemporaryDirectory() as d:
            b=shadow.capture(snap(),fitted(),d,clock=at(NOW),code_sha='b'*40)
            calls=[]
            def fake(root,*args):
                calls.append(args)
                if args[0]=='branch':return shadow.BRANCH
                if args[0] in ['diff','status']:return ''
                if args[0]=='push' and sum(x[0]=='push' for x in calls)<3:raise subprocess.CalledProcessError(1,'push')
                if args[0]=='rev-parse':return 'a'*40
                if args[0]=='ls-remote':return 'a'*40+' refs/heads/'+shadow.BRANCH
                return ''
            with patch.object(shadow,'git',side_effect=fake),patch.object(shadow.time,'sleep'):
                self.assertEqual(shadow.persist(d),'a'*40)
            self.assertEqual(sum(x[0]=='push' for x in calls),3);self.assertTrue(list(Path(d).rglob('*.json')))
    def test_late_remote_receipt_excluded_and_review_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            b=shadow.capture(snap(),fitted(),d,clock=at(NOW),code_sha='b'*40)
            with patch.object(shadow,'git',side_effect=['a'*40,json.dumps(b)]):r=shadow.receipt(d,b,'a'*40,clock=at('2026-10-19T11:11:00+09:00'))
            self.assertEqual(r['status'],'late_receipt_excluded')
            with self.assertRaises(ValueError):shadow.review_bundle(d,b,{},r)
    def test_wrong_branch_and_outside_prefix_blocked(self):
        with patch.object(shadow,'git',return_value='main'):
            with self.assertRaises(ValueError):shadow.persist('.')
        with patch.object(shadow,'git',side_effect=[shadow.BRANCH,'','?? data/venue_specialists_v1/new.json']):
            with self.assertRaises(ValueError):shadow.persist('.')
    def test_lock_prevents_two_process_writers(self):
        with tempfile.TemporaryDirectory() as d,patch.object(shadow,'git',return_value=d):
            with shadow.locked(d):
                with self.assertRaises(BlockingIOError):
                    with shadow.locked(d):pass
    def test_production_or_queued_job_yields_research(self):
        for status in ['in_progress','queued','waiting']:
            self.assertFalse(resource_guard.decide([{'id':1,'name':'Discord Production','status':status}],2)['allowed'])
    def test_own_run_does_not_block_itself(self):
        self.assertTrue(resource_guard.decide([{'id':2,'status':'in_progress'}],2)['allowed'])
    def test_numeric_string_courses_normalized(self):
        s=snap('16')
        for b in s['boats']:b['course']=str(b['course']);b['lane']=str(b['lane'])
        self.assertEqual(len(model.predict(s,fitted('16'),'A',mode='replay',now=NOW)['virtual_card']),10)

if __name__=='__main__':unittest.main()
