"""Read-only source learning and structural-history regression (no live requests)."""
from copy import deepcopy
from pathlib import Path
import json
import unittest

from research.venue_knowledge import lab
from research.venue_knowledge import archive_audit

ROOT = Path(__file__).resolve().parent


def catalog():
    return (
        json.loads((ROOT/"official_sources.json").read_text(encoding="utf-8")),
        json.loads((ROOT/"hypotheses.json").read_text(encoding="utf-8"))
    )


class FakeResponse:
    headers={"Content-Type":"text/html; charset=utf-8",
             "ETag":'"abc"',"Last-Modified":"Sun, 18 Oct 2026 12:00:00 GMT"}


class VenueKnowledgeTests(unittest.TestCase):
    def test_all_four_venues_with_official_citations_and_no_model_effects(self):
        a,b=catalog()
        v=lab.validate_catalog(a,b)
        self.assertEqual(v["source_count"],10)
        self.assertEqual(v["hypothesis_count"],12)
        self.assertEqual(v["prediction_weights_applied"],0)
        self.assertEqual(set(v["hypotheses_by_venue"]),set(lab.VENUES))
        self.assertTrue(all(h["review_status"]=="article_inspired_unvalidated" for h in b["hypotheses"]))

    def test_evidence_cannot_auto_promote_on_article_update(self):
        a,b=catalog()
        modified=deepcopy(b)
        modified["hypotheses"][0]["predictive_weight"]=.2
        with self.assertRaisesRegex(ValueError,"must not automatically change"):
            lab.validate_catalog(a,modified)
        modified=deepcopy(b)
        modified["hypotheses"][0]["auto_promote"]=True
        with self.assertRaisesRegex(ValueError,"must not automatically change"):
            lab.validate_catalog(a,modified)
        modified=deepcopy(b)
        modified["hypotheses"][0]["review_status"]="holdout_passed_for_review"
        with self.assertRaisesRegex(ValueError,"independent result"):
            lab.validate_catalog(a,modified)

    def test_all_hypotheses_must_cite_same_venue_primary_sources(self):
        a,b=catalog()
        modified=deepcopy(b)
        modified["hypotheses"][0]["source_ids"]=["hamanako-water"]
        with self.assertRaisesRegex(ValueError,"same-venue"):
            lab.validate_catalog(a,modified)
        modified=deepcopy(a)
        modified["sources"][0]["source_id"]=a["sources"][1]["source_id"]
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            lab.validate_catalog(modified,b)

    def test_block_source_network_misuse(self):
        a,b=catalog()
        for bad in ["http://www.boatrace.jp/test","https://evil.com/boat",
                    "https://www.boatrace.jp.evil.com/safety",
                    "https://u:p@www.boatrace.jp/test"]:
            changed=deepcopy(a)
            changed["sources"][0]["url"]=bad
            with self.assertRaisesRegex(ValueError,"Untrusted"):
                lab.validate_catalog(changed,b)

    def test_metadata_only_scan_no_full_copy(self):
        a,_=catalog()
        called=[]
        def fake_fetch(url):
            called.append(url)
            return FakeResponse(),b"<html><head><title>  Test Boat Official </title></head><body>" + b"X"*550 + b"</body></html>"
        rows=lab.scan_sources(a["sources"][:2],fetcher=fake_fetch,now="2026-10-19T12:00:00+00:00")
        self.assertEqual(len(rows),2)
        self.assertTrue(all(x["status"]=="fetched" for x in rows))
        self.assertEqual(rows[0]["document_title"],"Test Boat Official")
        self.assertEqual(len(rows[0]["content_sha256"]),64)
        self.assertFalse(any("body" in x for x in rows))
        self.assertFalse(any("X"*50 in json.dumps(x) for x in rows))
        self.assertTrue(all(x["article_parsed_for_prediction"] is False for x in rows))
        self.assertEqual(called,[x["url"] for x in a["sources"][:2]])

    def test_fetch_error_is_missing_not_fake_fact(self):
        a,_=catalog()
        def bad(_):
            raise TimeoutError("please retry")
        rows=lab.scan_sources(a["sources"][:1],fetcher=bad)
        self.assertEqual(rows[0]["status"],"unavailable")
        self.assertNotIn("content_sha256",rows[0])

    def test_learning_card_references_no_article_reprint(self):
        a,b=catalog()
        s=lab.report_md(a,b,lab.validate_catalog(a,b))
        self.assertIn("唐津",s)
        self.assertIn("浜名湖",s)
        self.assertIn("学習",s)
        self.assertIn("自動反映禁止",s)
        self.assertIn(a["sources"][0]["url"],s)

    def test_karatsu_pit_change_quarantine_transition_month(self):
        self.assertEqual(archive_audit.era("23","2025-11-30"),"before_dec2025_pit_change")
        self.assertEqual(archive_audit.era("23","2025-12-10"),"excluded_transition_dec2025")
        self.assertEqual(archive_audit.era("23","2026-01-01"),"after_dec2025_pit_change")

    def test_hamanako_motor_new_generation_kept_separate(self):
        self.assertEqual(archive_audit.era("06","2026-04-08"),"before_current_motor_20260409")
        self.assertEqual(archive_audit.era("06","2026-04-09"),"current_motor_period_20260409")

    def test_history_is_descriptive_only_and_has_wind_groups(self):
        example=[
            {"race_id":"r1","venue_code":"23","date":"2025-11-29",
             "normal_eligible":True,"official_verified":True,
             "trifecta_from_finish":"1-3-4","wind_m":7,"entry_changed":True,
             "boats":[{"motor_number":3}]},
            {"race_id":"r2","venue_code":"23","date":"2026-01-09",
             "normal_eligible":True,"official_verified":True,
             "trifecta_from_finish":"5-1-2","wind_m":1,"entry_changed":False,
             "boats":[{"motor_number":3}]},
            {"race_id":"r3","venue_code":"06","date":"2026-04-09",
             "normal_eligible":True,"official_verified":True,
             "trifecta_from_finish":"2-1-4","wind_m":2,"entry_changed":False,
             "boats":[{"motor_number":51}]},
            {"race_id":"r4","venue_code":"16","date":"2026-04-09",
             "normal_eligible":True,"official_verified":True,
             "trifecta_from_finish":"1-2-4","wind_m":None,"entry_changed":None,
             "boats":[{"motor_number":18}]}
        ]
        r=archive_audit.summarize(example)
        self.assertTrue(r["analysis_only"])
        self.assertFalse(r["historical_result_data_available_at_original_deadline"])
        a=r["groups"]["23/before_dec2025_pit_change"]
        self.assertEqual(a["wind_band_counts"]["6m+"],1)
        self.assertEqual(a["entry_changed_pct_when_known"],100)
        self.assertEqual(r["groups"]["23/after_dec2025_pit_change"]["head_lane1_pct"],0)
        self.assertEqual(r["groups"]["06/current_motor_period_20260409"]["normal_graded"],1)
        self.assertFalse(a["learned_predictive_effect"])
        self.assertIn("唐津",archive_audit.markdown(r))

    def test_history_duplicate_identity_must_fail(self):
        r={"race_id":"duplicate","venue_code":"03","date":"2026-05-01",
           "official_verified":True,"normal_eligible":True,
           "trifecta_from_finish":"1-2-3"}
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            archive_audit.summarize([r,r])


if __name__=="__main__":
    unittest.main()
