import contextlib
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import urllib.error
from unittest.mock import Mock, patch

import direct_discord_notify as base
import detailed_discord_notify as detailed
import notification_audit as audit
import notification_delivery as delivery
import notification_runner as runner
import persist_notification_state as persistence

ACK={'id':'123456','channel_id':'654321'}
RECORD={'day':'20260914','jcd':'19','rno':1,'phase':'final','deadline':'15:27',
        'all_picks':['1-2-3'],'virtual_bets':[{'combination':'1-2-3','units':1}]}


class Isolated(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        for target,attr,value in [(audit,'AUDIT_ROOT',self.root/'audit'),
                                  (delivery,'OUTBOX_ROOT',self.root/'outbox'),
                                  (base,'LOG_PATH',self.root/'predictions.jsonl'),
                                  (base,'CARD_DIR',self.root/'cards')]:
            item=patch.object(target,attr,value);item.start();self.addCleanup(item.stop)
        env=patch.dict(os.environ,{'NOTIFICATION_CHECKPOINT':'0'})
        env.start();self.addCleanup(env.stop)
        capture=contextlib.redirect_stdout(io.StringIO())
        capture.__enter__();self.addCleanup(capture.__exit__,None,None,None)

    def events(self):
        return [json.loads(line) for p in audit.AUDIT_ROOT.glob('*/*.jsonl') for line in p.read_text().splitlines()]


class DeliveryRecoveryTests(Isolated):
    def test_acknowledgement_survives_prediction_log_failure_without_another_post(self):
        send=Mock(return_value=ACK)
        with self.assertRaises(OSError):
            delivery.deliver('real forecast fixture',[RECORD],sender=send,writer=Mock(side_effect=OSError('disk full')))
        self.assertFalse(base.LOG_PATH.exists())
        self.assertEqual(json.loads(delivery.outbox_path([RECORD]).read_text())['status'],'confirmed')
        existing=delivery.recover_predictions(base.log_prediction,set())
        self.assertIn(('20260914','19',1,'final'),existing)
        row=json.loads(base.LOG_PATH.read_text())
        self.assertEqual(row['message_id'],ACK['id'])
        self.assertEqual(row['virtual_bets'],RECORD['virtual_bets'])
        delivery.deliver('same forecast',[RECORD],sender=send,writer=base.log_prediction)
        self.assertEqual(send.call_count,1)
        self.assertEqual(len(base.LOG_PATH.read_text().splitlines()),1)
        self.assertIn('send_success',[e['event'] for e in self.events()])
        self.assertIn('persist_failed',[e['event'] for e in self.events()])

    def test_timeout_does_not_fabricate_success_or_blindly_retry(self):
        send=Mock(side_effect=TimeoutError('ambiguous response'))
        for _ in range(2):
            with self.assertRaises((TimeoutError,delivery.SendUnknown)):
                delivery.deliver('forecast',[RECORD],sender=send,writer=base.log_prediction)
        self.assertEqual(send.call_count,1)
        self.assertFalse(base.LOG_PATH.exists())
        self.assertNotIn('send_success',[e['event'] for e in self.events()])
        self.assertIn('send_outcome_unknown',[e.get('reason') for e in self.events()])

    def test_explicit_rejection_can_retry(self):
        send=Mock(side_effect=[delivery.SendRejected('HTTP 429'),ACK])
        with self.assertRaises(delivery.SendRejected):
            delivery.deliver('forecast',[RECORD],sender=send,writer=base.log_prediction)
        self.assertTrue(delivery.deliver('forecast',[RECORD],sender=send,writer=base.log_prediction))
        self.assertEqual(send.call_count,2)

    def test_cannot_post_if_intent_cannot_be_persisted(self):
        send=Mock(return_value=ACK)
        with patch.object(delivery,'checkpoint',side_effect=[persistence.PersistenceError('offline'),None]):
            with self.assertRaises(persistence.PersistenceError):
                delivery.deliver('forecast',[RECORD],sender=send,writer=base.log_prediction)
        send.assert_not_called()
        self.assertEqual(json.loads(delivery.outbox_path([RECORD]).read_text())['status'],'not_sent')

    def test_cutoff_is_rechecked_after_persisting_intent(self):
        send=Mock(return_value=ACK)
        with self.assertRaises(delivery.DeadlinePassed):
            delivery.deliver('forecast',[RECORD],sender=send,writer=base.log_prediction,can_send=lambda:False)
        send.assert_not_called()
        self.assertFalse(base.LOG_PATH.exists())

    def test_confirmed_evidence_is_not_changed_by_a_later_model_allocation(self):
        with patch.dict(detailed._VIRTUAL,{('20260914','19',1,'final'):{'bets':[],'total_units':0}}):
            self.assertEqual(detailed.enrich_prediction_with_virtual(RECORD),RECORD)

    def test_transport_requires_message_and_channel_acknowledgement(self):
        with patch.object(delivery.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(ACK).encode())) as send:
            self.assertEqual(delivery.post_json('https://example.test/hook?thread_id=99',{'content':'fixture'}),ACK)
            self.assertIn('wait=true',send.call_args.args[0].full_url)
            self.assertIn('thread_id=99',send.call_args.args[0].full_url)
        with patch.object(delivery.urllib.request,'urlopen',return_value=io.BytesIO(b'{"id":"123"}')):
            with self.assertRaises(delivery.SendUnknown):
                delivery.post_json('https://example.test/hook',{})

    def test_rate_limit_recheck_stops_a_late_retry(self):
        error=urllib.error.HTTPError('https://example.test',429,'limited',{},io.BytesIO(b'{"retry_after":1}'))
        guard=Mock(side_effect=[True,False])
        with patch.object(delivery.urllib.request,'urlopen',side_effect=error) as send:
            with self.assertRaises(delivery.DeadlinePassed):
                delivery.post_json('https://example.test/hook',{},can_send=guard,pause=lambda _:None)
        self.assertEqual(send.call_count,1)

    def test_audit_redacts_credentials_and_urls(self):
        audit.emit('analysis_failed',day='20260914',token='private-test-value',
                   details={'webhook':'private-test-value','error':'https://example.test/private'})
        text=json.dumps(self.events())
        self.assertNotIn('private-test-value',text)
        self.assertNotIn('https://',text)


class SelectionAndMonitorTests(Isolated):
    def setUp(self):
        super().setUp()
        self.now=datetime(2026,9,14,14,57,tzinfo=base.JST)
        self.clock=[self.now]
        self.analysis={'inputs':[{'lane':n} for n in range(1,7)],'preview':{'exhibition_count':6},
                       'model_version':'fixture','grade':'B','heads':{},'previous_form':{},
                       'trifecta':[{'combination':'1-2-3'}]}
        for target,attr,value in [(base,'fetch',Mock()),(base,'discover_venues',Mock(return_value=['19'])),
                                  (base,'deadlines',Mock(return_value=['15:27'])),
                                  (base,'make_analysis_message',Mock(return_value='forecast fixture')),
                                  (base,'send_race_notice',Mock(return_value=True)),
                                  (base,'send_discord',Mock(return_value=ACK))]:
            item=patch.object(target,attr,value);item.start();self.addCleanup(item.stop)
        item=patch.object(base,'datetime')
        clock=item.start();self.addCleanup(item.stop)
        clock.now.side_effect=lambda *args:self.clock[0]

    def test_analysis_crossing_cutoff_is_audited_without_posting(self):
        def analyze(*args):
            self.clock[0]=self.now.replace(hour=15,minute=23)
            return self.analysis
        with patch.object(base,'analyze_official',side_effect=analyze):
            self.assertEqual(base.run_once(self.now),0)
        base.send_discord.assert_not_called()
        self.assertIn('deadline_after_analysis',[e.get('reason') for e in self.events()])

    def test_analysis_failure_identifies_stage_and_race(self):
        with patch.object(base,'analyze_official',side_effect=TimeoutError):
            self.assertEqual(base.run_once(self.now),1)
        failures=[e for e in self.events() if e['event']=='analysis_failed']
        self.assertTrue(any(e['jcd']=='19' and e['rno']==1 and e['stage']=='prediction' for e in failures))
        base.send_discord.assert_not_called()

    def test_final_has_priority_over_bulk_preliminaries(self):
        base.discover_venues.return_value=['19','20']
        base.deadlines.side_effect=lambda day,jcd:['15:27'] if jcd=='19' else ['19:00']*12
        with patch.object(base,'analyze_official',return_value=self.analysis) as analyze:
            self.assertEqual(base.run_once(self.now),0)
        self.assertEqual(analyze.call_args_list[0].args[1],'19')
        self.assertEqual(analyze.call_count,12)
        self.assertIn('batch_deferred',[e.get('reason') for e in self.events()])
        self.assertEqual(json.loads(base.LOG_PATH.read_text().splitlines()[0])['phase'],'final')

    def test_monitor_sees_exhibition_that_appears_after_old_ten_minute_watch(self):
        elapsed=[0]
        def analyze(*args):
            count=6 if elapsed[0]>=1200 else 0
            return {**self.analysis,'preview':{'exhibition_count':count}}
        def attempt():
            self.clock[0]=self.now+timedelta(seconds=elapsed[0])
            return base.run_once(self.clock[0])
        def pause(seconds):
            elapsed[0]+=seconds
        with patch.object(base,'analyze_official',side_effect=analyze):
            self.assertEqual(runner.run(1800,attempt=attempt,clock=lambda:elapsed[0],
                                        pause=pause,is_open=lambda:elapsed[0]<1500),0)
        self.assertEqual(base.send_discord.call_count,1)
        self.assertEqual(json.loads(base.LOG_PATH.read_text())['phase'],'final')

    def test_preliminary_and_waiting_do_not_consume_final_slot(self):
        base.log_prediction({**RECORD,'phase':'preliminary'})
        with patch.object(base,'analyze_official',return_value={**self.analysis,'preview':{'exhibition_count':0}}):
            base.run_once(self.now)
        base.send_discord.assert_not_called()
        with patch.object(base,'analyze_official',return_value=self.analysis):
            base.run_once(self.now)
        self.assertEqual(base.send_discord.call_count,1)
        self.assertEqual(len(base.LOG_PATH.read_text().splitlines()),2)

    def test_dry_run_does_not_write_audit_outbox_cards_or_predictions(self):
        with patch.object(base,'analyze_official',return_value=self.analysis):
            self.assertEqual(base.run_once(self.now,dry_run=True),0)
        self.assertEqual(list(self.root.rglob('*')),[])
        base.send_discord.assert_not_called()

    def test_partial_fetch_error_distinct_from_unpublished_exhibition(self):
        with patch.object(base,'withdrawal_lanes',return_value=[]),patch.object(base,'parse_racelist_boats',
                    return_value=[{'lane':i} for i in range(1,7)]),patch.object(base,'previous_form',return_value={}),patch.object(base,'analyze_race',
                    return_value={'trifecta':[{'combination':'1-2-3','probability':.1}]}):
            base.fetch.side_effect=['racelist',TimeoutError(),TimeoutError()]
            result=base.analyze_official('20260914','19',1)
        self.assertEqual(result['preview']['fetch_error'],'TimeoutError')
        self.assertEqual({e['source'] for e in result['data_errors']},{'beforeinfo','odds3t'})


class PersistenceTests(Isolated):
    def test_append_journals_merge_without_losing_competing_records(self):
        path='data/prediction_log.jsonl'
        merged=persistence.merge_content(path,b'{"rno":1}\n{"rno":2}\n',b'{"rno":1}\n{"rno":3}\n')
        self.assertEqual([json.loads(x)['rno'] for x in merged.splitlines()],[1,2,3])
        with self.assertRaises(ValueError):
            persistence.merge_content(path,b'{"rno":1}\n',b'broken')

    def test_pending_delivery_cannot_overwrite_another_run_owner(self):
        a=json.dumps({'status':'intent','run_id':'a'}).encode()
        b=json.dumps({'status':'intent','run_id':'b'}).encode()
        with self.assertRaises(persistence.PersistenceError):
            persistence.merge_content('data/notification_outbox/x.json',a,b)

    def test_race_card_fetch_failure_preserves_known_deadline(self):
        a=json.dumps({'checked_at':'1','races':{'19:1':{'deadline':'15:27'}}}).encode()
        b=json.dumps({'checked_at':'2','races':{'19:1':{'deadline':None}}}).encode()
        actual=json.loads(persistence.merge_content('data/race_cards/20260914.json',a,b))
        self.assertEqual(actual['races']['19:1']['deadline'],'15:27')

    def test_repository_race_retries_preserving_code_and_both_logs(self):
        origin=self.root/'remote.git';one=self.root/'one';two=self.root/'two'
        def git(cwd,*args):
            result=subprocess.run(['git','-C',str(cwd),*args],capture_output=True,check=True)
            return result.stdout.decode().strip()
        subprocess.run(['git','init','--bare',str(origin)],check=True,capture_output=True)
        for directory in [one,two]:
            subprocess.run(['git','clone',str(origin),str(directory)],check=True,capture_output=True)
            git(directory,'config','user.email','fixture@example.test')
            git(directory,'config','user.name','Fixture')
        git(one,'checkout','-b','main')
        (one/'data').mkdir();(one/'data/prediction_log.jsonl').write_text('{"rno":1}\n')
        (one/'model.py').write_text('original\n')
        git(one,'add','.');git(one,'commit','-m','seed');git(one,'push','origin','main')
        git(two,'fetch','origin','main');git(two,'checkout','-b','main','origin/main')
        (one/'data/prediction_log.jsonl').write_text('{"rno":1}\n{"rno":2}\n')
        original_head=git(one,'rev-parse','HEAD')
        def compete(attempt):
            if attempt==0:
                (two/'data/prediction_log.jsonl').write_text('{"rno":1}\n{"rno":3}\n')
                (two/'model.py').write_text('another users update\n')
                git(two,'add','.');git(two,'commit','-m','competing writer');git(two,'push','origin','main')
        with contextlib.chdir(one):
            commit=persistence.publish(persistence.changed_data(),before_push=compete)
        self.assertTrue(commit)
        self.assertEqual(git(one,'rev-parse','HEAD'),original_head)
        self.assertEqual(git(origin,'show','main:model.py'),'another users update')
        rows=[json.loads(line)['rno'] for line in git(origin,'show','main:data/prediction_log.jsonl').splitlines()]
        self.assertEqual(set(rows),{1,2,3})
        # Checkpointing the same evidence again cannot create another commit.
        with contextlib.chdir(one):
            self.assertIsNone(persistence.publish(persistence.changed_data()))

    def test_repository_audit_only_claims_success_after_accepted_commit(self):
        with patch.dict(os.environ,{'NOTIFICATION_CHECKPOINT':'1'}),patch.object(persistence,'changed_data',return_value={}),patch.object(persistence,'publish',side_effect=persistence.PersistenceError):
            with self.assertRaises(persistence.PersistenceError):
                persistence.checkpoint(required=True)
        self.assertNotIn('persist_success',[e['event'] for e in self.events()])
        self.assertIn('persist_failed',[e['event'] for e in self.events()])


if __name__=='__main__':
    unittest.main()
