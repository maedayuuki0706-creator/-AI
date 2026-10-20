"""End-to-end local-bare-Git tests: real push, fetch, immutable receipt, grading.

No HTTP, no GitHub secret, no production ref. A real Git repository simulator
is used so content verification and commit ancestry are actually exercised.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from research.scenario_v2 import engine as scenario
from research.venue_fusion_v1 import prospective as p
from research.venue_fusion_v1 import remote_receipt as rr
from research.venue_fusion_v1 import independent_grade as gr


def git(*args):
    return subprocess.check_output(["git",*map(str,args)],text=True).strip()


def fixture():
    now=datetime.now(scenario.JST).replace(microsecond=0)
    # Use a dynamic JST race-day rather than a predated fixture.
    day=now.strftime("%Y%m%d")
    code="03"
    rid=f"{day}_{code}_03"
    deadline=now+timedelta(minutes=20)
    c=sorted(scenario.COMBINATIONS)
    return now,{
        "version":p.VERSION,"research_only":True,
        "race_id":rid,"day":day,"venue_code":code,
        "deadline_at":deadline.isoformat(),
        "generated_at":(now-timedelta(minutes=1)).isoformat(),
        "input_captured_at":(now-timedelta(minutes=2)).isoformat(),
        "input_digest":"a"*64,"official_source_sha256":"b"*64,
        "main_model_version":"kyoutei-navi-course-v7-market-structure",
        "main_full_delivery_parity":False,"venue_adjustment_validated":False,
        "model_cards":{
            p.MODELS[0]:c[:10],
            p.MODELS[1]:c[4:14],
            p.MODELS[2]:c[4:14]
        },
        "ticket_count":10,"per_ticket_stake_yen":100,
        "status":"local_frozen_unconfirmed","git_remote_receipt_confirmed":False,
        "count_as_prospective":False,"result_accessed":False,
    }


def seal(obj):
    obj["digest"]=scenario.digest(obj)
    return obj


def review_for(card,winner,payout=1300):
    r={
        "race_id":card["race_id"],"jcd":card["venue_code"],"status":"graded",
        "source":"BOAT RACE official raceresult","refund_lanes":[],
        "official_trifectas":{winner:payout},
        "official_observed_at":(scenario.aware(card["deadline_at"])+timedelta(minutes=2)).isoformat(),
    }
    return seal(r)


class RemoteReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.remote=self.folder/"server.git"
        self.work=self.folder/"state"
        self.work.mkdir()
        git("init","--bare","--initial-branch="+rr.REMOTE_BRANCH,self.remote)
        git("init","-b",rr.REMOTE_BRANCH,self.work)
        git("-C",self.work,"config","user.name","Research Test")
        git("-C",self.work,"config","user.email","research@example.test")
        (self.work/"README.md").write_text("Independent research state only\n")
        git("-C",self.work,"add","README.md")
        git("-C",self.work,"commit","-m","Initial isolated research state")
        git("-C",self.work,"remote","add","origin",self.remote)
        git("-C",self.work,"push","-u","origin",rr.REMOTE_BRANCH)
        self.now,self.card=fixture()
        seal(self.card)

    def _publish(self,card=None,clock=None):
        return rr.publish(card or self.card,self.work,
                          allow_local_origin_for_tests=True,
                          clock=clock or (lambda:self.now))

    def _evidence(self):
        return gr.evidence(self.work,self.card["race_id"],
                           allow_local_origin_for_tests=True)

    def test_full_research_remote_publish_and_independent_grade(self):
        event=self._publish()
        self.assertTrue(event["remote_receipt_confirmed_before_cutoff"])
        self.assertFalse(event["count_as_prospective"])
        self.assertEqual(len(event["forecast_commit_sha"]),40)
        self.assertNotEqual(event["forecast_commit_sha"],event["receipt_commit_sha"])
        state=self._evidence()
        self.assertTrue(state["read_only_remote_git_verified"])
        self.assertEqual(state["forecast"]["model_cards"],self.card["model_cards"])
        self.assertEqual(state["receipt"]["forecast_digest"],self.card["digest"])
        winning=self.card["model_cards"][p.MODELS[1]][-1]
        result=gr.grade(state,review_for(self.card,winning,1350))
        self.assertTrue(result["count_as_prospective"])
        self.assertEqual(result["status"],"graded")
        self.assertEqual(result["per_model"][p.MODELS[0]]["return_yen"],0)
        self.assertEqual(result["per_model"][p.MODELS[1]]["return_yen"],1350)
        self.assertEqual(result["per_model"][p.MODELS[1]]["roi_pct"],135)
        self.assertFalse(result["model_is_full_production_main"])
        self.assertFalse(result["actual_1mark_tactics_verified"])
        self.assertIn("NOT_independent_server_time",result["time_attestation_type"])

    def test_no_remote_receipt_means_no_grading(self):
        with self.assertRaisesRegex(ValueError,"Missing or rewritten receipt"):
            self._evidence()

    def test_only_exact_state_branch_can_be_published(self):
        git("-C",self.work,"checkout","-b","main")
        with self.assertRaisesRegex(ValueError,"except independent fusion state"):
            self._publish()

    def test_default_does_not_allow_local_bare_git_origin(self):
        with self.assertRaisesRegex(ValueError,"Remote URL"):
            rr.publish(self.card,self.work,clock=lambda:self.now)

    def test_once_frozen_cannot_overwrite_or_duplicate(self):
        event=self._publish()
        fore_path,receipt_path=rr.source_paths(self.card["race_id"])
        original=(self.work/fore_path).read_bytes()
        receipt=(self.work/receipt_path).read_bytes()
        with self.assertRaises(FileExistsError):
            self._publish()
        self.assertEqual(original,(self.work/fore_path).read_bytes())
        self.assertEqual(receipt,(self.work/receipt_path).read_bytes())

    def test_expired_forecast_and_replay_are_rejected_pre_push(self):
        stale_clock=lambda:self.now+timedelta(minutes=22)
        with self.assertRaisesRegex(ValueError,"cutoff|stale"):
            self._publish(clock=stale_clock)
        self.assertEqual(len(list(self.work.glob("data/**/forecasts/*.json"))),0)
        bad=deepcopy(self.card)
        bad["status"]="retrospective_replay"
        seal(bad)
        with self.assertRaisesRegex(ValueError,"Only original"):
            self._publish(card=bad)

    def test_missed_remote_cutoff_leaves_unreceived_not_forged(self):
        successive=iter([self.now,self.now+timedelta(minutes=22)])
        with self.assertRaisesRegex(ValueError,"after forecast safety cutoff"):
            self._publish(clock=lambda:next(successive))
        forecast_path,receipt_path=rr.source_paths(self.card["race_id"])
        self.assertTrue((self.work/forecast_path).exists())
        self.assertFalse((self.work/receipt_path).exists())
        with self.assertRaisesRegex(ValueError,"Missing or rewritten receipt"):
            self._evidence()

    def test_status_promotion_or_outcome_leak_is_rejected(self):
        forged=deepcopy(self.card)
        forged["count_as_prospective"]=True
        seal(forged)
        with self.assertRaisesRegex(ValueError,"counterfeit"):
            self._publish(card=forged)
        forged=deepcopy(self.card)
        forged["actual_st"]=[.08,.1,.2]
        seal(forged)
        with self.assertRaisesRegex(ValueError,"Outcome field forbidden"):
            self._publish(card=forged)

    def test_frozen_future_data_or_mismatched_race_id_rejected(self):
        forged=deepcopy(self.card)
        forged["generated_at"]=(self.now+timedelta(minutes=4)).isoformat()
        seal(forged)
        with self.assertRaisesRegex(ValueError,"Future"):
            self._publish(card=forged)
        forged=deepcopy(self.card)
        forged["race_id"]=forged["race_id"].replace("_03_03","_23_03")
        seal(forged)
        with self.assertRaisesRegex(ValueError,"Inconsistent"):
            self._publish(card=forged)

    def test_exclusions_do_not_count_as_prospective(self):
        self._publish()
        state=self._evidence()
        winner=self.card["model_cards"][p.MODELS[0]][0]
        review=review_for(self.card,winner)
        review["refund_lanes"]=[2]
        seal(review)
        score=gr.grade(state,review)
        self.assertFalse(score["count_as_prospective"])
        self.assertEqual(score["status"],"excluded")
        review=review_for(self.card,winner)
        review["official_observed_at"]=(self.now-timedelta(minutes=5)).isoformat()
        seal(review)
        with self.assertRaisesRegex(ValueError,"before the race"):
            gr.grade(state,review)

    def test_three_card_same_winner_distinguishes_miss_reasons(self):
        winner="6-5-4"
        self.assertEqual(gr._card_label(winner,["1-2-3"]),"head_not_in_ten")
        self.assertEqual(gr._card_label("1-5-4",["1-2-3"]),"second_not_in_ten_after_head")
        self.assertEqual(gr._card_label("1-2-4",["1-2-3"]),"third_not_in_ten_after_head_second")
        self.assertEqual(gr._card_label("1-2-3",["1-2-3"]),"hit")


if __name__=="__main__":
    unittest.main()
