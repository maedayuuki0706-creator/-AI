import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from delivery_v2 import dispatcher, guard, receipts
from delivery_v2.catchup import Pending, run_once as catch_up
from delivery_v2.store import FileStore
from delivery_v2.watchdog import audit, generate_expected

JST = ZoneInfo('Asia/Tokyo')


class DispatcherTests(unittest.TestCase):
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
