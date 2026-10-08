"""Offline regression tests: never send an actual X or Discord post."""
import copy
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import contextlib
import unittest
from unittest.mock import patch
import urllib.error

import api_server as api
import x_post_delivery as delivery
import x_delivery_policy as policy
import x_delivery_store as store
from x_api_client import XPostRejected
from discord_formation import expand_formation

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=policy.JST)
DAY = "20261002"
KEY = f"{DAY}:08:1"
COMMIT = "a" * 40
ATTEMPT = "b" * 32


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


def row(**overrides):
    return {"day": DAY, "jcd": "08", "rno": 1, "venue": "常滑",
            "deadline": "12:12", "source": "厳選くん", "resend": False,
            "sent_at": NOW.isoformat(), "post": "常滑 1R\n1-234-234\nぜひフォローお願いします！",
            "main": ["1-2-3", "1-2-4", "1-3-2", "1-3-4", "1-4-2", "1-4-3"],
            **overrides}


class Response:
    def __init__(self, value):
        self.value = value
        self.status = 200
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return json.dumps(self.value).encode()


class XDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (patch.object(delivery, "STATE_DIR", Path(self.tmp.name) / "outbox"),
                  # Legacy integration is intentionally disabled in production to avoid
                  # competing with X Delivery V2. Enable only inside offline tests.
                  patch.object(delivery, "STANDARD_X_FEED_ENABLED", True),
                  patch.object(delivery, "datetime", Clock), patch.object(policy, "datetime", Clock),
                  patch.dict(os.environ, {}, clear=True),
                  contextlib.redirect_stdout(io.StringIO()),
                  patch("urllib.request.urlopen", side_effect=AssertionError("unexpected network"))):
            self.enterContext(p)
        delivery._RECEIPTS_DIRTY.clear()
        delivery._REPORTED_BLOCKS.clear()
        api._X_SYNC_POSTED.clear()
        api._X_SYNC_UNCERTAIN.clear()
        api._X_RESULT_POSTED.clear()
        api._X_RESULT_UNCERTAIN.clear()
        self.remote = {}
        self.archived = ""

    def bridge(self, mode="ok"):
        def publish_archive(day, text):
            self.archived = text
            return COMMIT
        def publish_state(day, state):
            self.remote = store.merge_state(self.remote, copy.deepcopy(state))
            return copy.deepcopy(self.remote), COMMIT
        def raw(path, ref):
            self.assertEqual(ref, COMMIT)
            return self.archived if path.endswith("jsonl") else json.dumps(self.remote)
        def transport(request, **kwargs):
            if request.full_url.endswith("/x-status"):
                return Response({"delivery_version": 2, "credentials_configured": True})
            payload = json.loads(request.data)
            if mode == "reject":
                return Response({"ok": False, "definitely_not_posted": True, "retryable": False})
            if mode == "retry":
                return Response({"ok": False, "definitely_not_posted": True, "retryable": True})
            result = api.sync_archived_prediction_to_x(**payload)
            if mode == "lost_response":
                raise TimeoutError("response lost after accepted post")
            return Response(result)
        patches = [patch.object(store, "configured", return_value=True),
                   patch.object(store, "load_state", side_effect=lambda day: copy.deepcopy(self.remote)),
                   patch.object(store, "publish_archive", side_effect=publish_archive),
                   patch.object(store, "publish_state", side_effect=publish_state),
                   patch.object(api, "_raw_text", side_effect=raw),
                   patch("urllib.request.urlopen", side_effect=transport),
                   patch.object(api, "post_to_x", return_value="123456789"),
                   patch.object(delivery, "_send_discord")]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        return mocks[-2], mocks[-1]

    def reserve(self):
        return {"x_attempts": {KEY: {"id": ATTEMPT, "status": "reserved"}}}

    def test_deadlines_freshness_sources_and_dates_fail_closed(self):
        policy.validate_live_row(row())
        policy.validate_live_row(row(deadline="12:10"))  # exact ten-minute boundary is allowed
        for overrides in ({"deadline": "12:09"}, {"deadline": "12:00"}, {"deadline": "--:--"}, {"deadline": "bad"},
                          {"day": "20261001"}, {"source": "穴くん"}, {"resend": True},
                          {"sent_at": (NOW - timedelta(minutes=16)).isoformat()},
                          {"sent_at": (NOW + timedelta(minutes=2)).isoformat()},
                          {"sent_at": "2026-10-02T12:00:00"}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                policy.validate_live_row(row(**overrides))
        with self.assertRaises(ValueError):
            policy.validate_live_row(row(), now=NOW.replace(minute=9, second=30))

    def test_japanese_weight_and_no_silent_ticket_truncation(self):
        self.assertEqual(policy.weighted_length("aあ🚤"), 5)
        self.assertEqual(policy.weighted_length("あ" * 141), 282)
        with self.assertRaises(ValueError):
            delivery._fit_post(["あ" * 141])

    def test_format_preserves_all_tickets_and_follow_invitation(self):
        post = delivery._build_post("ボートレースびわこ", 12, "12:10", row()["main"], label="厳選くん")
        self.assertIn("フォローお願いします", post)
        self.assertNotIn("#", post)
        self.assertLessEqual(policy.weighted_length(post), 280)
        expanded = set()
        for line in post.splitlines():
            if line and line[0].isdigit():
                expanded.update(expand_formation(line))
        self.assertEqual(expanded, set(row()["main"]))

    def test_archive_makes_directory_and_preserves_first_card(self):
        delivery._archive_post(row(), "厳選くん", "first")
        delivery._archive_post(row(), "厳選中穴", "second")
        saved = (delivery.STATE_DIR / f"{DAY}_posts.jsonl").read_text().splitlines()
        self.assertEqual(len(saved), 1)
        self.assertEqual(json.loads(saved[0])["post"], "first")

    def test_selected_prediction_posts_immediately_and_persists_receipt(self):
        post, mirror = self.bridge()
        self.assertTrue(delivery.send_selected_record(row()))
        post.assert_called_once()
        mirror.assert_called_once()
        self.assertEqual(self.remote["x_post_ids"][KEY], "123456789")
        self.assertEqual(self.remote["x_attempts"], {})
        self.assertIn(KEY, delivery._load(DAY)["x_posted_races"])

    def test_server_and_runner_restart_do_not_duplicate_confirmed_post(self):
        post, _ = self.bridge()
        delivery.send_selected_record(row())
        api._X_SYNC_POSTED.clear()
        delivery._state_path(DAY).unlink()
        self.assertEqual(delivery.sync_archived_via_render(DAY), 0)
        post.assert_called_once()

    def test_discord_outage_does_not_prevent_x_receipt(self):
        post, mirror = self.bridge()
        mirror.side_effect = RuntimeError("Discord unavailable")
        with self.assertRaises(RuntimeError):
            delivery.send_selected_record(row())
        post.assert_called_once()
        self.assertIn(KEY, self.remote["x_posted_races"])

    def test_x_outage_keeps_discord_mirror_and_archived_prediction(self):
        with patch.object(store, "configured", return_value=True), \
             patch.object(delivery, "sync_archived_via_render", side_effect=RuntimeError("outage")), \
             patch.object(delivery, "_send_discord") as mirror:
            self.assertTrue(delivery.send_selected_record(row()))
        mirror.assert_called_once()
        self.assertTrue((delivery.STATE_DIR / f"{DAY}_posts.jsonl").exists())

    def test_lost_response_is_held_across_restarts(self):
        post, _ = self.bridge("lost_response")
        delivery.send_selected_record(row())
        self.assertEqual(self.remote["x_attempts"][KEY]["status"], "uncertain")
        api._X_SYNC_POSTED.clear()
        delivery._state_path(DAY).unlink()
        delivery.sync_archived_via_render(DAY)
        post.assert_called_once()
        self.assertNotIn(KEY, self.remote["x_posted_races"])

    def test_permission_rejection_never_marks_success(self):
        post, mirror = self.bridge("reject")
        delivery.send_selected_record(row())
        self.assertEqual(self.remote["x_attempts"][KEY]["status"], "blocked")
        self.assertNotIn(KEY, self.remote["x_posted_races"])
        post.assert_not_called()
        mirror.assert_called_once()

    def test_retryable_rejection_waits_before_retry(self):
        post, _ = self.bridge("retry")
        delivery.send_selected_record(row())
        self.assertEqual(self.remote["x_attempts"][KEY]["status"], "retryable")
        saved = copy.deepcopy(self.remote)
        delivery.sync_archived_via_render(DAY)
        self.assertEqual(saved["x_attempts"], self.remote["x_attempts"])
        post.assert_not_called()

    def test_expired_archive_never_reaches_render(self):
        delivery._archive_post(row(deadline="11:59"), "厳選くん", "post")
        with patch.object(delivery, "check_render_ready") as ready:
            self.assertEqual(delivery.sync_archived_via_render(DAY), 0)
        ready.assert_not_called()


    def test_result_reply_uses_decimal_odds_and_original_post(self):
        state = {
            "x_posted_races": [KEY],
            "x_post_ids": {KEY: "2105651010316488732"},
            "x_result_attempts": {KEY: {"id": ATTEMPT, "status": "reserved"}},
        }
        archived = row(deadline="11:50", picks=["3-1-4"],
                       post="常滑 1R\n3-1-4\nぜひフォローお願いします！")
        with patch.object(api, "_x_sync_state", return_value=state), \
             patch.object(api, "_x_archive_post_row", return_value=archived), \
             patch.object(api, "_load_official_result", return_value={
                 "status": "settled", "payouts": {"3-1-4": 3940}, "refund_lanes": []
             }), \
             patch.object(api, "post_to_x", return_value="999") as post:
            result = api.sync_archived_result_to_x(DAY, "08", 1, COMMIT, ATTEMPT)
        self.assertTrue(result["hit"])
        self.assertEqual(result["odds"], 39.4)
        text_arg = post.call_args.args[0]
        self.assertIn("39.4倍", text_arg)
        self.assertNotIn("3,940円", text_arg)
        self.assertEqual(post.call_args.kwargs["reply_to"], "2105651010316488732")

    def test_result_miss_is_still_published(self):
        state = {
            "x_posted_races": [KEY],
            "x_post_ids": {KEY: "2105651010316488732"},
            "x_result_attempts": {KEY: {"id": ATTEMPT, "status": "reserved"}},
        }
        with patch.object(api, "_x_sync_state", return_value=state), \
             patch.object(api, "_x_archive_post_row", return_value=row(deadline="11:50", picks=["1-2-3"])), \
             patch.object(api, "_load_official_result", return_value={
                 "status": "settled", "payouts": {"3-1-4": 3940}, "refund_lanes": []
             }), \
             patch.object(api, "post_to_x", return_value="1000") as post:
            result = api.sync_archived_result_to_x(DAY, "08", 1, COMMIT, ATTEMPT)
        self.assertFalse(result["hit"])
        self.assertIn("❌ 不的中", post.call_args.args[0])
        self.assertIn("39.4倍", post.call_args.args[0])

    def test_server_uses_same_post_id_for_duplicate_attempt(self):
        with patch.object(api, "_x_sync_state", return_value=self.reserve()), \
             patch.object(api, "_x_sync_post_row", return_value=row()), \
             patch.object(api, "post_to_x", return_value="987") as post:
            first = api.sync_archived_prediction_to_x(DAY, "08", 1, COMMIT, ATTEMPT)
            second = api.sync_archived_prediction_to_x(DAY, "08", 1, COMMIT, ATTEMPT)
        self.assertFalse(first["already"])
        self.assertTrue(second["already"])
        self.assertEqual(second["post_id"], "987")
        post.assert_called_once()

    def test_server_rechecks_deadline_after_reading_archive(self):
        with patch.object(api, "_x_sync_state", return_value=self.reserve()), \
             patch.object(api, "_x_sync_post_row", return_value=row(deadline="11:59")), \
             patch.object(api, "post_to_x") as post, self.assertRaises(ValueError):
            api.sync_archived_prediction_to_x(DAY, "08", 1, COMMIT, ATTEMPT)
        post.assert_not_called()

    def test_state_read_failure_never_posts(self):
        with patch.object(api, "_raw_text", side_effect=api.XArchiveUnavailable("offline")), \
             patch.object(api, "post_to_x") as post, self.assertRaises(api.XArchiveUnavailable):
            api.sync_archived_prediction_to_x(DAY, "08", 1, COMMIT, ATTEMPT)
        post.assert_not_called()

    def test_unreserved_requests_are_rejected(self):
        with patch.object(api, "_x_sync_state", return_value={}), \
             patch.object(api, "post_to_x") as post, self.assertRaises(ValueError):
            api.sync_archived_prediction_to_x(DAY, "08", 1, COMMIT, ATTEMPT)
        post.assert_not_called()

    def test_receipt_merge_retains_all_confirmed_races(self):
        result = store.merge_state({"x_posted_races": [KEY], "x_post_ids": {KEY: "1"}},
                                   {"x_posted_races": ["other"], "x_attempts": {KEY: {"status": "reserved"}}})
        self.assertEqual(set(result["x_posted_races"]), {KEY, "other"})
        self.assertEqual(result["x_post_ids"][KEY], "1")
        self.assertNotIn(KEY, result["x_attempts"])

    def test_slow_x_does_not_hold_discord_delivery(self):
        entered, release = threading.Event(), threading.Event()
        def slow(day):
            entered.set()
            release.wait(3)
        with patch.dict(os.environ, {"X_ASYNC_DELIVERY": "1"}), \
             patch.object(store, "configured", return_value=True), \
             patch.object(delivery, "check_render_ready", return_value={}), \
             patch.object(delivery, "sync_archived_via_render", side_effect=slow), \
             patch.object(delivery, "_send_discord") as mirror:
            try:
                delivery.send_selected_record(row())
                self.assertTrue(entered.wait(1))
                mirror.assert_called_once()
                self.assertFalse(release.is_set())
            finally:
                release.set()
                delivery.flush_pending(5)

    def test_stale_mirror_save_cannot_erase_post_receipt(self):
        delivery._save(DAY, {"x_posted_races": [KEY], "x_post_ids": {KEY: "123"}})
        delivery._save(DAY, {"sent_races": [KEY], "x_posted_races": []})
        state = delivery._load(DAY)
        self.assertIn(KEY, state["x_posted_races"])
        self.assertEqual(state["x_post_ids"][KEY], "123")

    def test_store_retries_sha_conflict_without_overwriting_receipts(self):
        conflict = urllib.error.HTTPError("test", 409, "conflict", {}, io.BytesIO())
        with patch.object(store, "_ensure_branch"), \
             patch.object(store, "_read", side_effect=[("{}", "old"), (json.dumps({"x_posted_races": [KEY]}), "new")]), \
             patch.object(store, "_request", side_effect=[conflict, {"commit": {"sha": COMMIT}}]) as request:
            merged, commit = store.publish_state(DAY, {"x_posted_races": ["other"]})
        self.assertEqual(set(merged["x_posted_races"]), {KEY, "other"})
        self.assertEqual(request.call_args.args[1]["sha"], "new")
        self.assertEqual(commit, COMMIT)


if __name__ == "__main__":
    unittest.main()
