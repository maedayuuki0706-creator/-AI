"""True-main/yuuki/venue fusion: independent, offline, no secrets or delivery."""
from copy import deepcopy
from datetime import datetime
from unittest import TestCase, main, mock

from research.scenario_v2 import engine as scenario
from research.venue_fusion_v1 import engine as fusion


def sources():
    snap={
        "meta":{"day":"20261019", "jcd":"03", "rno":1,
                "deadline":"11:30", "captured_at":"2026-10-19T11:21:00+09:00"},
        "boats":[],
        "environment":{"wind_speed":8, "wind_direction":None,
                       "wave_cm":10, "tide":{"available":False,
                                           "current_measured":False}},
    }
    main_boats=[]
    for i in range(1,7):
        s={"lane":i,"course":i,"racer_id":str(4000+i),
           "avg_st":.10+i*.015,"motor_top2_rate":25+i,
           "course_top2_rate":30+i,
           "exhibition_time":6.8+i*.025, "exhibition_st":.11+i*.01}
        snap["boats"].append(s)
        main_boats.append({
            "lane":i,"predicted_course":i,"racer_id":str(4000+i),
            "avg_st":s["avg_st"],"win_rate":7.1-i*.4,
            "top2_rate":54-i,"top3_rate":66-i,"local_win_rate":6.7-i*.4,
            "local_top2_rate":44-i,"motor_top2_rate":s["motor_top2_rate"],
            "motor_top3_rate":40+i,"boat_top2_rate":31+i,
            "boat_top3_rate":43+i,"course_win_rate":48-i*4,
            "course_top2_rate":62-i,"exhibition_time":s["exhibition_time"],
            "exhibition_st":s["exhibition_st"],
            "flying":False,"exhibition_grade":.45+i*.01,
            "turn_grade":.5,"straight_grade":.5,"pit_out_grade":.5,
            "lap_grade":.5,"motor_grade":.5
        })
    source={
        "meta":{"day":"20261019","jcd":"03","rno":1,"deadline":"11:30",
                "captured_at":"2026-10-19T11:20:50+09:00",
                "source_observed_at":"2026-10-19T11:20:40+09:00",
                "source_type":fusion.ALLOWED_SOURCE,
                "production_preprocessing_verified":True,
                "source_sha256":"a"*64},
        "payload":{"race":{"venue":"江戸川","wind_speed":8,"wave_cm":10},
                   "boats":main_boats,"trifecta_odds":{}},
    }
    return snap,source


NOW="2026-10-19T20:00:00+09:00"


class FusionTest(TestCase):
    def test_true_main_120_plus_yuuki_plus_venue_keeps_ten_each(self):
        snap,src=sources()
        before=deepcopy((snap,src))
        x=fusion.generate(snap,src,mode="replay",now=NOW)
        scenario.verify(x)
        self.assertEqual(x["main_engine_version"],fusion.EXPECTED_MAIN_VERSION)
        self.assertEqual(x["status"],"retrospective_replay")
        self.assertTrue(x["research_only"])
        self.assertFalse(x["count_as_delivered"])
        self.assertFalse(x["venue_validated_adjustment_active"])
        self.assertFalse(x["main_probability_is_calibrated"])
        self.assertFalse(x["expected_value_computed"])
        self.assertEqual(len(x["main_120_rank"]),120)
        self.assertAlmostEqual(sum(x["main_head_strength"].values()),1,places=6)
        self.assertEqual(len(x["all_six_win_and_loss_hypotheses"]),6)
        for lane in x["all_six_win_and_loss_hypotheses"]:
            self.assertGreater(len(lane["win_paths"]),0)
            self.assertGreater(len(lane["loss_paths"]),0)
        for card in x["variants"].values():
            self.assertEqual(len(card),10)
            self.assertEqual(len(set(card)),10)
        # Until water/venue factors pass their holdout gates, they are a NO-OP.
        self.assertEqual(x["variants"]["existing_main_plus_yuuki"],
                         x["variants"]["existing_main_plus_yuuki_plus_venue"])
        self.assertEqual((snap,src),before)

    def test_main_is_always_first_stage(self):
        snap,src=sources()
        x=fusion.generate(snap,src,mode="replay",now=NOW)
        expected=[r["combination"] for r in x["main_120_rank"][:10]]
        self.assertEqual(x["variants"]["existing_main"],expected)
        # The 6 strongest original-main selections cannot be dropped silently.
        self.assertEqual(x["variants"]["existing_main_plus_yuuki"][:6],expected[:6])

    def test_reject_mismatched_entrant_or_exhibition_course(self):
        a,b=sources()
        b["payload"]["boats"][0]["racer_id"]="8888"
        with self.assertRaisesRegex(ValueError,"racer IDs"):
            fusion.generate(a,b,mode="replay",now=NOW)
        a,b=sources()
        b["payload"]["boats"][0]["predicted_course"]=2
        with self.assertRaisesRegex(ValueError,"entry courses"):
            fusion.generate(a,b,mode="replay",now=NOW)

    def test_disallow_truncated_main_inputs_that_mimic_full_live_model(self):
        a,b=sources()
        del b["payload"]["boats"][0]["win_rate"]
        with self.assertRaisesRegex(ValueError,"missing required field"):
            fusion.generate(a,b,mode="replay",now=NOW)
        a,b=sources()
        b["meta"]["production_preprocessing_verified"]=False
        with self.assertRaisesRegex(ValueError,"preprocessing"):
            fusion.generate(a,b,mode="replay",now=NOW)

    def test_time_leak_and_mixed_snaps_rejected(self):
        a,b=sources()
        b["meta"]["source_observed_at"]="2026-10-19T11:25:00+09:00"
        with self.assertRaisesRegex(ValueError,"Future source"):
            fusion.generate(a,b,mode="replay",now=NOW)
        a,b=sources()
        b["meta"]["source_observed_at"]="2026-10-19T11:16:00+09:00"
        b["meta"]["captured_at"]="2026-10-19T11:16:30+09:00"
        with self.assertRaisesRegex(ValueError,"120 seconds"):
            fusion.generate(a,b,mode="replay",now=NOW)
        a,b=sources()
        b["meta"]["db_snapshot_at"]="2026-10-19T11:21:00+09:00"
        with self.assertRaisesRegex(ValueError,"Future database"):
            fusion.generate(a,b,mode="replay",now=NOW)

    def test_nested_postrace_leak_is_rejected(self):
        a,b=sources()
        b["payload"]["boats"][0]["race_result"]={"actual_st":.09}
        with self.assertRaisesRegex(ValueError,"Outcome field forbidden"):
            fusion.generate(a,b,mode="replay",now=NOW)
        a,b=sources()
        a["environment"]["actual_course"]=1
        with self.assertRaisesRegex(ValueError,"Outcome field forbidden"):
            fusion.generate(a,b,mode="replay",now=NOW)

    def test_different_day_or_venue_rejected(self):
        a,b=sources()
        b["meta"]["day"]="20261020"
        with self.assertRaisesRegex(ValueError,"race: day"):
            fusion.generate(a,b,mode="replay",now=NOW)
        a,b=sources()
        b["payload"]["race"]["venue"]="唐津"
        with self.assertRaisesRegex(ValueError,"venue string"):
            fusion.generate(a,b,mode="replay",now=NOW)

    def test_live_requires_real_forecast_before_deadline(self):
        a,b=sources()
        with self.assertRaisesRegex(ValueError,"before deadline"):
            fusion.generate(a,b,mode="live",now=NOW)

    def test_scoped_venue_adjustment_only_after_evidence(self):
        snap,src=sources()
        a=fusion.generate(snap,src,mode="replay",now=NOW)
        with mock.patch.object(fusion.venue,"analyze",autospec=True) as mocked:
            mocked.return_value={"race_id":a["race_id"],"venue":"江戸川","digest":a["venue_diagnostics_digest"],
                "seven_features":a["venue_observations"],
                "lane_audits":[{"lane":i,"score":.1 if i==6 else 0.0} for i in range(1,7)]}
            b=fusion.generate(snap,src,mode="replay",now=NOW)
        self.assertTrue(b["venue_validated_adjustment_active"])
        self.assertEqual(len(b["variants"]["existing_main_plus_yuuki_plus_venue"]),10)
        self.assertEqual(a["variants"]["existing_main"],b["variants"]["existing_main"])
        with mock.patch.object(fusion.venue,"analyze",autospec=True) as mocked:
            mocked.return_value={"race_id":a["race_id"],"venue":"江戸川","digest":a["venue_diagnostics_digest"],
                "seven_features":a["venue_observations"],
                "lane_audits":[{"lane":i,"score":3.0} for i in range(1,7)]}
            with self.assertRaisesRegex(ValueError,"Unbounded venue"):
                fusion.generate(snap,src,mode="replay",now=NOW)


if __name__=="__main__":
    main()
