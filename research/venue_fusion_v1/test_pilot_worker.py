"""Synthetic existing-specialist source receipt -> independent fusion branch pilot.

Only local bare Git servers: proof of separate original/source state and fusion
destination, and of refusal to replay old/fake/duplicate/late research cards.
"""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from research.scenario_v2 import engine as scenario
from research.venue_fusion_v1 import pilot_worker as bridge
from research.venue_fusion_v1 import remote_receipt as rr
from research.venue_fusion_v1 import independent_grade as gr
from research.venue_fusion_v1.test_remote_receipt import git,fixture,seal,review_for


class PilotBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)
        self.now,self.card=fixture()
        self.day=self.card["day"]
        self.rid=self.card["race_id"]
        self.src_branch=bridge.ORIG_SOURCE_BRANCH
        self.source=self._repo(self.src_branch,"source")
        self.target=self._repo(rr.REMOTE_BRANCH,"target")
        self.scratch=self.home/"scratch"
        cutoff=scenario.aware(self.card["deadline_at"])
        self.snapshot={
            "meta":{"day":self.day,"jcd":"03","rno":3,
                    "deadline":cutoff.strftime("%H:%M"),
                    "captured_at":(self.now-timedelta(minutes=2)).isoformat()},
            "boats":[{"lane":i,"course":i,"racer_id":str(4100+i),
                      "avg_st":.15,"motor_top2_rate":35,"course_top2_rate":35} for i in range(1,7)],
            "official_originals":{
                "racelist":{"html":"<html>research mock roster</html>","sha256":"a"*64},
                "beforeinfo":{"html":"<html>research mock exhibition</html>","sha256":"b"*64}
            },
        }
        self._write_original()

    def _repo(self,branch,label):
        origin=self.home/f"{label}.git"
        work=self.home/label
        work.mkdir()
        git("init","--bare","--initial-branch="+branch,origin)
        git("init","-b",branch,work)
        git("-C",work,"config","user.name","Research Test")
        git("-C",work,"config","user.email","research@example.test")
        (work/"README.md").write_text("Separate test branch\n")
        git("-C",work,"add","README.md")
        git("-C",work,"commit","-m","Seed independent research branch")
        git("-C",work,"remote","add","origin",origin)
        git("-C",work,"push","-u","origin",branch)
        return work

    def _write_original(self):
        root=self.source/"data"/"venue_specialists_v1"
        inp=f"data/venue_specialists_v1/inputs/{self.day}/{self.rid}.json"
        fcast=f"data/venue_specialists_v1/forecasts/{self.day}/{self.rid}.json"
        receipt=f"data/venue_specialists_v1/receipts/{self.day}/{self.rid}.json"
        forecast={
            "race_id":self.rid,"deadline_at":self.card["deadline_at"],
            "snapshot_digest":scenario.digest(self.snapshot),
            "status":"prospective_uncheckpointed","research_only":True,
        }
        seal(forecast)
        for path,value in [(inp,self.snapshot),(fcast,forecast)]:
            filepath=self.source/path
            filepath.parent.mkdir(parents=True,exist_ok=True)
            filepath.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True)+"\n")
        git("-C",self.source,"add","--",inp,fcast)
        git("-C",self.source,"commit","-m","Freeze existing official research input and card")
        source_sha=git("-C",self.source,"rev-parse","HEAD")
        proof={
            "race_id":self.rid,"status":"confirmed_before_deadline",
            "complete_originals_verified":True,"commit_sha":source_sha,
            "input_path":inp,"forecast_path":fcast,
            "checked_at":(self.now-timedelta(minutes=1)).isoformat(),
            "digest":forecast["digest"],"snapshot_digest":forecast["snapshot_digest"],
        }
        receiptpath=self.source/receipt
        receiptpath.parent.mkdir(parents=True,exist_ok=True)
        receiptpath.write_text(json.dumps(proof,ensure_ascii=False,sort_keys=True)+"\n")
        git("-C",self.source,"add","--",receipt)
        git("-C",self.source,"commit","-m","Save original specialist remote receipt")
        git("-C",self.source,"push","origin",f"HEAD:refs/heads/{self.src_branch}")
        self.orig_input=self.source/inp
        self.old_receipt=receiptpath

    def _make_card(self,snapshot,now):
        card=deepcopy(self.card)
        card["generated_at"]=now
        card["input_digest"]=scenario.digest(snapshot)
        card["input_captured_at"]=snapshot["meta"]["captured_at"]
        card["deadline_at"]=scenario.aware(
            snapshot["meta"]["day"][:4]+"-"+snapshot["meta"]["day"][4:6]+"-"+
            snapshot["meta"]["day"][6:8]+"T"+snapshot["meta"]["deadline"]+":00+09:00").isoformat()
        return seal(card)

    def _run_bridge(self,*,publish,clock=None):
        with mock.patch.object(bridge.prospective,"build_live",side_effect=self._make_card):
            return bridge.process(self.source,self.target,self.scratch,
                                  clock=clock or (lambda:self.now),max_races=2,
                                  publish=publish,allow_local_origin_for_tests=True)

    def test_same_original_authenticated_without_altering_earlier_worker(self):
        rid,snapshot,old=bridge.verify_original(self.orig_input,self.source)
        self.assertEqual(rid,self.rid)
        self.assertEqual(old["source_input_digest"],scenario.digest(self.snapshot))
        self.assertTrue(old["source_remote_received_before_deadline"])
        self.assertEqual(len(bridge.scan_inputs(self.source,self.now.isoformat())),1)

    def test_dry_run_writes_only_scratch_not_destination(self):
        before=git("-C",self.source,"rev-parse","HEAD")
        targetbefore=git("-C",self.target,"rev-parse","HEAD")
        result=self._run_bridge(publish=False)
        self.assertEqual(len(result["dry_run_verified"]),1)
        self.assertEqual(result["published"],[])
        self.assertEqual(git("-C",self.target,"rev-parse","HEAD"),targetbefore)
        self.assertEqual(git("-C",self.source,"rev-parse","HEAD"),before)
        self.assertTrue((self.scratch/"pilot_status.json").exists())

    def test_real_state_publish_after_original_without_modifying_original(self):
        sourcebefore=git("-C",self.source,"rev-parse","HEAD")
        success=self._run_bridge(publish=True)
        self.assertEqual(len(success["published"]),1,success["skipped"])
        self.assertEqual(success["dry_run_verified"],[])
        self.assertEqual(git("-C",self.source,"rev-parse","HEAD"),sourcebefore)
        event=success["published"][0]
        self.assertEqual(event["race_id"],self.rid)
        independent=gr.evidence(self.target,self.rid,allow_local_origin_for_tests=True)
        result=gr.grade(independent,review_for(independent["forecast"],
            independent["forecast"]["model_cards"]["official_main_core"][0]))
        self.assertTrue(result["count_as_prospective"])
        duplicate=self._run_bridge(publish=True)
        self.assertEqual(duplicate["published"],[])
        self.assertEqual(duplicate["skipped"][0]["reason"],"already_frozen_independent_state")

    def test_original_source_receipt_too_late_is_rejected(self):
        proof=json.loads(self.old_receipt.read_text())
        proof["checked_at"]=(scenario.aware(self.card["deadline_at"])-timedelta(minutes=1)).isoformat()
        self.old_receipt.write_text(json.dumps(proof,ensure_ascii=False)+"\n")
        with self.assertRaisesRegex(ValueError,"too late"):
            bridge.verify_original(self.orig_input,self.source)

    def test_source_digest_mutation_rejected(self):
        snap=json.loads(self.orig_input.read_text())
        snap["boats"][0]["motor_top2_rate"]=99
        self.orig_input.write_text(json.dumps(snap,ensure_ascii=False)+"\n")
        with self.assertRaisesRegex(ValueError,"digest"):
            bridge.verify_original(self.orig_input,self.source)

    def test_no_attempt_when_approaching_cutoff(self):
        result=self._run_bridge(publish=True,
             clock=lambda:self.now+timedelta(minutes=17))
        self.assertEqual(result["published"],[])
        self.assertEqual(len(result["skipped"]),1)
        self.assertIn("cutoff",result["skipped"][0]["detail"])

    def test_empty_dir_does_not_fabricate_records(self):
        (self.orig_input).unlink()
        result=self._run_bridge(publish=False)
        self.assertEqual(result["published"],[])
        self.assertEqual(result["dry_run_verified"],[])
        self.assertEqual(result["new_model_prospective_grade_count"],0)


if __name__=="__main__":
    unittest.main()
