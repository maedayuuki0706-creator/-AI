import io
import json
import unittest
from unittest.mock import patch

from discord_ack import post


class DiscordAckTests(unittest.TestCase):
    def test_preserves_thread_and_notification_policy_and_requires_id(self):
        payload = {'content': '予想', 'allowed_mentions': {'parse': []}, 'flags': 4096}
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'{"id":"123456789"}')) as http:
            self.assertEqual(post('https://example.test/hook?thread_id=12&wait=false', payload), '123456789')
        request = http.call_args.args[0]
        self.assertIn('thread_id=12', request.full_url)
        self.assertIn('wait=true', request.full_url)
        self.assertEqual(json.loads(request.data), payload)

    def test_missing_or_invalid_id_is_not_success(self):
        for value in ({}, {'id': 'invalid'}, [], None):
            with self.subTest(value=value), patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(value).encode())):
                with self.assertRaises(RuntimeError):
                    post('https://example.test/hook', {'content': 'x'})

    def test_timeout_is_not_blindly_retried(self):
        with patch('urllib.request.urlopen', side_effect=TimeoutError()) as http:
            with self.assertRaises(TimeoutError):
                post('https://example.test/hook', {'content': 'x'})
        http.assert_called_once()


if __name__ == '__main__':
    unittest.main()
