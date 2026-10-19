"""V4 B-program contextual learning: anti-leak and deterministic regression (offline)."""
from copy import deepcopy
import unittest

from research.scenario_v2 import engine as scenario
from research.four_venue_phase2 import selection_v4_program as v4


def synthetic_race(n=1, day="2026-06-05", code="03", with_program=True):
    boats=[]
    # Strong boat on lane1 in the program; real outcomes are *labels* only.
    first, second, third=1, 2+(n%5), 2+((n+1)%5)
    if third==second:
        third=6 if second!=6 else 2
    order=[first,second,third]+[i for i in range(1,7) if i not in [first,second,third]]
    ranks={lane:rank+1 for rank,lane in enumerate(order)}
    for i in range(1,7):
        p={"lane":i,"racer_id":str(3000+i),"racer_class":"A1" if i==1 else "B1",
           "national_win_rate":7.8 if i==1 else 4.5+(i%3)*.12,
           "local_win_rate":7.2 if i==1 else 3.8+(i%4)*.12,
           "motor_top2_rate":41 if i==1 else 22+i,
           "boat_top2_rate":39 if i==1 else 23+i}
        boats.append({"lane":i,"racer_id":str(3000+i),"program":p if with_program else None,
                      "course":7-i, "actual_st":.13+(i*.015),
                      "finish":ranks[i],"status":f"{ranks[i]:02}"})
    return {"race_id":day.replace("-","")+code+f"{n:02}","venue_code":code,
            "date":day,"normal_eligible":True,"official_verified":True,
            "dead_heat_confirmed":False,"cancelled":False,
            "boats":boats,"trifecta_from_finish":"-".join(map(str,order[:3])),
            "method":"逃げ","wind_m":8,"payout_per_100":1240}


class TestV4Context(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.train=[synthetic_race(n=(i%12)+1,day=f"2026-05-{(i//12)%20+1:02}",code="03")
                   for i in range(240)]
        # Unique race IDs are expected in the real archive, but training only
        # stores the unique IDs as evidence, so generate unique dates/numbers.
        for i,r in enumerate(cls.train):
            r["race_id"]=f"20260{(i//25)%5+1}{(i%25)+1:02}03{(i%12)+1:02}"
            # Force dates to remain in actual training period.
            r["date"]=f"2026-{(i//25)%5+1:02}-{(i%25)+1:02}"
        cls.model=v4.train_model(cls.train,"03")

    def test_project_forgets_results_and_postrace_st(self):
        original=synthetic_race()
        projection=v4.project_B_only(original)
        assert projection is not None
        altered=deepcopy(original)
        for b in altered["boats"]:
            b["finish"]=7-b["finish"]
            b["actual_st"]=0.9
            b["course"]=b["lane"]
            b["status"]="F"
        altered.update({"method":"まくり差し","payout_per_100":100000,
                        "result":"1-6-4","official_trifectas":{"2-1-3":1000}})
        self.assertEqual(v4.project_B_only(altered),projection)
        self.assertEqual(v4.feature_rows(projection),v4.feature_rows(v4.project_B_only(altered)))

    def test_invalid_or_mismatched_program_quarantined(self):
        r=synthetic_race()
        r["boats"][0]["program"]["racer_id"]="9999"
        self.assertIsNone(v4.project_B_only(r))
        r=synthetic_race()
        r["boats"][0]["program"]["racer_class"]="Z1"
        self.assertIsNone(v4.project_B_only(r))
        r=synthetic_race()
        r["boats"][0]["program"]["motor_top2_rate"]=101
        self.assertIsNone(v4.project_B_only(r))

    def test_training_cutoff_and_model_frozen(self):
        ids=self.model["training_ids"]
        self.assertEqual(self.model["training_n"],len(self.train))
        self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue(all(r[:8] <= "20260630" for r in ids))
        self.assertEqual(self.model["training_end"],"2026-06-30")
        self.assertEqual(len(self.model["weights"]),len(v4.FEATURES))
        scenario.verify(self.model)
        self.assertFalse(self.model["calibrated"])
        with self.assertRaisesRegex(ValueError,"digest"):
            tampered=deepcopy(self.model)
            tampered["weights"][0]+=2
            v4.checked(tampered)

    def test_training_ignores_future_results(self):
        future=synthetic_race(1,"2026-07-01")
        future["trifecta_from_finish"]="1-2-3"
        model=v4.train_model(self.train+[future],"03")
        self.assertEqual(model["training_input_digest"],self.model["training_input_digest"])
        self.assertEqual(model["weights"],self.model["weights"])
        self.assertEqual(model["digest"],self.model["digest"])

    def test_120_complete_and_ten_ticket_card(self):
        program=v4.project_B_only(synthetic_race())
        card,ranked=v4.card(program,self.model)
        self.assertEqual(len(card),10)
        self.assertEqual(len(ranked),120)
        self.assertEqual(len(set(r["combination"] for r in ranked)),120)
        self.assertEqual(len(set(r["combination"] for r in card)),10)
        self.assertAlmostEqual(sum(r["uncalibrated_pl_strength"] for r in ranked),1,places=7)
        self.assertEqual(len(v4.feature_rows(program)),6)

    def test_historical_comparison_cannot_use_actual_course(self):
        first=synthetic_race(1,"2026-08-01")
        output=v4.score_history([first],{"03":self.model},{"03":["1-2-3"]+[
            "2-1-3","3-1-2","4-1-3","5-1-3","6-1-3","1-3-2","1-4-2","1-5-2","1-6-2"]})
        self.assertEqual(len(output),1)
        altered=deepcopy(first)
        for b in altered["boats"]:
            b["course"]=b["lane"]
            b["actual_st"]=.001
        output2=v4.score_history([altered],{"03":self.model},{"03":output[0]["A_card"]})
        self.assertEqual(output[0]["V4_card"],output2[0]["V4_card"])
        self.assertEqual(output[0]["V4_hit"],output2[0]["V4_hit"])
        self.assertFalse(output[0]["B_archive_available_as_of_race"])

    def test_no_missing_as_of_claim(self):
        self.assertIn("after racing",self.model["data_availability"])
        self.assertEqual(self.model["adoption_status"],"offline_research_unvalidated")


if __name__=="__main__":
    unittest.main()
