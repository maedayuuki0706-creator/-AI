"""Offline, read-only exploratory replay; no collector or delivery imports."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path

from research_fusion_roi_replay import ALL_COMBOS, check_unique, read_json, score, verify

SOURCE_SHA = "f4b1f11a7a7fd542ec49ee475900a7396f2a727e"
POLICY = "new-yuuki-six-boat-v2"


def choose(record: dict, reserve_heads: bool = False) -> list[str]:
    """Uses only frozen pre-race fields. Outcomes cannot enter this function."""
    rows = record["trifecta"]
    if len(rows) != 120 or {r["combination"] for r in rows} != ALL_COMBOS:
        raise ValueError("Expected 120 unique combinations")
    for row in rows:
        for field in ("probability", "rank_score", "cover_score"):
            value = row[field]
            if type(value) not in (int, float) or not isfinite(value) or value < 0:
                raise ValueError("Invalid frozen score")
    if abs(sum(r["probability"] for r in rows) - 1) > 1e-6:
        raise ValueError("Probabilities do not sum to one")
    ranked = sorted(rows, key=lambda r: (-r["rank_score"], r["combination"]))
    main = [r["combination"] for r in ranked[:6]]
    remaining = sorted((r for r in ranked if r["combination"] not in main),
                       key=lambda r: (-r["cover_score"], r["combination"]))
    cover = []
    if reserve_heads:
        supported = {s["lane"] for s in record["boat_scenarios"]
                     if record["head_probabilities"][str(s["lane"])] >= .05
                     and any(c["log_factor"] > 0 for c in s["factor_components"])}
        covered = {int(c[0]) for c in main}
        for row in remaining:
            lane = int(row["combination"][0])
            if lane in supported and lane not in covered and len(cover) < 4:
                cover.append(row["combination"])
                covered.add(lane)
    for row in remaining:
        if len(cover) == 4:
            break
        if row["combination"] not in cover:
            cover.append(row["combination"])
    return check_unique(main + cover)


def load_candidate(path: Path) -> tuple[dict, str]:
    candidate = read_json(path)
    expected = {"probabilities": "保存済みの展開補正後確率を維持",
                "main": "rank_score降順の6点", "cover": "本線を除くcover_score降順の4点",
                "alternate_head_reservation": False, "tie_break": "combination昇順",
                "unit_yen": 100}
    if (candidate.get("name") != "no_alt_head_v1" or
            candidate.get("research_only") is not True or
            candidate.get("production_enabled") is not False or
            candidate.get("rule") != expected):
        raise ValueError("Candidate differs from frozen no_alt_head_v1 rule")
    value = json.dumps(candidate, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False)
    return candidate, sha256(value.encode()).hexdigest()


def replay(root: Path, candidate_path: Path) -> dict:
    _, candidate_digest = load_candidate(candidate_path)
    paths = sorted((root / "predictions").glob("*/*.json"))
    if not paths:
        raise ValueError("No predictions")
    excluded = Counter()
    totals = {}
    checked = 0
    for path in paths:
        record = read_json(path)
        if record.get("code_sha") != SOURCE_SHA:
            excluded["other_code_version"] += 1
            continue
        companions = [root / d / path.parent.name / path.name
                      for d in ("checkpoints", "results", "evaluations")]
        if not all(p.is_file() for p in companions):
            raise ValueError("Missing companion: " + path.name)
        checkpoint, result, evaluation = map(read_json, companions)
        verify(path.stem, record, checkpoint, result, evaluation)
        model = record["models"]["fusion"]
        if model.get("selection_policy") != POLICY:
            raise ValueError("Unexpected policy")
        baseline = model["picks"]
        if choose(record, True) != baseline:
            raise ValueError("Cannot reproduce frozen tickets: " + path.name)
        original = score(baseline, result)
        reported = evaluation["models"]["fusion"]
        if (original["stake"] != reported["stake_yen"] or
                original["returned"] != reported["return_yen"] or
                original["hit"] != reported["hit"]):
            raise ValueError("Original evaluation mismatch")
        candidate = choose(record)
        checked += 1
        if result["status"] != "settled" or result.get("refund_lanes"):
            excluded["not_settled_or_has_refunds"] += 1
            continue
        for period in ("total", path.parent.name):
            for name, picks in (("baseline", baseline), ("no_alt_head_v1", candidate)):
                s = totals.setdefault(period, {}).setdefault(name, Counter())
                row = score(picks, result)
                s.update(races=1, hits=int(row["hit"]), stake_yen=row["stake"],
                         return_yen=row["returned"])
    if not checked or "total" not in totals:
        raise ValueError("No eligible records for pinned source version")
    for models in totals.values():
        for s in models.values():
            s["hit_rate_pct"] = round(100*s["hits"]/s["races"], 2)
            s["roi_pct"] = round(100*s["return_yen"]/s["stake_yen"], 2)
            s["profit_yen"] = s["return_yen"] - s["stake_yen"]
    return {"label": "EXPLORATORY_NOT_INDEPENDENT_VALIDATION", "research_only": True,
            "candidate_digest": candidate_digest, "source_code_sha": SOURCE_SHA,
            "reproduced_records": checked, "excluded": dict(excluded), "periods": totals}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--candidate", type=Path,
                        default=Path(__file__).with_name("research_no_alt_head_v1.json"))
    args = parser.parse_args()
    print(json.dumps(replay(args.state_root, args.candidate), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
