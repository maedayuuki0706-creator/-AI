import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.scenario_v2 import engine as e
from research.scenario_v2.adapters import from_fusion
from research.scenario_v2.batch import result_from_files, verify_git_source


def source_fixture():
    combos = sorted(e.COMBINATIONS)
    r = {"key": "20261016_06_07", "day": "20261016", "jcd": "06", "rno": 7,
         "deadline": "19:00", "deadline_at": "2026-10-16T19:00:00+09:00",
         "captured_at": "2026-10-16T18:50:00+09:00", "created_at": "2026-10-16T18:50:01.9+09:00",
         "pre_race_boats": [{"lane": i, "predicted_course": i, "racer_id": str(4000+i), "avg_st": .15,
                             "motor_top2_rate": 40, "exhibition_time": 6.7} for i in range(1, 7)],
         "pre_race_weather": {"wind_speed": 3}, "database": {"snapshot_at": "2026-10-16T18:40:00+09:00"},
         "hiyori_features": [{"lane": i, "preview": {"chokusen": -1, "mawariashi": 0, "shukai": 3700+i}} for i in range(1, 7)],
         "models": {"fusion": {"picks": combos[:10], "main_picks": combos[:6], "cover_picks": combos[6:10]}},
         "trifecta": [{"combination": c} for c in combos]}
    r["digest"] = e.digest(r)
    cp = {"key": r["key"], "prediction_digest": r["digest"], "eligible_checkpoint": True,
          "prediction_committed_at": "2026-10-16T18:50:03+09:00", "commit_sha": "a"*40}
    return r, cp


class AdapterBatchTests(unittest.TestCase):
    def test_sentinels_are_missing_not_best_times(self):
        r, cp = source_fixture(); d = from_fusion(r, cp)
        self.assertTrue(all(b["straight_time"] is None and b["turn_time"] is None for b in d["boats"]))
        self.assertEqual(d["boats"][0]["lap_time"], 37.01)
        self.assertEqual(len(d["boats"][0]["unavailable_observations"]), 2)
        e.generate(d, mode="replay", now="2026-10-17T00:00:00+09:00")

    def test_source_digest_and_checkpoint_identity(self):
        r, cp = source_fixture(); r["pre_race_boats"][0]["avg_st"] = .1
        with self.assertRaises(ValueError): from_fusion(r, cp)

    def test_timing_preview_cannot_come_from_another_race_or_racer(self):
        for field, value in [("hiduke",20261017), ("race_no",8), ("place_no",5), ("player_no",9999)]:
            r, cp = source_fixture();r["hiyori_features"][0]["preview"][field] = value
            r["digest"] = e.digest({k:v for k,v in r.items() if k != "digest"});cp["prediction_digest"] = r["digest"]
            with self.subTest(field=field), self.assertRaises(ValueError): from_fusion(r, cp)
        r, cp = source_fixture(); cp["key"] = "other"
        with self.assertRaises(ValueError): from_fusion(r, cp)

    def test_enriched_fields_rejected_before_projection(self):
        r, cp = source_fixture(); r["hiyori_features"][0]["preview"]["actual_st"] = .1
        r["digest"] = e.digest({k:v for k,v in r.items() if k != "digest"}); cp["prediction_digest"] = r["digest"]
        with self.assertRaises(ValueError): from_fusion(r, cp)

    def test_late_checkpoint_and_future_db_rejected(self):
        r, cp = source_fixture(); cp["prediction_committed_at"] = r["deadline_at"]
        with self.assertRaises(ValueError): from_fusion(r, cp)
        r, cp = source_fixture(); r["database"]["snapshot_at"] = "2026-10-16T18:55:00+09:00"
        r["digest"] = e.digest({k:v for k,v in r.items() if k != "digest"}); cp["prediction_digest"] = r["digest"]
        with self.assertRaises(ValueError): from_fusion(r, cp)

    def test_git_timestamp_precision_and_real_late_commit(self):
        r, cp = source_fixture()
        with patch("subprocess.check_output", side_effect=[json.dumps(r).encode(), "2026-10-16T09:50:01Z"]):
            verify_git_source(".", r, cp)
        with patch("subprocess.check_output", side_effect=[json.dumps(r).encode(), "2026-10-16T10:00:00Z"]):
            with self.assertRaises(ValueError): verify_git_source(".", r, cp)

    def test_git_object_content_must_match(self):
        r, cp = source_fixture(); other = copy.deepcopy(r); other["day"] = "20261015"
        other["digest"] = e.digest({k:v for k,v in other.items() if k != "digest"})
        with patch("subprocess.check_output", return_value=json.dumps(other).encode()):
            with self.assertRaises(ValueError): verify_git_source(".", r, cp)

    def test_no_postrace_details_is_not_filled(self):
        r, _ = source_fixture()
        outcome = {"prediction_digest": r["digest"], "evaluated_at": "2026-10-16T19:10:00+09:00",
                   "official_result": {"status": "settled", "payouts": {"1-2-3": 1400}, "source_url": "official"}}
        with tempfile.TemporaryDirectory() as tmp:
            got = result_from_files(r, outcome, tmp)
        self.assertNotIn("boats", got)
        self.assertIsNone(got["winning_method"])

    def test_missing_finish_is_not_invented_as_accident(self):
        r, _ = source_fixture()
        outcome = {"prediction_digest": r["digest"], "evaluated_at": "2026-10-16T19:10:00+09:00",
                   "official_result": {"status": "settled", "payouts": {"1-2-3": 1400}}}
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"20261016"/"06_07.json"; p.parent.mkdir()
            p.write_text(json.dumps({"day": "20261016", "jcd": "06", "rno": 7, "settled": True,
                                     "settled_at": "2026-10-16T19:10:00+09:00", "rows": [{"finish": None}]}))
            got = result_from_files(r, outcome, tmp)
        self.assertEqual(got["status"], "incomplete_finish")


if __name__ == "__main__": unittest.main()
