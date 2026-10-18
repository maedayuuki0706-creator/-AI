"""Live HTTP contract smoke test without contacting BOAT RACE or using Secrets."""
from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen
from unittest.mock import patch

from research.website_schedule import schedule_server as app


class PublicScheduleServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def get_json(self, endpoint):
        try:
            with urlopen(self.base + endpoint, timeout=3) as response:
                return response.status, json.load(response), response.headers
        except HTTPError as error:
            return error.code, json.load(error), error.headers

    def test_health(self):
        status, body, headers = self.get_json("/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")

    def test_no_other_legacy_routes(self):
        status, body, _ = self.get_json("/today.json")
        self.assertEqual(status, 404)
        self.assertFalse(body["ok"])

    def test_schedule_uses_cached_source_with_correct_day(self):
        expected = {"races": [{"jcd": "03", "rno": 5, "deadline": "13:15"}]}
        with patch.object(app, "schedule_snapshot", return_value=expected) as mocked:
            status, body, _ = self.get_json("/schedule.json")
        self.assertEqual(status, 200)
        self.assertEqual(body, expected)
        self.assertEqual(len(mocked.call_args.args[0]), 8)

    def test_invalid_date_is_400_not_current_date_substitution(self):
        with patch.object(app, "schedule_snapshot") as mocked:
            status, _, _ = self.get_json("/schedule.json?date=20261395")
        self.assertEqual(status, 400)
        mocked.assert_not_called()

    def test_upstream_failure_is_explicit_503(self):
        with patch.object(app, "schedule_snapshot", side_effect=TimeoutError("official timeout")):
            status, body, _ = self.get_json("/schedule.json")
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "official deadline source unavailable")


if __name__ == "__main__":
    unittest.main()
