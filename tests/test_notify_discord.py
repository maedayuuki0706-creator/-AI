import contextlib
import io
import json
import os
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import notify_discord as notifier


COLLECTION = {"ok": True, "date": "2026-09-09", "total": 144, "venues": 12}
DELIVERY = {"ok": True, "eligible": 2, "sent": 1, "skipped": 1, "failed": 0, "analysisFailures": 0}
UNPUBLISHED = {"error": "この日のレースデータはまだ公開されていません", "date": "2026-09-10"}


class Response(io.BytesIO):
    def __init__(self, payload, content_type="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        super().__init__(body)
        self.headers = {"Content-Type": content_type}


def http_error(payload, code=404, path="/api/races"):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return urllib.error.HTTPError(notifier.SITE_URL + path, code, "error", {}, io.BytesIO(body))


class NotifierTests(unittest.TestCase):
    def run_case(self, responses, args=None, token="test-token"):
        with patch.dict(os.environ, {"NOTIFICATION_RUN_TOKEN": token}):
            with patch.object(notifier.urllib.request, "build_opener") as build:
                build.return_value.open.side_effect = responses
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = notifier.main(args or [])
                calls = build.return_value.open.call_args_list
        return result, output.getvalue(), calls

    def test_published_races_trigger_authenticated_notification_once(self):
        result, output, calls = self.run_case([Response(COLLECTION), Response(DELIVERY)])
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].args[0].full_url, notifier.SITE_URL + "/api/races")
        self.assertIsNone(calls[0].args[0].get_header("Authorization"))
        self.assertEqual(calls[1].args[0].get_header("Authorization"), "Bearer test-token")
        self.assertIn("sent=1", output)

    def test_midnight_unpublished_response_skips_notifications_successfully(self):
        result, output, calls = self.run_case([http_error(UNPUBLISHED)])
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn("公開待ち", output)
        self.assertIn("2026-09-10", output)

    def test_known_no_meeting_response_is_also_a_normal_skip(self):
        result, _, calls = self.run_case([http_error({**UNPUBLISHED, "error": "開催レースが見つかりませんでした"})])
        self.assertEqual((result, len(calls)), (0, 1))

    def test_unrelated_404_or_bad_date_remains_failure(self):
        for payload in [b"<html>Not found</html>", {"error": "Not found"}, {**UNPUBLISHED, "date": "2026-99-99"}]:
            with self.subTest(payload=payload):
                result, _, calls = self.run_case([http_error(payload)])
                self.assertEqual((result, len(calls)), (1, 1))

    def test_notification_404_is_not_mistaken_for_unpublished_races(self):
        result, _, calls = self.run_case([Response(COLLECTION), http_error(UNPUBLISHED, path="/api/notifications")])
        self.assertEqual((result, len(calls)), (1, 2))

    def test_login_html_or_malformed_json_is_not_success(self):
        for response in [Response(b"<html>Sign in</html>", "text/html"), Response(b"not-json"), Response([])]:
            with self.subTest(response=response):
                result, _, calls = self.run_case([response])
                self.assertEqual((result, len(calls)), (1, 1))

    def test_auth_error_is_not_retried_or_exposed(self):
        result, output, calls = self.run_case([Response(COLLECTION), http_error({"error": "test-token"}, code=401)])
        self.assertEqual((result, len(calls)), (1, 2))
        self.assertNotIn("test-token", output)

    def test_collection_failure_never_sends_notifications(self):
        for payload in [{"ok": False}, {"ok": True}, {**COLLECTION, "total": "144"}]:
            with self.subTest(payload=payload):
                result, _, calls = self.run_case([Response(payload)])
                self.assertEqual((result, len(calls)), (1, 1))

    def test_partial_analysis_or_delivery_failure_is_reported(self):
        for delivery in [{**DELIVERY, "failed": 1}, {**DELIVERY, "analysisFailures": 1}, {**DELIVERY, "ok": False}]:
            with self.subTest(delivery=delivery):
                result, _, _ = self.run_case([Response(COLLECTION), Response(delivery)])
                self.assertEqual(result, 1)

    def test_check_needs_no_token_and_never_calls_notifications(self):
        result, output, calls = self.run_case([Response(COLLECTION)], args=["--check"], token="")
        self.assertEqual((result, len(calls)), (0, 1))
        self.assertIn("Discord送信なし", output)

    def test_missing_run_token_fails_before_network_access(self):
        result, _, calls = self.run_case([], token="")
        self.assertEqual((result, len(calls)), (2, 0))

    def test_http_redirect_does_not_forward_authorization(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/login")
                self.end_headers()

            def do_GET(self):
                requests.append(self.path)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            with patch.object(notifier, "SITE_URL", f"http://127.0.0.1:{server.server_port}"):
                with self.assertRaises(notifier.ApiError) as caught:
                    notifier.post_json("/api/notifications", "test-token")
            self.assertEqual(caught.exception.status, 302)
            self.assertEqual(requests, ["/api/notifications"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
