"""Tests for a result-isolated, immutable 120-combination research index."""
import json
from itertools import permutations
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research.scenario_v2 import engine as scenario
from research.trifecta_index_v1.index import build_index, evaluate, save_once


COMBOS = sorted("-".join(map(str, p)) for p in permutations(range(1, 7), 3))
RACE = "20261021_06_03"
META = {
    "day": "20261021", "jcd": "06", "rno": 3, "race_id": RACE,
    "captured_at": "2026-10-21T11:00:00+09:00",
    "deadline_at": "2026-10-21T11:15:00+09:00",
}


def frozen(record):
    record["digest"] = scenario.digest(record)
    return record


def scenario_record():
    lanes = []
    for lane in range(1, 7):
        combo = f"{lane}-{(lane % 6) + 1}-{((lane + 1) % 6) + 1}"
        branch = {
            "id": f"{lane}:mock:{lane}", "supported_observations": lane % 3,
            "formations": [{"combination": combo}],
        }
        lanes.append({"lane": lane, "hypotheses": [branch]})
    return frozen({
        "version": "yuuki-scenario-research-v2", "status": "research_only",
        "meta": dict(META), "generated_at": "2026-10-21T11:02:00+09:00",
        "lanes": lanes,
        "virtual_card": {"picks": COMBOS[:10]},
    })


def specialist_record():
    common = scenario_record()
    return frozen({
        "version": "venue-specialists-shadow-v1.1-log-recovery",
        "research_only": True, "jcd": "06", "model": "浜名湖くん",
        "race_id": RACE, "common_v2_digest": common["digest"], "common_v2": common,
        "lane_audits": [{"lane": n, "score": 0.0} for n in range(1, 7)],
        "virtual_card": [{"combination": c} for c in COMBOS[:10]],
        "created_at": "2026-10-21T11:02:00+09:00",
    })


def phase2_record():
    lanes = scenario_record()["lanes"]
    native = [{"combination": c, "historical_score": 1 / (n + 1)}
              for n, c in enumerate(reversed(COMBOS))]
    return frozen({
        "version": "four-venue-phase2-ab-v0.2-unvalidated",
        "research_only": True, "venue_code": "06", "variant": "B",
        "meta": dict(META), "generated_at": "2026-10-21T11:02:00+09:00",
        "lanes": lanes, "virtual_card": native[:10], "not_selected": native[10:],
    })


class TrifectaIndexTests(unittest.TestCase):
    def test_yuuki_all_120_and_ties(self):
        result = build_index(scenario_record(), "yuuki_v2")
        scenario.verify(result)
        self.assertEqual(result["model"], "新ゆうき")
        self.assertEqual([x["rank"] for x in result["ranks"]], list(range(1, 121)))
        self.assertEqual(set(x["combination"] for x in result["ranks"]), set(COMBOS))
        self.assertTrue(any(x["unscored_fallback"] for x in result["ranks"]))
        self.assertTrue(any(x["tied_count"] > 1 for x in result["ranks"]))
        self.assertFalse(result["probabilities_calibrated"])
        self.assertFalse(result["count_as_prospective"])

    def test_all_four_venue_names(self):
        for code, name in (("03", "江戸川くん"), ("06", "浜名湖くん"),
                           ("16", "児島くん"), ("23", "唐津くん")):
            doc = specialist_record()
            doc["jcd"], doc["model"] = code, name
            doc["race_id"] = f"20261021_{code}_03"
            doc["common_v2"]["meta"]["jcd"] = code
            doc["common_v2"]["meta"]["race_id"] = doc["race_id"]
            frozen(doc["common_v2"])
            doc["common_v2_digest"] = doc["common_v2"]["digest"]
            frozen(doc)
            result = build_index(doc, "venue_v1")
            self.assertEqual(result["model"], name)
            self.assertEqual(len(result["ranks"]), 120)

    def test_phase2_preserves_native_ranking(self):
        doc = phase2_record()
        result = build_index(doc, "venue_phase2")
        expected = [x["combination"] for x in doc["virtual_card"] + doc["not_selected"]]
        self.assertEqual([x["combination"] for x in result["ranks"]], expected)
        self.assertTrue(result["native_rank_preserved"])
        self.assertEqual(result["ranks"][0]["rank"], 1)
        self.assertEqual(result["ranks"][-1]["rank"], 120)

    def test_reject_duplicate_phase2_combinations(self):
        doc = phase2_record()
        doc["not_selected"][0]["combination"] = doc["virtual_card"][0]["combination"]
        frozen(doc)
        with self.assertRaises(ValueError):
            build_index(doc, "venue_phase2")

    def test_review_uses_separate_verified_result(self):
        idx = build_index(scenario_record(), "yuuki_v2")
        official = {"race_id": RACE, "observed_at": "2026-10-21T11:16:00+09:00",
                    "normal_verified": True, "refund_lanes": [],
                    "trifecta": idx["ranks"][19]["combination"]}
        result = evaluate(idx, official)
        self.assertEqual(result["actual_rank"], 20)
        self.assertTrue(result["top_n_hit"]["20"])
        self.assertFalse(result["top_n_hit"]["10"])
        self.assertFalse(result["count_as_prospective"])
        scenario.verify(result)
        official["observed_at"] = "2026-10-21T11:10:00+09:00"
        with self.assertRaises(ValueError):
            evaluate(idx, official)

    def test_accident_is_excluded(self):
        idx = build_index(scenario_record(), "yuuki_v2")
        official = {"race_id": RACE, "observed_at": "2026-10-21T11:16:00+09:00",
                    "normal_verified": False, "refund_lanes": [3], "trifecta": COMBOS[0]}
        result = evaluate(idx, official)
        self.assertFalse(result["valid_normal_race"])
        self.assertIsNone(result["actual_rank"])

    def test_immutable_write_and_tamper_check(self):
        idx = build_index(specialist_record(), "venue_v1")
        with TemporaryDirectory() as d:
            target = Path(d) / "forecasts" / "venue-v1-06" / (RACE + ".json")
            save_once(idx, target)
            self.assertEqual(json.loads(target.read_text())["digest"], idx["digest"])
            with self.assertRaises(FileExistsError):
                save_once(idx, target)
            idx["ranks"][0]["index_0_100"] = -1
            with self.assertRaises(ValueError):
                save_once(idx, Path(d) / "forged.json")


if __name__ == "__main__":
    unittest.main()
