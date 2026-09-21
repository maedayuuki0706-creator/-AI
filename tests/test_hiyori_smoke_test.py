import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import hiyori_smoke_test as test


class HiyoriSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.receipts = patch.object(test, 'RECEIPTS', Path(self.tmp.name))
        self.receipts.start()
        self.addCleanup(self.receipts.stop)
        self.env = patch.dict(test.os.environ, {'HIYORI_DISCORD_WEBHOOK_URL': 'https://discord.com/api/webhooks/123/test-token'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def opener(self, *responses):
        return Mock(side_effect=[io.BytesIO(json.dumps(r).encode()) for r in responses])

    def test_real_post_is_silent_acknowledged_and_not_repeated(self):
        opener = self.opener({'channel_id': '456'}, {'id': '789', 'channel_id': '456'})
        receipt = test.send('test-1', opener=opener)
        self.assertEqual(test.send('test-1', opener=opener), receipt)
        self.assertEqual(opener.call_count, 2)
        post = opener.call_args_list[1].args[0]
        self.assertEqual(post.method, 'POST')
        self.assertIn('wait=true', post.full_url)
        payload = json.loads(post.data)
        self.assertIn('日和AI', payload['content'])
        self.assertEqual(payload['allowed_mentions'], {'parse': []})
        self.assertEqual(payload['flags'], 4096)
        self.assertNotIn('test-token', json.dumps(receipt))

    def test_missing_hiyori_secret_never_falls_back_to_main(self):
        with patch.dict(test.os.environ, {'DISCORD_WEBHOOK_URL': 'https://discord.com/api/webhooks/111/other'}, clear=True):
            opener = Mock()
            with self.assertRaisesRegex(RuntimeError, 'HIYORI_DISCORD_WEBHOOK_URL is not configured'):
                test.send('missing', opener=opener)
            opener.assert_not_called()

    def test_wrong_channel_or_missing_message_id_is_not_success(self):
        for response in ({'id': '789', 'channel_id': '999'}, {'channel_id': '456'}):
            with self.assertRaises(RuntimeError):
                test.send('failure', opener=self.opener({'channel_id': '456'}, response))
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_post_timeout_does_not_create_a_success_receipt(self):
        opener = Mock(side_effect=[io.BytesIO(b'{"channel_id":"456"}'), TimeoutError])
        with self.assertRaises(RuntimeError):
            test.send('timeout', opener=opener)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
