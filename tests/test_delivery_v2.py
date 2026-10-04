import unittest
from unittest.mock import patch
import json

from delivery_v2.discord_sender import DeliveryError, post_confirmed


class Response:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return json.dumps({"id":"123456789"}).encode()


class DiscordSenderTest(unittest.TestCase):
    def test_requires_webhook(self):
        with self.assertRaises(DeliveryError):
            post_confirmed("", "x")

    @patch("urllib.request.urlopen", return_value=Response())
    def test_waits_for_message_id(self, mocked):
        self.assertEqual(post_confirmed("https://example.invalid/webhook", "hello"), "123456789")
        self.assertIn("wait=true", mocked.call_args.args[0].full_url)


if __name__ == "__main__":
    unittest.main()
