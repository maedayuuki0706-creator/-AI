"""Offline selector V3 regression, no network and no effect on production."""
import json
from pathlib import Path
import unittest

from research.four_venue_phase2 import model as historical
from research.four_venue_phase2 import selection_v3 as up
from research.four_venue_phase2 import evaluate_selection_v3 as evaluation
from research.scenario_v2 import engine as scenario

HERE = Path(__file__).resolve().parents[1]
MODELS = HERE / "model_manifests"


def mock_snapshot(day="20261019", venue="03", captured="2026-10-19T11:14:00+09:00"):
    return {
        "meta":{
            "day":day,"jcd":venue,"rno":1,"deadline":"11:30",
            "captured_at":captured,"db_snapshot_at":"2026-10-16T09:00:00+09:00",
        },
        "boats":[{
            "lane":i,"course":i,"racer_id":str(4500+i),"name":"テスト",
            "avg_st":.13+i*.01,"exhibition_st":.2-i*.01,
            "exhibition_time":7+i*.02,"motor_top2_rate":30,
            "course_top2_rate":None,"turn_time":None,"straight_time":None,
            "lap_time":None,
        } for i in range(1,7)],
        "environment":{"wind_speed":8,"wind_direction":None,"wave_cm":10}
    }


class TestSelectionV3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models=evaluation.manifests(MODELS)

    def test_train_model_is_venue_fixed_and_old(self):
        self.assertEqual(set(self.models),set(["03","16","23","06"]))
        for jcd,model in self.models.items():
            self.assertEqual(model["training_end"],"2026-06-30")
            self.assertTrue(all(x[8:10]==jcd for x in model["training_race_ids"]))
            self.assertLess(len(model["training_race_ids"]),8876)

    def test_all_120_scores_and_card_caps(self):
        identity=dict(zip(range(1,7),range(1,7)))
        for jcd,model in self.models.items():
            for variant in up.VARIANTS:
                ranks=up.rank_weights(up._scoring(model,variant),identity)
                self.assertEqual(len(ranks),120)
                self.assertEqual(len(set(row["combination"] for row in ranks)),120)
                card=up.choose(ranks,variant)
                self.assertEqual(len(card),10)
                self.assertEqual(len(set(x["combination"] for x in card)),10)
                if variant=="V3":
                    counts={}
                    pair={}
                    for row in card:
                        h,s,_=row["combination"].split("-")
                        counts[h]=counts.get(h,0)+1
                        pair[h,s]=pair.get((h,s),0)+1
                    self.assertLessEqual(max(counts.values()),5)
                    self.assertLessEqual(max(pair.values()),2)

    def test_course_switch_mapped_without_any_outcome(self):
        boats=mock_snapshot()["boats"]
        boats[0]["course"],boats[3]["course"]=boats[3]["course"],boats[0]["course"]
        mapped=up.course_to_lane(boats)
        self.assertEqual(mapped[1],4)
        self.assertEqual(mapped[4],1)
        self.assertEqual(len(set(mapped.values())),6)
        rankings=up.rank_weights(up._scoring(self.models["03"],"V3"),mapped)
        self.assertEqual(len(rankings),120)

    def test_bad_lane_or_duplicate_rejected(self):
        boats=mock_snapshot()["boats"]
        boats[0]["course"]=2
        with self.assertRaises(ValueError):
            up.course_to_lane(boats)
        with self.assertRaises(ValueError):
            up.rank_weights({(1,2,3):.1},dict(zip(range(1,7),range(1,7))))

    def test_build_has_six_boat_paths_and_full_alternative_audit(self):
        src=mock_snapshot()
        old=json.dumps(src,sort_keys=True)
        record=up.snapshot_candidates(src,self.models["03"],"V3",mode="replay",
                                      now="2026-10-19T19:00:00+09:00")
        scenario.verify(record)
        self.assertEqual(record["status"],"retrospective_replay")
        self.assertEqual(record["model_digest"],self.models["03"]["digest"])
        self.assertEqual(len(record["lanes"]),6)
        self.assertEqual(len(record["all_120_candidates"]),120)
        self.assertEqual(len(record["virtual_card"]),10)
        self.assertEqual(len(record["not_selected"]),110)
        self.assertEqual(len({r["combination"] for r in record["all_120_candidates"]}),120)
        self.assertEqual({r["rank"] for r in record["all_120_candidates"]},set(range(1,121)))
        self.assertFalse(record["probabilities_calibrated"])
        self.assertEqual(record["training_end"],"2026-06-30")
        self.assertEqual(json.dumps(src,sort_keys=True),old)
        for lane in record["lanes"]:
            self.assertTrue(lane["win_paths"] and lane["loss_paths"] and lane["hypotheses"])

    def test_outcome_leak_rejected_even_nested(self):
        snap=mock_snapshot()
        snap["boats"][0]["race_result"]={"trifecta":"1-2-3"}
        with self.assertRaisesRegex(ValueError,"Outcome"):
            up.snapshot_candidates(snap,self.models["03"],"V3",mode="replay",
                                   now="2026-10-19T19:00:00+09:00")

    def test_malformed_or_future_model_prevented(self):
        snap=mock_snapshot("20261018","03","2026-10-18T11:14:00+09:00")
        with self.assertRaisesRegex(ValueError,"not available"):
            up.snapshot_candidates(snap,self.models["03"],"V3",mode="replay",
                                   now="2026-10-19T19:00:00+09:00")
        snap=mock_snapshot(venue="16")
        with self.assertRaisesRegex(ValueError,"mismatch"):
            up.snapshot_candidates(snap,self.models["03"],"V3",mode="replay",
                                   now="2026-10-19T19:00:00+09:00")

    def test_original_scoring_is_not_mutated(self):
        for model in self.models.values():
            frozen= json.dumps(model,sort_keys=True)
            for v in up.VARIANTS:up.historical_card(model,v)
            self.assertEqual(json.dumps(model,sort_keys=True),frozen)

    def test_historical_finish_kept_out_of_ranker(self):
        record={
            "race_id":"202608010301","date":"2026-08-01",
            "normal_eligible":True,"official_verified":True,
            "trifecta_from_finish":"3-1-5",
            "boats":[{"lane":i,"course":7-i,"finish":{1:2,2:6,3:1,4:5,5:3,6:4}[i]}
                     for i in range(1,7)]
        }
        self.assertEqual(evaluation._actual_lanes(record),"3-1-5")
        before=up.historical_card(self.models["03"],"V3")
        for boat in record["boats"]:
            boat["course"]=boat["lane"]
        after=up.historical_card(self.models["03"],"V3")
        self.assertEqual(before,after,"Outcome course must not feed candidate ranking")
        hist=evaluation.historical_exploration([{"venue_code":"03",**record}],self.models)
        self.assertEqual(len(hist),3)
        self.assertTrue(all(r["ROI_available"] is False for r in hist))

    def test_return_math_and_classification(self):
        self.assertEqual(up.miss_type("1-2-3",["1-2-3"]),"hit")
        self.assertEqual(up.miss_type("1-2-4",["1-2-3"]),"third_not_selected_given_head_and_second")
        self.assertEqual(up.miss_type("1-4-2",["1-2-3"]),"second_not_selected_given_head")
        self.assertEqual(up.miss_type("4-2-3",["1-2-3"]),"head_not_selected")


if __name__=="__main__":
    unittest.main()
