"""Yuuki research-only evidence audit for frozen fusion-shadow race journals.

Reads prospective records from a separately cloned research-fusion-shadow-state branch.
Never imports delivery modules, connects to a webhook, or modifies original records.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

VERSION = "yuuki-v3-shadow-audit-v1"
COMPARISON = ("fusion", "control_existing_10", "control_hiyori_10",
              "control_sheet_db_10", "control_knowledge_v2_10")


def _time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _single_outcome(result):
    official = result.get("official_result", result)
    if official.get("status") != "settled" or official.get("refund_lanes") or official.get("special_per_100"):
        return None
    payouts = official.get("payouts") or {}
    if len(payouts) != 1:
        return None
    pick, amount = next(iter(payouts.items()))
    lanes = str(pick).split("-")
    if (len(lanes) != 3 or any(n not in "123456" or len(n) != 1 for n in lanes)
            or len(set(lanes)) != 3 or not isinstance(amount, (int, float)) or amount <= 0):
        return None
    return pick, int(amount), official


def analyze_race(prediction, verification):
    evaluation = verification.get("evaluation") or verification
    outcome = _single_outcome(evaluation)
    if outcome is None:
        return None, "unsettled_abnormal_refund"
    actual, payout, official = outcome
    deadline = _time(prediction.get("deadline_at"))
    created = _time(prediction.get("created_at"))
    committed = _time(evaluation.get("prediction_committed_at")
                      or official.get("prediction_committed_at"))
    if not (deadline and created and committed and created < deadline and committed < deadline):
        return None, "unproven_predeadline"
    if (verification.get("prediction_digest") or evaluation.get("prediction_digest")) != prediction.get("digest"):
        return None, "digest_mismatch"
    if (verification.get("key") or evaluation.get("key")) != prediction.get("key"):
        return None, "key_mismatch"
    if prediction.get("mode") != "prospective_shadow" or not prediction.get("research_only"):
        return None, "not_prospective_research"
    if len(prediction.get("boat_scenarios") or []) != 6 or not all(isinstance(x, dict) for x in prediction["boat_scenarios"]):
        return None, "invalid_scenarios"

    model = prediction.get("models") or {}
    heads = prediction.get("head_probabilities") or {}
    winner = actual.split("-")[0]
    top = max(heads, key=lambda h: float(heads[h])) if heads else None
    head_prob = float(heads.get(winner, 0.0))
    # Probability score is only diagnostic because this model is uncalibrated.
    head_brier = sum((float(heads.get(str(i), 0.0)) - (winner == str(i))) ** 2 for i in range(1, 7))
    cards = {}
    for name in COMPARISON:
        picks = list(dict.fromkeys((model.get(name) or {}).get("picks") or []))
        # Unit stake comparison: at most one exact 3連単 can win per settled race.
        cards[name] = {
            "points": len(picks), "stake": 100 * len(picks),
            "return": payout if actual in picks else 0,
            "hit": int(actual in picks),
            "head_covered": winner in {p.split("-")[0] for p in picks},
        }

    selected = cards["fusion"]
    ticket_reason = ("hit" if selected["hit"] else
                     "head_covered_tail_missing" if selected["head_covered"] else
                     "winning_head_not_in_picks")

    winner_scenario = next((x for x in prediction.get("boat_scenarios", [])
                            if str(x.get("lane")) == winner), None)
    post = official.get("race_details") or {}
    method = post.get("method")
    predicted_methods = (winner_scenario or {}).get("anticipated_methods") or []
    method_match = (method in predicted_methods) if method and predicted_methods else None
    verified_condition_count = 0
    condition_supported = 0
    checks = (evaluation.get("scenario_review") or {}).get("boats") or []
    for lane in checks:
        if str(lane.get("lane")) != winner:
            continue
        for check in lane.get("condition_checks") or []:
            if check.get("observed") is not None:
                verified_condition_count += 1
                condition_supported += int(check["observed"] is True)
    return {
        "key": prediction["key"], "venue": prediction.get("venue"),
        "outcome": actual, "payout": payout,
        "model_top_head": top, "actual_head": winner,
        "model_top_head_correct": top == winner, "head_brier": head_brier,
        "winning_head_model_probability": head_prob,
        "ticket_failure": ticket_reason, "cards": cards,
        "method": method, "predicted_methods_for_winner": predicted_methods,
        "winning_method_compatible": method_match,
        "verified_pre_race_condition_count": verified_condition_count,
        "observed_condition_positive": condition_supported,
        "causal_attribution": "unverified_without_race_video",
    }, None


def audit(state_root: Path, days):
    records = []
    excluded = Counter()
    for day in days:
        prediction_dir = state_root / "predictions" / day
        verification_dir = state_root / "official_verifications" / day
        if not prediction_dir.is_dir():
            excluded["missing_day_predictions"] += 1
            continue
        for file in sorted(prediction_dir.glob("*.json")):
            verification_file = verification_dir / file.name
            if not verification_file.is_file():
                excluded["not_officially_verified"] += 1
                continue
            try:
                pred = json.loads(file.read_text(encoding="utf-8"))
                verification = json.loads(verification_file.read_text(encoding="utf-8"))
                item, reason = analyze_race(pred, verification)
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                item, reason = None, "malformed_log"
            if reason:
                excluded[reason] += 1
            else:
                records.append(item)
    tallies = {}
    for name in COMPARISON:
        stake = sum(r["cards"][name]["stake"] for r in records)
        returned = sum(r["cards"][name]["return"] for r in records)
        tallies[name] = {
            "races": len(records), "stake_yen": stake,
            "returned_yen": returned, "hits": sum(r["cards"][name]["hit"] for r in records),
            "roi_pct": round(100 * returned / stake, 2) if stake else None,
        }
    possible = [r["winning_method_compatible"] for r in records
                if r["winning_method_compatible"] is not None]
    return {
        "version": VERSION, "mode": "research_only_offline",
        "days": list(days), "verified_races": len(records),
        "excluded": dict(excluded),
        "failure_types": dict(Counter(r["ticket_failure"] for r in records)),
        "top_head_correct": sum(r["model_top_head_correct"] for r in records),
        "head_brier_mean": round(sum(r["head_brier"] for r in records) / len(records), 6)
            if records else None,
        "winning_method_compatible": {
            "assessed": len(possible), "compatible": sum(x is True for x in possible),
            "not_verified": len(records) - len(possible),
        },
        "cards": tallies,
        "cases": records,
        "limitations": [
            "Analysis is conditional on archived, verified, pre-deadline predictions.",
            "Expected probabilities and scenario coefficients have not been calibrated.",
            "Winning method compatibility is not proof of predicted physical race tactics.",
            "Equal 10-ticket stakes are not risk-adjusted or out-of-time proof.",
            "No future data are fed back into ticket generation.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--days", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.state_root, args.days)
    if not report["verified_races"]:
        raise SystemExit("no qualified verified races; refusing to publish an empty success report")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
