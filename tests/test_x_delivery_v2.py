import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import Mock, patch

import api_server
import x_delivery_store
import x_featured_selector as selector
import x_post_delivery as formatter
from x_delivery_policy import JST, weighted_length
from x_delivery_v2 import dispatcher
from x_delivery_v2.store import Store, key, receipt_key


class MemoryStore(Store):
    def __init__(self):
        self.states, self.archives, self.reports = {}, {}, {}
        self.lock = threading.RLock()

    def state(self, day):
        with self.lock:
            return copy.deepcopy(self.states.get(day, {}))

    def update(self, day, change):
        with self.lock:
            self.states[day] = change(self.state(day))
            return self.state(day), "a"*40

    def publish(self, row):
        with self.lock:
            self.archives.setdefault(row["day"], {}).setdefault(key(row), copy.deepcopy(row))
            return copy.deepcopy(self.archives[row["day"]][key(row)])

    def archive(self, day):
        return copy.deepcopy(self.archives.get(day, {}))

    def report(self, day, value):
        self.reports[day] = copy.deepcopy(value)


class XProductionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        p = patch.object(dispatcher, "RECOVERY", self.root/"recovery")
        p.start(); self.addCleanup(p.stop)
        p = patch.dict(os.environ, {"X_DELIVERY_SOURCE_COMMIT":"b"*40})
        p.start(); self.addCleanup(p.stop)
        self.now = datetime(2026, 10, 6, 13, 0, tzinfo=JST)
        self.store = MemoryStore()
        self.sender = Mock(return_value={"ok":True, "post_id":"1234567890123456789"})
        self.row = {"day":"20261006", "jcd":"05", "rno":1, "venue":"多摩川", "deadline":"13:30",
                    "source":"AI重なり本線", "post":"多摩川1R\n1-23-23", "picks":["1-2-3","1-3-2"],
                    "sent_at":self.now.isoformat(), "resend":False}
        self.store.publish(self.row)

    def send(self, row=None, phase="prediction", **kw):
        return dispatcher.deliver(row or self.row, phase, store=kw.pop("store",self.store),
                                  clock=lambda:self.now, transport=self.sender, **kw)

    def test_claim_ack_archive_and_restart_guard_verify_without_another_post(self):
        self.assertEqual(self.send()["status"], "sent")
        self.assertEqual(self.send()["status"], "already_sent")
        self.sender.assert_called_once()
        proof = dispatcher.verify(self.store.state(self.row["day"]), self.store.archive(self.row["day"]))
        self.assertTrue(proof[0]["verified"])
        receipt = self.store.state(self.row["day"])["x_v2_receipts"][receipt_key(self.row,"prediction")]
        self.assertEqual(receipt["content_sha256"], hashlib.sha256(self.row["post"].encode()).hexdigest())

    def test_two_producers_send_the_same_race_only_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _:self.send(), range(2)))
        self.sender.assert_called_once()

    def test_github_compare_and_swap_conflict_preserves_the_other_claim(self):
        raced={"x_attempts":{key(self.row):{"id":"another-owner","status":"reserved","attempt":1}}}
        def request(path, payload=None, **kw):
            if kw.get("method") == "PUT":
                raise urllib.error.HTTPError(path,409,"conflict",{},None)
            return {"object":{"sha":"c"*40}}
        with patch.object(x_delivery_store,"_ensure_branch"), \
             patch.object(x_delivery_store,"load_state",return_value={}), \
             patch.object(x_delivery_store,"_read",side_effect=[("","old-sha"),(json.dumps(raced,ensure_ascii=False,sort_keys=True,indent=2)+"\n","new-sha")]), \
             patch.object(x_delivery_store,"_request",side_effect=request), \
             patch.object(x_delivery_store.time,"sleep"):
            result=self.send(store=Store())
        self.assertEqual(result["status"],"reserved")
        self.sender.assert_not_called()

    def test_timeout_and_invalid_post_id_are_held_across_restart(self):
        for response in [TimeoutError(), {"ok":True}, {"ok":True,"post_id":"not-an-id"}]:
            with self.subTest(response=response):
                self.store = MemoryStore(); self.store.publish(self.row)
                self.sender = Mock(side_effect=response) if isinstance(response,Exception) else Mock(return_value=response)
                self.assertEqual(self.send()["status"], "uncertain")
                self.assertEqual(self.send()["status"], "uncertain")
                self.sender.assert_called_once()

    def test_persistence_failure_after_ack_keeps_recovery_and_blocks_repost(self):
        real = self.store.finish
        def finish(row, phase, owner, outcome, now):
            if outcome["status"] == "sent":
                raise OSError("persistence unavailable")
            return real(row,phase,owner,outcome,now)
        with patch.object(self.store,"finish",side_effect=finish), self.assertRaises(OSError):
            self.send()
        self.assertEqual(self.send()["status"], "sending")
        self.sender.assert_called_once()
        proof = json.loads(next(dispatcher.RECOVERY.glob("*.json")).read_text())
        self.assertEqual(proof["post_id"], "1234567890123456789")

    def test_local_recovery_failure_still_saves_numeric_ack_to_state(self):
        with patch.object(Path,"mkdir",side_effect=OSError("disk unavailable")):
            self.assertEqual(self.send()["status"],"sent")
        self.assertEqual(self.send()["status"],"already_sent")
        self.sender.assert_called_once()

    def test_late_ack_is_saved_but_does_not_report_verified_production(self):
        def slow(phase, body):
            self.now += timedelta(minutes=21)
            return {"ok":True,"post_id":"1234567890123456789"}
        with patch.object(dispatcher,"candidate_row",return_value=self.row):
            report=dispatcher.run_once(store=self.store,clock=lambda:self.now,transport=slow,
                candidates=[{"key":key(self.row)}],ready=Mock())
        self.assertEqual(report["status"],"degraded")
        self.assertEqual(report["production_verification"],[])
        self.assertEqual(report["errors"][0]["stage"],"verification")
        self.assertEqual(self.send()["status"],"already_sent")

    def test_definite_rejection_retries_three_times_and_not_more(self):
        self.sender.return_value = {"ok":False,"definitely_not_posted":True,"retryable":True}
        self.assertEqual(self.send()["status"],"retry")
        self.send(); self.assertEqual(self.sender.call_count,1)
        self.now += timedelta(seconds=61)
        self.assertEqual(self.send()["status"],"retry")
        self.now += timedelta(seconds=61)
        self.assertEqual(self.send()["status"],"failed")
        self.now += timedelta(seconds=61)
        self.assertEqual(self.send()["status"],"failed")
        self.assertEqual(self.sender.call_count,3)

    def test_late_wakeup_never_sends_a_prediction_inside_ten_minutes(self):
        self.now += timedelta(minutes=20)
        self.assertEqual(self.send()["status"],"expired")
        self.sender.assert_not_called()

    def test_slow_claim_rechecks_safety_margin_before_calling_render(self):
        original=self.store.claim
        def slow(*args,**kw):
            saved=original(*args,**kw)
            self.now += timedelta(minutes=19,seconds=30)
            return saved
        with patch.object(self.store,"claim",side_effect=slow):
            self.assertEqual(self.send()["status"],"expired")
        self.sender.assert_not_called()

    def test_daily_quota_includes_inflight_and_confirmed_claims(self):
        rows=[{**self.row,"rno":r} for r in range(1,12)]
        for row in rows:
            self.store.publish(row)
            self.send(row)
        self.assertEqual(self.sender.call_count,10)
        self.assertEqual(len(self.store.state("20261006")["x_featured_races"]),10)

    def test_result_requires_confirmed_prediction_id_and_does_not_repost_prediction(self):
        self.now += timedelta(minutes=31)
        self.assertEqual(self.send(phase="result")["status"],"not_due")
        self.sender.assert_not_called()
        race=key(self.row)
        self.store.states[self.row["day"]]={"x_posted_races":[race],"x_post_ids":{race:"2345678901234567890"}}
        receipt=self.send(phase="result")
        self.assertEqual(receipt["parent_post_id"],"2345678901234567890")
        self.assertEqual(self.sender.call_args.args[0],"result")

    def test_official_result_wait_does_not_exhaust_network_retry_budget(self):
        self.now += timedelta(minutes=31)
        race=key(self.row)
        self.store.states[self.row["day"]]={"x_posted_races":[race],"x_post_ids":{race:"2345678901234567890"}}
        self.sender.return_value={"ok":False,"error":"official result pending","definitely_not_posted":True,"retryable":True}
        for _ in range(6):
            self.assertEqual(self.send(phase="result")["status"],"waiting_result")
            self.now += timedelta(seconds=31)
        self.assertEqual(self.sender.call_count,6)

    def test_official_void_result_is_delivered_once_with_acknowledgement(self):
        self.now += timedelta(minutes=31)
        race = key(self.row)
        self.store.states[self.row["day"]] = {
            "x_posted_races": [race],
            "x_post_ids": {race: "2345678901234567890"},
        }
        self.sender.return_value = {"ok": True, "post_id": "1234567890123456789",
                                    "winner": "不成立", "odds": None, "hit": None, "void": True}
        report = dispatcher.run_once(store=self.store, clock=lambda:self.now,
                                      transport=self.sender, candidates=[], ready=Mock())
        self.assertEqual(report["counts"], {"sent": 1})
        self.assertEqual(report["status"], "checked")
        self.assertEqual(self.store.state(self.row["day"])["x_result_post_ids"][race], "1234567890123456789")
        self.assertEqual(self.sender.call_args.args[0], "result")
        dispatcher.run_once(store=self.store, clock=lambda:self.now,
                            transport=self.sender, candidates=[], ready=Mock())
        self.sender.assert_called_once()

    def test_midnight_catchup_publishes_only_previous_days_pending_result(self):
        self.now=datetime(2026,10,7,0,3,tzinfo=JST)
        race=key(self.row)
        self.store.states[self.row["day"]]={"x_posted_races":[race],"x_post_ids":{race:"2345678901234567890"}}
        report=dispatcher.run_once(store=self.store,clock=lambda:self.now,transport=self.sender,
                                   candidates=[],ready=Mock())
        self.assertEqual(self.sender.call_args.args[0],"result")
        self.assertEqual(report["counts"],{"sent":1})
        self.assertTrue(report["production_verification"][0]["restart_duplicate_guard_verified"])
        dispatcher.run_once(store=self.store,clock=lambda:self.now,transport=self.sender,candidates=[],ready=Mock())
        self.sender.assert_called_once()

    def test_native_receipt_does_not_verify_against_a_changed_archive(self):
        self.send()
        self.store.archives[self.row["day"]][key(self.row)]["post"]="changed"
        with self.assertRaises(ValueError):
            dispatcher.verify(self.store.state(self.row["day"]),self.store.archive(self.row["day"]))

    def test_legacy_checkpoint_does_not_erase_newer_native_receipt(self):
        self.send()
        remote=self.store.state(self.row["day"])
        stale=copy.deepcopy(remote)
        stale["x_v2_receipts"][receipt_key(self.row,"prediction")]["status"]="sending"
        stale["x_post_ids"][key(self.row)]="wrong"
        merged=x_delivery_store.merge_state(remote,stale)
        self.assertEqual(merged["x_v2_receipts"][receipt_key(self.row,"prediction")]["status"],"sent")
        self.assertEqual(merged["x_post_ids"][key(self.row)],"1234567890123456789")

    def test_stale_legacy_checkpoint_cannot_release_a_native_reserved_claim(self):
        remote,_=self.store.claim(self.row,"prediction","native-owner",self.now)
        stale={"x_attempts":{key(self.row):{"id":"old-owner","status":"retryable","attempt":1}}}
        merged=x_delivery_store.merge_state(remote,stale)
        self.assertEqual(merged["x_attempts"][key(self.row)]["id"],"native-owner")
        self.assertEqual(merged["x_attempts"][key(self.row)]["status"],"reserved")

    def test_idle_is_reported_without_any_post_or_backend_probe(self):
        ready=Mock()
        report=dispatcher.run_once(store=self.store,clock=lambda:self.now,transport=self.sender,
                                   candidates=[],ready=ready)
        self.assertEqual(report["status"],"checked")
        self.assertEqual(report["production_verification"],[])
        self.sender.assert_not_called(); ready.assert_not_called()

    def test_candidate_uses_exact_original_refs_and_rejects_stale_source(self):
        p12=self.root/"p12"; p3=self.root/"p3"; p3.mkdir()
        record={"day":"20261006","jcd":"05","rno":1,"venue":"多摩川","deadline":"13:30",
                "created_at":self.now.isoformat(),"digest":"original-digest"}
        path=p3/"20261006_05_01.json"; path.write_text(json.dumps(record))
        item={"race":record,"source":"AI重なり本線","note":"展示反映","score":85,
              "picks":["1-2-3"],"main_picks":["1-2-3"],"cover_picks":[]}
        with patch.object(selector,"PT12_DIR",p12), patch.object(selector,"PT3_DIR",p3):
            row=dispatcher.candidate_row(item,self.now)
            self.assertEqual(row["prediction_records"][0]["record_digest"],"original-digest")
            record["created_at"]=(self.now-timedelta(minutes=16)).isoformat()
            path.write_text(json.dumps(record))
            with self.assertRaises(ValueError): dispatcher.candidate_row(item,self.now)

    def test_formatter_keeps_exact_eighteen_tickets_and_follow_invitation(self):
        main=["1-2-3","1-2-4","1-3-2","1-3-4","1-4-2","1-4-3","2-1-3","2-1-4","2-3-1","2-4-1"]
        cover=["3-1-2","3-1-4","4-1-2","4-2-1","5-1-2","5-2-1","6-1-2","6-2-1"]
        text,picks=formatter.build_featured_post(self.row,source="AI重なり本線",main_picks=main,
                                               cover_picks=cover,note="展示反映｜AI頭評価 2=15%・3=12%・4=10%・5=5%・6=2%")
        self.assertLessEqual(weighted_length(text),280)
        self.assertIn("フォローお願いします",text)
        self.assertEqual(api_server._archived_pick_set({"post":text}),set(main+cover))
        self.assertEqual(set(picks),set(main+cover))

    def test_definite_result_fallback_rejection_does_not_leave_an_uncertain_server_guard(self):
        api_server._X_RESULT_POSTED.clear(); api_server._X_RESULT_UNCERTAIN.clear()
        race=key(self.row); owner="a"*32
        state={"x_posted_races":[race],"x_post_ids":{race:"2345678901234567890"},
               "x_result_attempts":{race:{"id":owner,"status":"reserved"}}}
        with patch.object(api_server,"_x_sync_state",return_value=state), \
             patch.object(api_server,"_x_result_prediction_row",return_value=self.row), \
             patch.object(api_server,"_load_official_result",return_value={"status":"settled","payouts":{"1-2-3":3940}}), \
             patch.object(api_server,"post_to_x",side_effect=[api_server.XPostRejected(403,"reply unavailable"),api_server.XPostRejected(429,"rate limited")]):
            with self.assertRaises(api_server.XPostRejected):
                api_server.sync_archived_result_to_x(self.row["day"],self.row["jcd"],self.row["rno"],"a"*40,owner)
        self.assertNotIn(race,api_server._X_RESULT_UNCERTAIN)

    def test_result_receipt_metadata_matches_actual_standalone_fallback(self):
        api_server._X_RESULT_POSTED.clear(); api_server._X_RESULT_UNCERTAIN.clear()
        race=key(self.row); owner="a"*32
        state={"x_posted_races":[race],"x_post_ids":{race:"2345678901234567890"},
               "x_result_attempts":{race:{"id":owner,"status":"reserved"}}}
        with patch.object(api_server,"_x_sync_state",return_value=state), \
             patch.object(api_server,"_x_result_prediction_row",return_value=self.row), \
             patch.object(api_server,"_load_official_result",return_value={"status":"settled","payouts":{"1-2-3":3940}}), \
             patch.object(api_server,"post_to_x",side_effect=[api_server.XPostRejected(403,"reply unavailable"),"1234567890123456789"]) as post:
            result=api_server.sync_archived_result_to_x(self.row["day"],self.row["jcd"],self.row["rno"],"a"*40,owner)
        self.assertEqual(result["text"],post.call_args.args[0])
        self.assertIsNone(result["reply_to"])
        self.assertIn("39.4倍",result["text"])
        api_server._X_RESULT_POSTED.clear(); api_server._X_RESULT_UNCERTAIN.clear()

    def test_official_void_result_posts_refund_notice_not_fake_winner(self):
        api_server._X_RESULT_POSTED.clear(); api_server._X_RESULT_UNCERTAIN.clear()
        race = key(self.row); owner = "a"*32
        state = {"x_posted_races": [race], "x_post_ids": {race: "2345678901234567890"},
                 "x_result_attempts": {race: {"id": owner, "status": "reserved"}}}
        with patch.object(api_server, "_x_sync_state", return_value=state), \
             patch.object(api_server, "_x_result_prediction_row", return_value=self.row), \
             patch.object(api_server, "_load_official_result", return_value={
                 "status": "void", "payouts": {}, "refund_lanes": [2, 4]}), \
             patch.object(api_server, "post_to_x", return_value="1234567890123456789") as post:
            result = api_server.sync_archived_result_to_x(
                self.row["day"], self.row["jcd"], self.row["rno"], "a"*40, owner)
        self.assertTrue(result["ok"])
        self.assertTrue(result["void"])
        self.assertIsNone(result["odds"])
        self.assertIsNone(result["hit"])
        self.assertIn("返還対象艇：2号艇・4号艇", result["text"])
        self.assertIn("払戻なし", result["text"])
        self.assertIn("\\n", result["text"])
        self.assertEqual(post.call_args.kwargs["reply_to"], "2345678901234567890")
        api_server._X_RESULT_POSTED.clear(); api_server._X_RESULT_UNCERTAIN.clear()


if __name__ == "__main__": unittest.main()
