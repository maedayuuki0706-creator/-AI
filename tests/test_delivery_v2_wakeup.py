import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from delivery_v2 import wakeup


class WakeupTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026,10,5,2,0,tzinfo=timezone.utc)

    def api(self, rows=(), state='active', fail_dispatch=False):
        def call(path, payload=None):
            if path.endswith('/dispatches'):
                if fail_dispatch:
                    raise TimeoutError('request outcome unknown')
                return {}
            if '/runs?' in path:
                return {'workflow_runs':list(rows)}
            return {'id':42,'state':state}
        return Mock(side_effect=call)

    def test_existing_legacy_run_is_never_cancelled_or_restarted(self):
        api = self.api([{'id':2,'status':'in_progress','created_at':'2026-10-05T01:30:00Z'}])
        self.assertEqual(wakeup.wake('discord_notify.yml',api=api,now=self.now)['status'],'already_active')
        self.assertFalse(any(call.args[0].endswith('/dispatches') for call in api.call_args_list))

    def test_recent_completed_legacy_run_is_not_started_again(self):
        api = self.api([{'id':2,'status':'completed','created_at':'2026-10-05T01:59:00Z'}])
        self.assertEqual(wakeup.wake('sokuhou-delivery.yml',api=api,now=self.now)['status'],'recent_run')

    def test_continuation_ignores_its_parent_and_uses_dispatch_event(self):
        api = self.api([{'id':1,'status':'in_progress','created_at':'2026-10-05T01:59:00Z'}])
        result = wakeup.wake(wakeup.DISPATCHER,api=api,now=self.now,current_run_id='1',continuation=True)
        self.assertEqual(result['event'],'workflow_dispatch')
        self.assertEqual(api.call_args.args,('/actions/workflows/42/dispatches',
                         {'ref':'main','inputs':{'wake_reason':'continuation'}}))

    def test_already_queued_continuation_does_not_fan_out(self):
        api = self.api([{'id':1,'status':'in_progress'},{'id':2,'status':'queued'}])
        result = wakeup.wake(wakeup.DISPATCHER,api=api,current_run_id='1',continuation=True)
        self.assertEqual(result['status'],'already_active')
        self.assertFalse(any(call.args[0].endswith('/dispatches') for call in api.call_args_list))

    def test_disabled_workflow_is_not_reenabled(self):
        api = self.api(state='disabled_manually')
        self.assertEqual(wakeup.wake('prototype12-delivery.yml',api=api,now=self.now)['status'],'disabled')
        api.assert_called_once()

    def test_ambiguous_dispatch_is_not_blindly_retried(self):
        api = self.api(fail_dispatch=True)
        with self.assertRaises(TimeoutError):
            wakeup.wake(wakeup.DISPATCHER,api=api,continuation=True)
        self.assertEqual(sum(call.args[0].endswith('/dispatches') for call in api.call_args_list),1)

    def test_legacy_api_failure_does_not_block_dispatcher_continuation(self):
        api = self.api()
        real = api.side_effect
        def call(path,payload=None):
            if path.endswith('discord_notify.yml'):
                raise RuntimeError('legacy lookup unavailable')
            return real(path,payload)
        api.side_effect = call
        report = wakeup.run_once(api=api,now=self.now,current_run_id='1',targets=('discord_notify.yml',))
        self.assertEqual([row['status'] for row in report],['error','requested'])


if __name__ == '__main__':
    unittest.main()
