import unittest
from datetime import datetime, timedelta, timezone
from research.ultimate_fusion_v1 import engine as e

def race(day="20261102", code="23", rno=7, with_results=False, *, first=2, second=1, third=5):
    outcome_order = [first, second, third] + [i for i in range(1, 7) if i not in (first, second, third)]
    finish_by_lane = {lane: i for i, lane in enumerate(outcome_order, 1)}
    rows = [{
        "lane": i, "racer_id": str(4000+i), "name": "TEST" + str(i),
        "exhibition_course": i,
        "exhibition_time": 6.7 + (i-1)*.03,
        "exhibition_st": .12 + i*.01,
        "tilt": 0,
        "motor_number": i*10,
        **({"finish": finish_by_lane[i], "actual_st": .13, "actual_course": i}
           if with_results else {}),
    } for i in range(1, 7)]
    return {
        "day": day, "jcd": code, "rno": rno,
        "deadline": "12:00", "captured_at": f"{day[:4]}-{day[4:6]}-{day[6:]}T11:42:00+09:00",
        "settled": with_results,
        "rows": rows,
    }

class FusionContractTest(unittest.TestCase):
    def test_24_venues_120_combinations(self):
        self.assertEqual(len(e.VENUE_CODES), 24)
        self.assertEqual(len(e.COMBOS), 120)
        self.assertEqual(len(set(e.COMBOS)), 120)
        self.assertIn("2-1-5", e.COMBOS)

    def test_valid_predeadline(self):
        snapshot = e.prepare_live(race())
        self.assertEqual(snapshot["race_id"], "20261102_23_07")
        self.assertNotIn("finish", snapshot["boats"][0])
        self.assertNotIn("actual_st", snapshot["boats"][0])

    def test_live_settled_never_allowed(self):
        with self.assertRaisesRegex(ValueError, "leakage"):
            e.prepare_live(race(with_results=True))
        v=race()
        v["rows"][0]["finish"]=None
        e.prepare_live(v)
        v["rows"][0]["finish"]=1
        with self.assertRaisesRegex(ValueError, "leakage"):
            e.prepare_live(v)

    def test_deadline_and_lead_guard(self):
        v=race()
        v["captured_at"] = "2026-11-02T11:59:00+09:00"
        with self.assertRaisesRegex(ValueError, "predeadline"):
            e.prepare_live(v)
        v["captured_at"] = "2026-11-02T11:40:00+09:00"
        with self.assertRaisesRegex(ValueError, "predeadline"):
            e.prepare_live(v, observed_at="2026-11-02T12:01:00+09:00")

    def test_stale_predeadline_data_rejected(self):
        with self.assertRaisesRegex(ValueError, "Stale source"):
            e.prepare_live(race(), observed_at="2026-11-02T11:46:01+09:00")

    def test_entrant_identity_guard(self):
        r=race()
        r["rows"][2]["lane"]=2
        with self.assertRaises(ValueError):
            e.prepare_live(r)

    def test_alerts_only_owned_predeparture_data(self):
        raw=race()
        raw["rows"][2]["exhibition_time"]=6.53
        raw["rows"][3]["exhibition_course"]=5
        raw["rows"][3]["tilt"]=1
        s=e.prepare_live(raw)
        a=e.derive_alerts(s)
        self.assertTrue(any(x["kind"]=="outer_exhibition_advantage" and x["lane"]==3 for x in a))
        self.assertTrue(any(x["kind"]=="entry_changed" and x["lane"]==4 for x in a))
        self.assertTrue(any(x["kind"]=="tilt_jump" and x["lane"]==4 for x in a))

    def test_training_only_prior_days(self):
        past=[race(day="20261101", rno=i, with_results=True) for i in range(1, 5)]
        now=race(day="20261102", rno=5, with_results=True, first=1)
        after=race(day="20261103", rno=6, with_results=True, first=1)
        p=e.historical_evidence(past+[now,after], "20261102", "23", min_leader_races=2)
        self.assertEqual(p["race_count"],4)
        self.assertEqual(p["models"]["2"]["leader_races"],4)
        self.assertEqual(p["models"]["1"]["leader_races"],0)
        self.assertEqual(p["models"]["2"]["top_followers"][0]["second"],1)
        self.assertEqual(p["models"]["2"]["top_followers"][0]["third"],5)

    def test_insufficient_never_fake_frequencies(self):
        h=e.historical_evidence([race(day="20261101",with_results=True)], "20261102", "23")
        self.assertEqual(h["models"]["2"]["status"],"insufficient_leader_sample")
        self.assertEqual(h["models"]["2"]["top_followers"],[])

    def test_secondary_archive_not_live(self):
        s=e.prepare_live(race())
        foot={
            "race_id":s["race_id"],"status":"ok",
            "acquisition":{"source_family":"BoatraceCSV_secondary",
                "retrieved_at":"2026-11-02T11:50:00+09:00",
                "published_at":None},
            "rows":[{"lane":i,"racer_id":str(4000+i),"lap_time":36.6} for i in range(1,7)]
        }
        v=e.original_exhibition(foot,s)
        self.assertEqual(v["status"],"retrospective_or_unverified_not_used")
        self.assertIsNone(v["measurements"])

    def test_verified_official_original_six_id(self):
        s=e.prepare_live(race())
        foot={
            "race_id":s["race_id"],"status":"ok",
            "acquisition":{"source_family":"venue_official_verified",
                "retrieved_at":"2026-11-02T11:40:00+09:00",
                "published_at":"2026-11-02T11:39:00+09:00"},
            "rows":[{"lane":i,"racer_id":str(4000+i),"lap_time":36.6} for i in range(1,7)]
        }
        self.assertEqual(e.original_exhibition(foot,s)["status"],"verified_predeadline")
        foot["rows"][1]["racer_id"]="notmatch"
        self.assertEqual(e.original_exhibition(foot,s)["status"],"retrospective_or_unverified_not_used")

    def test_report_does_not_claim_ready_or_ev(self):
        s=e.prepare_live(race())
        h=e.historical_evidence([race(day="20261101",with_results=True)], "20261102","23")
        report=e.research_report(s,h)
        self.assertFalse(report["ready_for_betting"])
        self.assertIsNone(report["ev"])
        self.assertIsNone(report["estimated_trifecta_distribution"])
        self.assertFalse(report["result_consulted"])
        self.assertFalse(report["source_families"]["third_party_site_api_integrated"])

    def test_foreign_profile_rejected(self):
        with self.assertRaisesRegex(ValueError, "future evidence"):
            e.research_report(e.prepare_live(race()),
                e.historical_evidence([], "20261101","23"))

    def test_ev_only_after_calibration(self):
        self.assertIsNone(e.ev_only_after_validation({}, {}, False)["ev"])
        with self.assertRaisesRegex(ValueError, "120"):
            e.ev_only_after_validation({"1-2-3":1.0}, {}, True)
        probs={combo:1/120 for combo in e.COMBOS}
        r=e.ev_only_after_validation(probs,{"1-2-3":150},True)
        self.assertEqual(r["ev"]["1-2-3"],1.25)

if __name__ == "__main__":
    unittest.main()
