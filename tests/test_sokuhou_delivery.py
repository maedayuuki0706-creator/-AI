from datetime import datetime, timedelta, timezone
import io
import json
import os
import threading
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

import sokuhou_delivery as delivery


class MemoryStore:
    """Compare-and-swap receipts shared by independent simulated runners."""
    def __init__(self):
        self.rows = {}
        self.lock = threading.Lock()
        self.fail_sent = False

    def read(self, key):
        with self.lock:
            row, sha = self.rows.get(key, (None, None))
            return None if row is None else dict(row), sha

    def write(self, key, value, sha):
        with self.lock:
            if self.fail_sent and value['status'] == 'sent':
                raise OSError('receipt service unavailable')
            current = self.rows.get(key, (None, None))[1]
            if sha != current:
                raise urllib.error.HTTPError('https://example.test', 409, 'conflict', {}, None)
            new_sha = str(int(current or 0) + 1)
            self.rows[key] = (dict(value), new_sha)
            return new_sha


class SokuhouDeliveryTests(unittest.TestCase):
    def setUp(self):
        quiet = patch.object(delivery, 'print', create=True)
        quiet.start()
        self.addCleanup(quiet.stop)
        self.store = MemoryStore()
        self.sender = Mock(return_value={'id': '123456'})
        self.key = 'normal:20261003:22:5'
        self.now = datetime(2026, 10, 3, 10, tzinfo=timezone.utc)

    def send(self, key=None, **kwargs):
        return delivery.deliver(key or self.key, '速報', {}, sender=self.sender,
                                store=self.store, now=kwargs.get('now', self.now))

    def test_restart_and_lost_local_journal_do_not_repost(self):
        receipt = self.send()
        self.assertEqual(receipt['status'], 'sent')
        self.assertEqual(self.send()['message_id'], '123456')
        self.sender.assert_called_once()

    def test_two_runners_racing_for_the_same_race_send_once(self):
        original = self.store.read
        barrier = threading.Barrier(2)
        def simultaneous_read(key):
            result = original(key)
            if result[0] is None:
                barrier.wait(timeout=3)
            return result
        self.store.read = simultaneous_read
        with __import__('concurrent.futures', fromlist=['ThreadPoolExecutor']).ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.send(), range(2)))
        self.assertTrue(all(r['status'] in {'sent', 'sending'} for r in results))
        self.sender.assert_called_once()

    def test_crash_after_claim_never_blindly_retries(self):
        self.sender.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.send()
        self.sender.side_effect = None
        self.assertEqual(self.send()['status'], 'sending')
        self.sender.assert_called_once()

    def test_discord_success_followed_by_persistence_failure_does_not_repost(self):
        self.store.fail_sent = True
        with tempfile.TemporaryDirectory() as temp, patch.object(delivery, 'Path', side_effect=lambda _: __import__('pathlib').Path(temp)):
            with self.assertRaises(OSError):
                self.send()
            receipt = json.loads(next(__import__('pathlib').Path(temp).glob('*.json')).read_text())
            self.assertEqual(receipt['message_id'], '123456')
        self.store.fail_sent = False
        self.assertEqual(self.send()['status'], 'sending')
        self.sender.assert_called_once()

    def test_timeout_is_uncertain_not_success_or_automatic_retry(self):
        self.sender.side_effect = TimeoutError()
        self.assertEqual(self.send()['status'], 'uncertain')
        self.assertEqual(self.send()['status'], 'uncertain')
        self.sender.assert_called_once()

    def test_missing_acknowledgement_is_held(self):
        self.sender.return_value = None
        self.assertEqual(self.send()['status'], 'uncertain')
        self.assertEqual(self.send()['status'], 'uncertain')
        self.sender.assert_called_once()

    def test_explicit_rate_limit_respects_delay_and_attempt_limit(self):
        self.sender.side_effect = lambda _: (_ for _ in ()).throw(
            urllib.error.HTTPError('https://example.test', 429, 'rate limit', {}, io.BytesIO(b'{"retry_after":90}')))
        self.assertEqual(self.send()['status'], 'retry')
        self.assertEqual(self.send(now=self.now+timedelta(seconds=60))['status'], 'retry')
        self.assertEqual(self.sender.call_count, 1)
        self.send(now=self.now+timedelta(seconds=100))
        self.assertEqual(self.send(now=self.now+timedelta(seconds=200))['status'], 'failed')
        self.send(now=self.now+timedelta(seconds=500))
        self.assertEqual(self.sender.call_count, 3)

    def test_different_ai_venue_day_and_race_have_independent_receipts(self):
        for key in [self.key, 'mid_odds:20261003:22:5', 'normal:20261003:24:5',
                    'normal:20261003:22:6', 'normal:20261004:22:5', 'yuuki:20261003:22:5']:
            self.send(key)
        self.assertEqual(self.sender.call_count, 6)

    def test_receipt_store_unavailable_prevents_discord_send(self):
        self.store.read = Mock(side_effect=OSError())
        with self.assertRaises(OSError):
            self.send()
        self.sender.assert_not_called()

    def test_send_uses_confirmed_ack_without_changing_prediction_destination(self):
        response = Mock()
        response.read.return_value = b'{"id":"987654"}'
        with patch.dict(os.environ, {'DISCORD_HIT_WEBHOOK_URL':'https://example.test/hook?thread_id=1',
                                     'DISCORD_WEBHOOK_URL':'original'}), patch('urllib.request.urlopen') as http:
            http.return_value.__enter__.return_value = response
            self.assertEqual(delivery.send_confirmed('速報'), {'id':'987654'})
            self.assertIn('wait=true', http.call_args.args[0].full_url)
            self.assertIn('thread_id=1', http.call_args.args[0].full_url)
            self.assertEqual(os.environ['DISCORD_WEBHOOK_URL'], 'original')

    def test_key_rejects_invalid_venue_race_and_paths(self):
        for key in ['normal:20261003:25:1', 'normal:20261003:24:13', '../secret']:
            with self.assertRaises(ValueError):
                delivery.ReceiptStore.path(key)


if __name__ == '__main__':
    unittest.main()
