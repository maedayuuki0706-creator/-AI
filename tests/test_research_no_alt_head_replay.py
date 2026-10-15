import copy
import json
from pathlib import Path
import tempfile
import unittest

from research_fusion_roi_replay import ALL_COMBOS
from research_no_alt_head_replay import choose, load_candidate, replay


def record():
    return {"trifecta": [{"combination": c, "probability": 1/120,
                         "rank_score": 120-i, "cover_score": 120-i}
                        for i, c in enumerate(sorted(ALL_COMBOS))],
            "boat_scenarios": [{"lane": 2, "factor_components": [{"log_factor": .1}]}],
            "head_probabilities": {"2": 1/6}}


class CandidateTests(unittest.TestCase):
    def test_removes_only_head_reservation(self):
        r = record()
        before = copy.deepcopy(r)
        plain, reserved = choose(r), choose(r, True)
        self.assertEqual(plain[:6], reserved[:6])
        self.assertEqual(plain, sorted(ALL_COMBOS)[:10])
        self.assertEqual(len(reserved), 10)
        self.assertTrue(any(c.startswith("2-") for c in reserved[6:]))
        self.assertFalse(any(c.startswith("2-") for c in plain))
        self.assertEqual(r, before)

    def test_results_cannot_change_selection(self):
        r = record()
        expected = choose(r)
        r["result"] = {"payouts": {"6-5-4": 100000}}
        self.assertEqual(choose(r), expected)

    def test_ties_are_deterministic(self):
        r = record()
        for row in r["trifecta"]:
            row["rank_score"] = row["cover_score"] = 1
        r["trifecta"].reverse()
        self.assertEqual(choose(r), sorted(ALL_COMBOS)[:10])

    def test_rejects_missing_duplicate_and_nonfinite_rows(self):
        for change in ("missing", "duplicate", "nan"):
            with self.subTest(change=change):
                r = record()
                if change == "missing": r["trifecta"].pop()
                elif change == "duplicate": r["trifecta"][0] = r["trifecta"][1]
                else: r["trifecta"][0]["cover_score"] = float("nan")
                with self.assertRaises(ValueError): choose(r)

    def test_rejects_modified_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)/"candidate.json"
            p.write_text(json.dumps({"name": "no_alt_head_v1", "production_enabled": True}))
            with self.assertRaises(ValueError): load_candidate(p)

    def test_missing_dataset_fails(self):
        config = Path(__file__).resolve().parents[1]/"research_no_alt_head_v1.json"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "No predictions"):
                replay(Path(directory), config)


if __name__ == "__main__":
    unittest.main()
