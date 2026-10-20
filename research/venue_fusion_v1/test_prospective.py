"""No-network safety tests for forward-only local research cards."""
import json
import tempfile
from pathlib import Path
from unittest import TestCase, mock

from research.scenario_v2 import engine as scenario
from research.venue_fusion_v1 import prospective as p
from research.venue_fusion_v1 import engine as hybrid


class ProspectiveGateTests(TestCase):
    def sample(self):
        return {"meta":{"day":"20261021","jcd":"06","rno":1,
                        "deadline":"12:00","captured_at":"2026-10-21T11:48:00+09:00"},
                "boats":[{"lane":i,"course":i,"racer_id":str(5000+i),
                          "avg_st":.15,"motor_top2_rate":35,"course_top2_rate":35}
                         for i in range(1,7)]}

    def test_expired_input_cannot_replay_as_live(self):
        with self.assertRaisesRegex(ValueError,"Live forecast"):
            p.build_live(self.sample(),now="2026-10-21T12:05:00+09:00")

    def test_result_leakage_rejected_before_any_main_call(self):
        s=self.sample()
        s["boats"][0]["actual_st"]=.02
        with mock.patch.object(p,"analyze_race") as main:
            with self.assertRaisesRegex(ValueError,"Outcome field forbidden"):
                p.build_live(s,now="2026-10-21T11:50:00+09:00")
            main.assert_not_called()

    def test_no_retroactive_future_generation(self):
        with self.assertRaisesRegex(ValueError,"Generation cannot precede"):
            p.build_live(self.sample(),now="2026-10-21T11:30:00+09:00")

    def test_local_file_atomic_never_overwrites(self):
        rec={"status":"local_frozen_unconfirmed","research_only":True,
             "race_id":"20261021_06_01","count_as_prospective":False}
        rec["digest"]=scenario.digest(rec)
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/"20261021_06_01.json"
            p.save_local_only(rec,dest)
            original=dest.read_bytes()
            with self.assertRaises(FileExistsError):
                p.save_local_only(rec,dest)
            self.assertEqual(original,dest.read_bytes())
            self.assertFalse(json.loads(original)["count_as_prospective"])

    def test_digest_tampering_rejected(self):
        rec={"status":"local_frozen_unconfirmed","research_only":True,
             "race_id":"20261021_06_01"}
        rec["digest"]=scenario.digest(rec)
        rec["race_id"]="20261021_06_02"
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/"forged.json"
            with self.assertRaisesRegex(ValueError,"digest"):
                p.save_local_only(rec,dest)
            self.assertFalse(dest.exists())

    def test_live_cards_but_no_prospective_claim_without_receipt(self):
        s=self.sample()
        combos=sorted(scenario.COMBINATIONS)
        main={"model_version":hybrid.EXPECTED_MAIN_VERSION,
              "trifecta":[{"combination":v,"probability":(120-i)/7260}
                          for i,v in enumerate(combos)]}
        fake_original={"payload":{"race":{"venue":"浜名湖"},"boats":[]},
                       "meta":{"preprocessing_level":"main_official_core_without_profile_form_odds",
                               "source_sha256":"a"*64,
                               "official_pages":{"racelist":{"sha256":"b"*64},
                                                 "beforeinfo":{"sha256":"c"*64}}},
                       "limitations":["missing historical profiles"]}
        fake_yuuki={"digest":"y"*64}
        fake_venue={"digest":"v"*64,"lane_audits":[]}
        with mock.patch.object(p,"from_frozen_official",return_value=fake_original),\
             mock.patch.object(p,"analyze_race",return_value=main),\
             mock.patch.object(p.hybrid,"_build_with_ranking",return_value=fake_yuuki),\
             mock.patch.object(p.hybrid,"_card",return_value=combos[:10]),\
             mock.patch.object(p.venue,"analyze",return_value=fake_venue),\
             mock.patch.object(p.hybrid,"_venue_adjust",side_effect=lambda rows,_:(rows,False)):
            r=p.build_live(s,now="2026-10-21T11:50:00+09:00")
        self.assertEqual(len(r["model_cards"]),3)
        self.assertTrue(all(len(c)==10 for c in r["model_cards"].values()))
        self.assertFalse(r["git_remote_receipt_confirmed"])
        self.assertFalse(r["count_as_prospective"])
        self.assertFalse(r["main_full_delivery_parity"])
        self.assertFalse(r["result_accessed"])
        self.assertEqual(r["status"],"local_frozen_unconfirmed")
        self.assertEqual(r["digest"],scenario.digest({k:v for k,v in r.items() if k!="digest"}))
