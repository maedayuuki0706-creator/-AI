import io
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from delivery_v2 import receipts, guard
from delivery_v2.store import FileStore, GitHubStore, default_store
from delivery_v2.catchup import Pending, run_once


class DurableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for name, value in [('ROOT', Path(self.temp.name)/'receipts')]:
            p = patch.object(receipts, name, value); p.start(); self.addCleanup(p.stop)
        p = patch.object(guard, 'RECOVERY', Path(self.temp.name)/'recovery'); p.start(); self.addCleanup(p.stop)
        self.now = datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc)
        self.store = FileStore()
        self.args = ('main','20261004','01',1,'prediction')

    def deliver(self, sender, **kw):
        return guard.deliver_once(*self.args, sender, store=kw.pop('store', self.store),
                                  clock=lambda: self.now, **kw)

    def test_restart_after_loss_of_local_mirror_does_not_repost(self):
        sender = Mock(return_value='12345')
        first = self.deliver(sender)
        second = self.deliver(sender, store=FileStore())
        self.assertEqual(first['status'], 'sent')
        self.assertEqual(second['status'], 'already_sent')
        self.assertEqual(second['message_id'], first['message_id'])
        sender.assert_called_once()

    def test_two_workers_claim_the_same_race_only_once(self):
        sender = Mock(return_value='12345')
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: self.deliver(sender, store=FileStore()), range(2)))
        sender.assert_called_once()

    def test_persistence_failure_after_ack_blocks_repost_and_keeps_id(self):
        real_write = self.store.write
        def write(key, row, sha):
            if row['status'] == 'sent':
                raise OSError('state unavailable')
            return real_write(key, row, sha)
        sender = Mock(return_value='12345')
        with patch.object(self.store, 'write', side_effect=write), self.assertRaises(OSError):
            self.deliver(sender)
        self.assertEqual(self.deliver(sender)['status'], 'sending')
        sender.assert_called_once()
        self.assertEqual(json.loads(next(guard.RECOVERY.glob('*.json')).read_text())['message_id'], '12345')

    def test_timeout_and_missing_ack_are_held_across_restart(self):
        for sender in [Mock(side_effect=TimeoutError()), Mock(return_value=None)]:
            self.args = (*self.args[:3], self.args[3]+1, 'prediction')
            self.assertEqual(self.deliver(sender)['status'], 'uncertain')
            self.assertEqual(self.deliver(sender, store=FileStore())['status'], 'uncertain')
            sender.assert_called_once()

    def test_explicit_rate_limit_retry_is_bounded_and_keeps_original_payload(self):
        def rate_limit(content):
            raise HTTPError('redacted', 429, 'limited', {}, io.BytesIO(b'{"retry_after":60}'))
        sender = Mock(side_effect=rate_limit)
        self.assertEqual(self.deliver(sender)['status'], 'retry')
        self.deliver(sender); self.assertEqual(sender.call_count, 1)
        self.now += timedelta(seconds=61)
        self.args = (*self.args[:4], 'changed prediction')
        self.assertEqual(self.deliver(sender)['status'], 'retry')
        self.now += timedelta(seconds=61)
        self.assertEqual(self.deliver(sender)['status'], 'failed')
        self.now += timedelta(hours=1)
        self.assertEqual(self.deliver(sender)['status'], 'failed')
        self.assertEqual(sender.call_count, 3)
        self.assertTrue(all(call.args[0] == 'prediction' for call in sender.call_args_list))

    def test_expired_prediction_is_never_posted(self):
        sender = Mock(return_value='12345')
        self.assertEqual(self.deliver(sender, expires_at=self.now)['status'], 'expired')
        sender.assert_not_called()

    def test_storage_unavailable_prevents_post(self):
        sender = Mock(return_value='12345')
        with patch.object(self.store, 'read', side_effect=OSError()), self.assertRaises(OSError):
            self.deliver(sender)
        sender.assert_not_called()

    def test_corrupt_receipt_does_not_become_permission_to_resend(self):
        p = receipts.path_for('main','20261004','01',1)
        p.parent.mkdir(parents=True); p.write_text('broken')
        sender = Mock(return_value='12345')
        with self.assertRaises(ValueError): self.deliver(sender)
        sender.assert_not_called()

    def test_paths_and_naive_times_are_rejected(self):
        for stream in ('../main', 'main/a', ''):
            with self.assertRaises(ValueError): receipts.path_for(stream,'20261004','01',1)
        with self.assertRaises(ValueError): receipts.path_for('main','20261004','25',1)
        with self.assertRaises(ValueError): self.deliver(Mock(), expires_at=datetime(2026,10,4))

    def test_production_cannot_silently_fall_back_to_local_storage(self):
        with patch.dict('os.environ', {}, clear=True), self.assertRaises(RuntimeError): default_store()
        with patch.dict('os.environ', {'GITHUB_ACTIONS':'true'}, clear=True):
            self.assertIsInstance(default_store(), GitHubStore)

    def test_delayed_pass_catches_up_only_unexpired_due_predictions(self):
        sender = Mock(return_value='12345')
        rows = [Pending('main','20261004','01',r,self.now-timedelta(minutes=5),
                        self.now+timedelta(minutes=offset),'prediction',{})
                for r,offset in [(1,-1),(2,4)]]
        result = run_once(rows, {'main':sender}, store=self.store, clock=lambda:self.now)
        self.assertEqual([r['status'] for r in result], ['expired','sent'])
        sender.assert_called_once()


if __name__ == '__main__': unittest.main()
