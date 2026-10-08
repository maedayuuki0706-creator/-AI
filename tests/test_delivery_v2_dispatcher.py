import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from delivery_v2 import dispatcher, guard, receipts, integration
from delivery_v2.catchup import Pending, run_once as catch_up
from delivery_v2.store import FileStore
from delivery_v2.watchdog import audit, generate_expected

JST = ZoneInfo('Asia/Tokyo')


class DispatcherTests(unittest.TestCase):
    def test_exhibition_arriving_on_second_pass_sends_exactly_once(self):
        import prototype3_delivery as yuuki
        now = datetime(2026,10,4,18,12,tzinfo=JST)
        elapsed = [0.0]
        clock = lambda: now+timedelta(seconds=elapsed[0])
        def sleep(seconds):
            elapsed[0] += seconds
        record = dict(day='20261004',jcd='01',rno=1,deadline='18:15',venue='桐生',
                      key='20261004_01_01',digest='unchanged-prediction',selection={'selected':False},
                      model={'main_picks':['1-2-3'],'cover_picks':[],'point_count':1})
        real_deliver = guard.deliver_once
        with tempfile.TemporaryDirectory() as temp, patch.object(receipts,'ROOT',Path(temp)/'state'), \
             patch.object(yuuki,'ROOT',Path(temp)/'legacy'), patch.object(guard,'RECOVERY',Path(temp)/'recovery'), \
             patch.object(yuuki,'now_jst',side_effect=clock), \
             patch.dict('os.environ',{'DISCORD_DELIVERY_V2_STREAMS':'yuuki', 'PT3_DISCORD_WEBHOOK_URL':'test-only'}), \
             patch.object(integration,'default_store',side_effect=FileStore), \
             patch.object(integration,'deliver_once',side_effect=lambda *a,**kw:real_deliver(*a,**kw,clock=clock)), \
             patch.object(yuuki,'post_webhook',return_value='123456') as post, \
             patch.object(yuuki,'build_record',side_effect=[(None,'waiting_for_exhibition'),(record,'ready')]) as build:
            result = dispatcher.yuuki_engine('20261004',{'01':['18:15']},FileStore(),clock=clock,
                budget_seconds=60,recheck_seconds=20,monotonic=lambda:elapsed[0],sleep=sleep)
            self.assertEqual(result,{'passes':2,'waiting':{}})
            self.assertEqual(build.call_count,2)
            self.assertEqual(yuuki.read(yuuki.prediction_path(record['key'])),record)
            self.assertEqual(yuuki.read(yuuki.receipt_path(record['key']))['message_id'],'123456')
            dispatcher.yuuki_engine('20261004',{'01':['18:15']},FileStore(),clock=clock,
                budget_seconds=60,recheck_seconds=20,monotonic=lambda:elapsed[0],sleep=sleep)
            post.assert_called_once()

    def test_exhibition_wait_never_retries_after_deadline(self):
        import prototype3_delivery as yuuki
        now = datetime(2026,10,4,18,13,55,tzinfo=JST)
        elapsed = [0.0]
        clock = lambda: now+timedelta(seconds=elapsed[0])
        def sleep(seconds):
            elapsed[0] += seconds
        with tempfile.TemporaryDirectory() as temp, patch.object(receipts,'ROOT',Path(temp)/'state'), \
             patch.object(yuuki,'ROOT',Path(temp)/'legacy'), patch.object(yuuki,'now_jst',side_effect=clock), \
             patch.object(yuuki,'build_record',return_value=(None,'waiting_for_exhibition')) as build, \
             patch.object(yuuki,'post_webhook') as post:
            dispatcher.yuuki_engine('20261004',{'01':['18:15']},FileStore(),clock=clock,
                budget_seconds=100,recheck_seconds=70,monotonic=lambda:elapsed[0],sleep=sleep)
            build.assert_called_once()
            post.assert_not_called()

    def test_generation_budget_prevents_starting_more_races(self):
        import prototype3_delivery as yuuki
        now = datetime(2026,10,4,18,12,tzinfo=JST)
        elapsed = [0.0]
        def process(*args):
            elapsed[0] += 60
        with tempfile.TemporaryDirectory() as temp, patch.object(receipts,'ROOT',Path(temp)/'state'), \
             patch.object(yuuki,'ROOT',Path(temp)/'legacy'), patch.object(yuuki,'process_race',side_effect=process) as run:
            dispatcher.yuuki_engine('20261004',{'01':['18:15','18:20']},FileStore(),clock=lambda:now,
                budget_seconds=30,monotonic=lambda:elapsed[0])
            run.assert_called_once()

    def test_late_first_wake_next_day_still_reports_missed_active_races(self):
        now = datetime(2026,10,5,8,45,tzinfo=JST)
        activation = datetime(2026,10,4,20,53,tzinfo=JST)
        with tempfile.TemporaryDirectory() as temp, patch.object(receipts,'ROOT',Path(temp)/'state'), \
             patch.object(dispatcher,'SUMMARY',Path(temp)/'report.json'), \
             patch.object(dispatcher,'legacy_state',return_value=({},[])), patch.object(dispatcher,'notify_failure') as notify:
            report = dispatcher.run_once(store=FileStore(),clock=lambda:now, schedules={'01':['08:30']},
                engine=lambda *args,**kwargs:None, active=('yuuki',), activation_at=activation)
            self.assertEqual(report['status'],'degraded')
            self.assertIsNone(report['last_successful_check'])
            self.assertEqual(report['active_since']['yuuki'],activation.isoformat())
            self.assertEqual([row['stream'] for row in report['active_missed']],['yuuki'])
            notify.assert_called_once()

    def test_live_dispatch_starts_before_full_receipt_snapshot(self):
        now = datetime(2026,10,8,17,30,tzinfo=JST)
        with tempfile.TemporaryDirectory() as temp, patch.object(receipts,'ROOT',Path(temp)/'state'), \
             patch.object(dispatcher,'SUMMARY',Path(temp)/'report.json'), \
             patch.object(dispatcher,'legacy_state',return_value=({},[])), \
             patch.object(dispatcher,'notify_failure'):
            store = FileStore()
            with patch.object(store,'list_day', wraps=store.list_day) as scan:
                dispatcher.run_once(store=store, clock=lambda:now,
                    schedules={'01':['17:40']}, engine=lambda *args,**kw:None,
                    active=('yuuki',))
                scan.assert_called_once_with('20261008')

    def test_actual_receipt_verification_rejects_a_different_report_prediction(self):
        import prototype3_delivery as yuuki
        now = datetime(2026,10,4,18,12,tzinfo=JST)
        record = dict(day='20261004',jcd='01',rno=1,deadline='18:15',venue='桐生',
                      key='20261004_01_01',digest='original',selection={'selected':False},
                      model={'main_picks':['1-2-3'],'cover_picks':[],'point_count':1})
        with tempfile.TemporaryDirectory() as temp, patch.object(receipts,'ROOT',Path(temp)/'state'), \
             patch.object(yuuki,'ROOT',Path(temp)/'legacy'), patch.object(guard,'RECOVERY',Path(temp)/'recovery'):
            result = guard.deliver_once('yuuki','20261004','01',1,yuuki.message(record),lambda _: '987654321',
                store=FileStore(),record=record,expires_at=now+timedelta(minutes=3),clock=lambda:now)
            receipts.atomic_write(yuuki.prediction_path(record['key']),record)
            receipts.atomic_write(yuuki.receipt_path(record['key']),{'message_id':'987654321','prediction_digest':'original'})
            proof = {result['key']:result}
            verified = dispatcher.verify_yuuki('20261004',proof,store=FileStore())[0]
            self.assertEqual(verified['message_id'],'987654321')
            self.assertTrue(verified['restart_duplicate_guard_verified'])
            receipts.atomic_write(yuuki.prediction_path(record['key']),{**record,'digest':'different'})
            with self.assertRaises(ValueError):
                dispatcher.verify_yuuki('20261004',proof)

    def test_cached_schedule_survives_transient_official_index_failure(self):
        import direct_discord_notify as base
        with patch.object(base,'discover_venues',side_effect=TimeoutError), \
             patch.object(base,'deadlines',return_value=['18:15']):
            schedules, errors = dispatcher.discover('20261004', {'01':['18:15']})
            self.assertEqual(schedules, {'01':['18:15']})
            self.assertEqual(errors,[{'jcd':'index','error_type':'TimeoutError'}])

    def test_delayed_1812_wake_sends_all_due_unexpired_and_never_past_deadline(self):
        now = datetime(2026,10,4,18,12,tzinfo=JST)
        with tempfile.TemporaryDirectory() as temp, patch.object(receipts,'ROOT',Path(temp)/'state'), \
             patch.object(guard,'RECOVERY',Path(temp)/'recovery'):
            store = FileStore()
            calls = []
            def send(content):
                calls.append(content)
                return str(1000+len(calls))
            pending = [Pending('yuuki','20261004','01',r,now-timedelta(minutes=12),close,text,{'all_picks':[text]})
                       for r,close,text in [(1,now-timedelta(minutes=1),'expired'),
                                            (2,now+timedelta(minutes=3),'catch-up'),
                                            (3,now+timedelta(minutes=8),'second target')]]
            first = catch_up(pending, {'yuuki':send}, store=store, clock=lambda:now)
            self.assertEqual(calls,['catch-up','second target'])
            self.assertEqual([row['status'] for row in first],['expired','sent','sent'])
            catch_up(pending, {'yuuki':send}, store=store, clock=lambda:now)
            self.assertEqual(len(calls),2)

    def test_production_engine_scans_current_day_after_hours_without_a_wake(self):
        now = datetime(2026,10,4,18,12,tzinfo=JST)
        import prototype3_delivery as yuuki
        with tempfile.TemporaryDirectory() as temp, patch.object(receipts,'ROOT',Path(temp)/'state'), \
             patch.object(yuuki,'ROOT',Path(temp)/'legacy'), patch.object(yuuki,'process_race') as process:
            dispatcher.yuuki_engine('20261004', {'01':['18:10','18:15','18:20','19:00']},
                                    FileStore(), clock=lambda:now)
            self.assertEqual([call.args[2] for call in process.call_args_list],[2,3])

    def test_watchdog_gated_streams_and_ambiguous_sends_are_not_false_success(self):
        now = datetime(2026,10,4,18,12,tzinfo=JST)
        records = [dict(day='20261004',jcd='01',rno=1,deadline='18:10',stream='longshot',status='sniper_skip'),
                   dict(day='20261004',jcd='01',rno=2,deadline='18:15',stream='yuuki_selected')]
        expected = generate_expected('20261004', {'01':['18:10','18:15']}, records=records)
        self.assertFalse(any(item.stream=='longshot' for item in expected))
        self.assertEqual(len([item for item in expected if item.stream=='yuuki_selected']),1)
        state = {receipts.identity('yuuki','20261004','01',2):{'status':'uncertain'}}
        rows = audit(expected, now=now, durable=state)
        self.assertEqual({row['status'] for row in rows}, {'missed','catch_up','uncertain'})

    def test_dispatcher_persists_missed_and_recovers_from_lost_cursor(self):
        now = datetime(2026,10,4,18,12,tzinfo=JST)
        with tempfile.TemporaryDirectory() as temp, patch.object(receipts,'ROOT',Path(temp)/'state'), \
             patch.object(dispatcher,'SUMMARY',Path(temp)/'report.json'), patch.object(dispatcher,'legacy_state',return_value=({},[])):
            calls = []
            def engine(day, schedules, store, *, clock):
                calls.append(schedules)
            report = dispatcher.run_once(store=FileStore(), clock=lambda:now,
                schedules={'01':['18:10','18:15']}, engine=engine)
            self.assertEqual(report['counts'],{'missed':2,'catch_up':2})
            stored,_ = FileStore().read(report['key'])
            self.assertEqual(stored['deliveries'],report['deliveries'])
            receipts.path_for('dispatcher','20261004','01',1,'check').unlink()
            dispatcher.run_once(store=FileStore(), clock=lambda:now, schedules={'01':['18:10','18:15']},engine=engine)
            self.assertEqual(len(calls),2)


if __name__=='__main__':
    unittest.main()
