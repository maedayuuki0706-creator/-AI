"""Read-only held-out evaluation of the preregistered no-alt-head rule.

No scheduling, capture, notifications, production changes, or automatic promotion.
"""
import argparse
from collections import Counter
from datetime import datetime
from hashlib import sha256
import inspect
import json
from pathlib import Path

from research_fusion_roi_replay import read_json, score, verify, when
from research_no_alt_head_replay import choose, load_candidate, POLICY, SOURCE_SHA


def validate_plan(plan, candidate_path):
    _, candidate_digest = load_candidate(candidate_path)
    if (plan.get("name") != "no_alt_head_holdout_v1" or
            plan.get("research_only") is not True or
            plan.get("automatic_promotion") is not False or
            plan.get("scope") != "settled_without_refunds" or
            plan.get("source_code_sha") != SOURCE_SHA or plan.get("source_policy") != POLICY):
        raise ValueError("Unsupported validation plan")
    for key in ("start_day", "end_day"):
        datetime.strptime(plan[key], "%Y%m%d")
    if (plan["start_day"] < "20261016" or plan["end_day"] < plan["start_day"] or
            when(plan["registered_at"]).strftime("%Y%m%d") >= plan["start_day"]):
        raise ValueError("Plan must be fixed before the held-out period")
    if any(type(plan[k]) is not int or plan[k] < 1 for k in ("minimum_days", "minimum_races")):
        raise ValueError("Invalid evidence thresholds")
    if candidate_digest != plan["candidate_digest"]:
        raise ValueError("Candidate changed after registration")
    if sha256(inspect.getsource(choose).encode()).hexdigest() != plan["selector_sha256"]:
        raise ValueError("Selector changed after registration")


def evaluate(root, candidate_path, plan_path):
    plan = read_json(plan_path)
    validate_plan(plan, candidate_path)
    if not (root / "predictions").is_dir():
        raise ValueError("Missing predictions directory")
    counts = Counter()
    totals = {}
    days = set()
    observed_candidates = []
    for path in sorted((root / "predictions").glob("*/*.json")):
        day = path.parent.name
        if not plan["start_day"] <= day <= plan["end_day"]:
            counts["outside_window"] += 1
            continue
        record = read_json(path)
        if record["day"] != day:
            raise ValueError("Race date differs from path")
        counts["within_window"] += 1
        if (record.get("code_sha") != SOURCE_SHA or
                record["models"]["fusion"].get("selection_policy") != POLICY):
            counts["incompatible_source_or_policy"] += 1
            continue
        if when(record["created_at"]) < when(plan["registered_at"]):
            raise ValueError("Prediction predates plan")
        companions = [root / d / day / path.name for d in
                      ("checkpoints", "results", "evaluations")]
        missing = [d for d, p in zip(("checkpoint", "result", "evaluation"), companions)
                   if not p.is_file()]
        if missing:
            for item in missing: counts["missing_"+item] += 1
            counts["pending_records"] += 1
            continue
        checkpoint, result, evaluation = map(read_json, companions)
        verify(path.stem, record, checkpoint, result, evaluation)
        baseline = record["models"]["fusion"]["picks"]
        if choose(record, True) != baseline:
            raise ValueError("Cannot reproduce frozen baseline: " + path.name)
        original = score(baseline, result)
        saved = evaluation["models"]["fusion"]
        if (original["stake"], original["returned"], original["hit"]) != (
                saved["stake_yen"], saved["return_yen"], saved["hit"]):
            raise ValueError("Original evaluation mismatch")
        candidate = choose(record)
        if result["status"] != "settled" or result.get("refund_lanes"):
            counts["not_settled_or_has_refunds"] += 1
            continue
        counts["evaluated"] += 1
        days.add(day)
        observed_candidates.append({"key": path.stem, "prediction_digest": record["digest"],
                                    "checkpoint_commit": checkpoint["commit_sha"]})
        for period in ("total", day):
            for name, picks in (("baseline", baseline), ("no_alt_head_v1", candidate)):
                item = totals.setdefault(period, {}).setdefault(name, Counter())
                row = score(picks, result)
                item.update(races=1, hits=int(row["hit"]), stake_yen=row["stake"],
                            return_yen=row["returned"])
    for models in totals.values():
        for item in models.values():
            item["hit_rate_pct"] = round(100*item["hits"]/item["races"], 2)
            item["roi_pct"] = round(100*item["return_yen"]/item["stake_yen"], 2)
            item["profit_yen"] = item["return_yen"]-item["stake_yen"]
    status = "WAITING_FOR_ELIGIBLE_FUTURE_DATA" if not counts["evaluated"] else "PARTIAL_HOLDOUT"
    enough = counts["evaluated"] >= plan["minimum_races"] and len(days) >= plan["minimum_days"]
    if enough: status = "MINIMUM_SAMPLE_REACHED_REVIEW_REQUIRED"
    return {"research_only": True, "status": status, "automatic_promotion": False,
            "window": [plan["start_day"], plan["end_day"]],
            "candidate_digest": plan["candidate_digest"],
            "plan_digest": sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode()).hexdigest(),
            "counts": dict(counts), "evaluated_days": sorted(days), "periods": totals,
            "verified_records": observed_candidates,
            "collection_coverage": "UNKNOWN: prediction files do not enumerate all scheduled races",
            "note": "No data is not a zero-percent result; this program does not collect or schedule jobs."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--candidate", type=Path,
                        default=Path(__file__).with_name("research_no_alt_head_v1.json"))
    parser.add_argument("--plan", type=Path,
                        default=Path(__file__).with_name("research_no_alt_head_holdout_plan.json"))
    args = parser.parse_args()
    print(json.dumps(evaluate(args.state_root, args.candidate, args.plan),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
