"""Repeated audit of an old missed race must not masquerade as a new outage."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from delivery_v2 import dispatcher, receipts
from delivery_v2.store import FileStore

JST = ZoneInfo('Asia/Tokyo')


class RepeatedMissAuditTests(unittest.TestCase):
    def test_existing_missed_remains_degraded_but_not_a_new_action_failure(self):
        now = datetime(2026, 10, 9, 18, 12, tzinfo=JST)
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(receipts, 'ROOT', Path(temp) / 'state'), \
             patch.object(dispatcher, 'SUMMARY', Path(temp) / 'report.json'), \
             patch.object(dispatcher, 'legacy_state', return_value=({}, [])), \
             patch.object(dispatcher, 'notify_failure') as alert:
            kwargs = dict(
                store=FileStore(), clock=lambda: now,
                schedules={'01': ['18:10']},
                engine=lambda *args, **kw: None,
                active=('yuuki',), activation_at=now - timedelta(hours=1),
            )
            first = dispatcher.run_once(**kwargs)
            self.assertEqual(first['status'], 'degraded')
            self.assertEqual(len(first['active_missed']), 1)
            self.assertEqual(len(first['new_active_missed']), 1)
            self.assertEqual(dispatcher.dispatch_exit_code(first), 1)

            second = dispatcher.run_once(**kwargs)
            self.assertEqual(second['status'], 'degraded')
            self.assertEqual(len(second['active_missed']), 1)
            self.assertEqual(second['new_active_missed'], [])
            self.assertEqual(dispatcher.dispatch_exit_code(second), 0)
            self.assertEqual(second['active_missed'][0]['status'], 'missed')
            self.assertEqual(alert.call_count, 2)

    def test_actual_new_or_technical_error_still_fails(self):
        healthy = dict(new_active_missed=[], schedule_errors=[], delivery_errors={})
        self.assertEqual(dispatcher.dispatch_exit_code(healthy), 0)
        for changed in (
            dict(new_active_missed=[{'key': 'yuuki:20261009:23:3:final'}]),
            dict(schedule_errors=[{'jcd': '23', 'error_type': 'TimeoutError'}]),
            dict(delivery_errors={'yuuki:20261009:23:3:final': 'storage_error'}),
        ):
            self.assertEqual(dispatcher.dispatch_exit_code({**healthy, **changed}), 1)


if __name__ == '__main__':
    unittest.main()
