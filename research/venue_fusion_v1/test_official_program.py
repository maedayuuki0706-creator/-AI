"""Offline official input + main-core bridge safety/regression, with real immutable K snapshots."""
import json
import os
from copy import deepcopy
from pathlib import Path
from unittest import TestCase, main, mock

from research.scenario_v2 import engine as scenario
from research.venue_fusion_v1.official_program import from_frozen_official
from research.venue_fusion_v1.offline_pilot import build_offline,checked_old,compare,grade
from research.venue_fusion_v1 import engine as hybrid


STATE=os.getenv("VENUE_ARCHIVE_STATE")
CODE_SOURCE_SHA=os.getenv("VENUE_ARCHIVE_STATE_SHA","")
SAMPLE="20261020_03_01"
DAY="20261020"


def sample_path():
    return Path(STATE)/"inputs"/DAY/(SAMPLE+".json")


class RealFrozenOfficialTests(TestCase):
    @classmethod
    def setUpClass(cls):
        if not STATE:
            raise __import__("unittest").SkipTest("Immutable research state checkout not provided")
        cls.source=json.loads(sample_path().read_text(encoding="utf-8"))

    def test_official_source_hash_time_six_entrants(self):
        original=self.source
        src=from_frozen_official(original)
        self.assertEqual(src["meta"]["preprocessing_level"],
                         "main_official_core_without_profile_form_odds")
        self.assertFalse(src["meta"]["production_preprocessing_verified"])
        self.assertEqual(len(src["payload"]["boats"]),6)
        self.assertEqual({b["racer_id"] for b in src["payload"]["boats"]},
                         {str(b["racer_id"]) for b in original["boats"]})
        self.assertEqual(src["payload"]["trifecta_odds"],{})
        self.assertTrue(all(b["historical_profile_applied"] is False for b in src["payload"]["boats"]))
        self.assertTrue(all(b["previous_form_applied"] is False for b in src["payload"]["boats"]))
        # Read production parser through a patched fetch to make sure the
        # captured HTML is suitable for actual deployed program parsing.
        import direct_discord_notify as production
        html=original["official_originals"]["racelist"]["html"]
        with mock.patch.object(production,"fetch",return_value=html):
            main_program=production.parse_racelist_boats(DAY,"03",1)
        self.assertEqual([b["racer_id"] for b in main_program],
                         [b["racer_id"] for b in src["payload"]["boats"]])
        self.assertEqual([b["win_rate"] for b in main_program],
                         [b["win_rate"] for b in src["payload"]["boats"]])
        pre_html=original["official_originals"]["beforeinfo"]["html"]
        main_preview=production.parse_beforeinfo(pre_html)
        self.assertTrue(main_preview["entry_observed"])
        self.assertEqual(main_preview["exhibition_count"],6)
        self.assertEqual(
            {k:v["predicted_course"] for k,v in main_preview["boats"].items()},
            {b["lane"]:b["predicted_course"] for b in src["payload"]["boats"]}
        )

    def test_real_original_receipt_bound_before_deadline(self):
        snapshot,old,receipt,review=checked_old(Path(STATE),DAY,SAMPLE)
        self.assertEqual(scenario.digest(snapshot),old["snapshot_digest"])
        self.assertTrue(receipt["complete_originals_verified"])
        self.assertLess(scenario.aware(receipt["checked_at"]),
                        scenario.aware(old["deadline_at"]))
        self.assertTrue(review.exists())

    def test_original_program_mutation_is_rejected(self):
        original=deepcopy(self.source)
        original["official_originals"]["racelist"]["html"]+="spam"
        with self.assertRaisesRegex(ValueError,"SHA256"):
            from_frozen_official(original)
        original=deepcopy(self.source)
        original["official_originals"]["beforeinfo"]["url"]="https://wrong.example.com/"
        with self.assertRaisesRegex(ValueError,"URL"):
            from_frozen_official(original)

    def test_source_after_deadline_rejected(self):
        original=deepcopy(self.source)
        original["official_originals"]["beforeinfo"]["observed_at"]="2026-10-20T11:20:00+09:00"
        with self.assertRaisesRegex(ValueError,"after cutoff"):
            from_frozen_official(original)

    def test_source_older_than_two_minutes_rejected(self):
        original=deepcopy(self.source)
        original["official_originals"]["racelist"]["observed_at"]="2026-10-20T10:48:00+09:00"
        with self.assertRaisesRegex(ValueError,"far apart"):
            from_frozen_official(original)

    def test_six_boat_ids_courses_motors_must_match_archive(self):
        original=deepcopy(self.source)
        original["boats"][0]["racer_id"]="9999"
        with self.assertRaisesRegex(ValueError,"racer ID"):
            from_frozen_official(original)
        original=deepcopy(self.source)
        original["boats"][0]["course"]=6
        with self.assertRaisesRegex(ValueError,"Unique lanes, courses"):
            from_frozen_official(original)
        original=deepcopy(self.source)
        original["boats"][0]["motor_number"]=999
        with self.assertRaisesRegex(ValueError,"motor number"):
            from_frozen_official(original)

    def test_replay_main_core_yuuki_venue_but_never_delivered(self):
        now="2026-10-20T14:05:00+09:00"
        x=build_offline(self.source,generated_at=now)
        self.assertEqual(x["main_model_version"],hybrid.EXPECTED_MAIN_VERSION)
        self.assertFalse(x["main_full_delivery_parity"])
        self.assertFalse(x["count_as_prospective"])
        self.assertEqual(x["status"],"retrospective_replay")
        self.assertEqual(len(x["main_120_rank"]),120)
        self.assertEqual(len(x["scenario_all_six"]),6)
        self.assertTrue(all(v["win_paths"] and v["loss_paths"] for v in x["scenario_all_six"]))
        for value in x["cards"].values():
            self.assertEqual(len(value),10)
            self.assertEqual(len(set(value)),10)
        self.assertEqual(x["cards"]["official_main_core_plus_yuuki"],
                         x["cards"]["official_main_core_plus_yuuki_plus_venue"])
        self.assertFalse(x["venue_validated_adjustment_active"])
        # Applying the original full-main parity gate to this input MUST fail.
        real_capture=from_frozen_official(self.source)
        with self.assertRaisesRegex(ValueError,"official pre-race"):
            hybrid.generate(self.source,real_capture,mode="replay",now=now)

    def test_bounded_pilot_on_locked_state_snapshot(self):
        assert len(CODE_SOURCE_SHA)==40
        summary,rows,rejected=compare([DAY],Path(STATE),source_sha=CODE_SOURCE_SHA,
                                      now="2026-10-20T14:06:00+09:00")
        self.assertGreater(summary["reconstructed"],0)
        self.assertEqual(summary["new_prospective_predicted_races"],0)
        self.assertEqual(summary["source_sha"],CODE_SOURCE_SHA)
        self.assertTrue(summary["originals_not_modified"])
        for row in rows:
            self.assertTrue(row["original_receipt_before_deadline"])
            self.assertFalse(row["new_cards_predeadline_received"])
            self.assertFalse(row["main_full_delivery_parity"])
            self.assertTrue(row["retrospective_replay"])
        for v in summary["by_venue"].values():
            for k in ("original_venue_v1","official_main_core",
                      "official_main_core_plus_yuuki","official_main_core_plus_yuuki_plus_venue"):
                self.assertIn(k,v["comparison"])
        # Missing/failed sources are visible, not counted as misses.
        self.assertEqual(len(rows)+len(rejected),summary["original_saved_inputs_seen"])

    def test_grader_head_second_third_distinctions(self):
        item={"cards":{
            "official_main_core":["1-2-3"]+[
                "2-3-4","3-4-5","4-5-6","5-6-1","6-1-2","1-3-2","2-4-3","3-5-4","4-6-5"],
            "official_main_core_plus_yuuki":["1-2-6"]+[
                "1-2-3","2-3-4","3-4-5","4-5-6","5-6-1","6-1-2","1-3-2","2-4-3","3-5-4"],
            },"scenario_formation_candidates":["1-2-3"]}
        graded=grade(item,"1-2-6",{"1-2-6":1870})
        self.assertEqual(graded["official_main_core"]["selection_reason"],
                         "3rd_missing_given_head_2nd")
        self.assertEqual(graded["official_main_core_plus_yuuki"]["return_yen"],1870)
        self.assertEqual(graded["official_main_core_plus_yuuki"]["roi_pct"],187)
        self.assertFalse(graded["official_main_core_plus_yuuki"]["outcome_in_scenario"])


if __name__=="__main__":
    main()
