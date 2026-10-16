"""Official-result-only postmortem for pre-deadline remotely confirmed specialist logs.

No forecast regeneration or editing. Official trifecta is a result, NOT direct
proof of the winning tactical scenario or losing boats' actual manoeuvres.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from research.scenario_v2.collector import save_immutable
from .engine import digest, VENUES

JST = ZoneInfo("Asia/Tokyo")


def read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def evaluate(forecast, receipt, result):
    """Only settled refund-free races count toward ordinary return and hit rate."""
    if forecast.get("digest") != digest({k:v for k,v in forecast.items() if k != "digest"}):
        raise ValueError("Frozen forecast digest mismatch")
    if receipt.get("digest") != forecast["digest"] or receipt.get("race_id") != forecast["race_id"]:
        raise ValueError("Receipt does not bind to forecast")
    if receipt.get("status") != "confirmed_before_deadline":
        raise ValueError("Only confirmed before-deadline Git originals may be evaluated")
    saved = datetime.fromisoformat(receipt["checked_at"])
    deadline = datetime.fromisoformat(forecast["deadline_at"])
    if saved >= deadline:
        raise ValueError("Receipt signed after race deadline")
    status = result.get("status")
    payouts = result.get("payouts") or {}
    exclude = bool(result.get("refund_lanes")) or status != "settled"
    if not payouts and not exclude:
        raise ValueError("Invalid official settled result without trifecta")
    picks = [x["combination"] for x in forecast.get("virtual_card") or []]
    if len(picks) != len(set(picks)):
        raise ValueError("Duplicated virtual bets")
    if len(picks) != 10:
        exclude = True
    hits = [key for key in payouts if key in picks]
    payout = sum(int(value) for key,value in payouts.items() if key in picks) if not exclude else None
    winning = sorted(payouts)
    # Explicitly separate selection errors from actual tactical causes.
    first = winning[0].split("-") if len(winning) == 1 else None
    heads = {p.split("-")[0] for p in picks}
    first_pairs = {"-".join(p.split("-")[:2]) for p in picks}
    if exclude or first is None:
        selection = "not_graded"
    elif winning[0] in picks:
        selection = "hit"
    elif first[0] not in heads:
        selection = "head_not_selected"
    elif "-".join(first[:2]) not in first_pairs:
        selection = "second_not_selected_given_head"
    else:
        selection = "third_not_selected_given_head_and_second"
    out = {
        "race_id": forecast["race_id"], "jcd": forecast["jcd"],
        "venue": forecast["venue"], "model": forecast["model"],
        "forecast_digest": forecast["digest"],
        "confirmed_commit_sha": receipt["commit_sha"],
        "source": "BOAT RACE official raceresult",
        "official_observed_at": result.get("observed_at"),
        "official_source_url": result.get("source_url"),
        "status": "excluded" if exclude else "graded",
        "exclusion_reason": (status if status != "settled" else "refund_or_incomplete_card") if exclude else None,
        "official_trifectas": payouts, "refund_lanes": result.get("refund_lanes", []),
        "winning_combinations": winning,
        "virtual_card": picks, "selection": selection,
        "stake_yen": len(picks) * 100 if not exclude else None,
        "return_yen": payout,
        "profit_yen": (payout - len(picks)*100) if not exclude else None,
        "hit": bool(hits) if not exclude else None,
        "scenario_mechanism_verified": False,
        "limitations": ["Official finishing order does not establish each boat's tactics or failure causes",
                        "Actual 1M track/video not reviewed"],
    }
    out["digest"] = digest(out)
    return out


def summarize(root, day):
    counts = {}
    for path in sorted((Path(root) / "reviews").glob("20*/*.json")):
        result = read(path)
        if not result or result.get("status") != "graded":
            continue
        code = result["jcd"]
        row = counts.setdefault(code, {"venue": VENUES[code]["venue"], "graded": 0,
                                       "hits": 0, "stake_yen": 0, "return_yen": 0,
                                       "selection_errors": {}})
        row["graded"] += 1
        row["hits"] += int(bool(result["hit"]))
        row["stake_yen"] += result["stake_yen"]
        row["return_yen"] += result["return_yen"]
        k = result["selection"]
        row["selection_errors"][k] = row["selection_errors"].get(k, 0)+1
    for row in counts.values():
        row["hit_rate_pct"] = round(100*row["hits"]/row["graded"], 2) if row["graded"] else None
        row["roi_pct"] = round(100*row["return_yen"]/row["stake_yen"], 2) if row["stake_yen"] else None
        row["profit_yen"] = row["return_yen"] - row["stake_yen"]
    report = {"version": "venue-specialists-official-postmortem-v1", "through_day": day,
              "research_only": True, "prospective_only": True,
              "venues": counts, "actual_scenario_causes_verified": 0}
    report["digest"] = digest(report)
    return report


def run(root, *, now=None, official=None, max_fetch=24):
    now = now or datetime.now(JST)
    if official is None:
        import direct_discord_notify as official
    from daily_report import parse_payout
    root = Path(root)
    checked, saved, errors = 0, 0, []
    pending = sorted((root / "forecasts").glob("20*/*.json"))
    for path in pending:
        if checked >= max_fetch:
            break
        forecast = read(path)
        if not forecast:
            continue
        key = forecast["race_id"]
        # Only result-day files, never the immutable pre-race snapshot.
        out_path = root / "reviews" / key[:8] / (key + ".json")
        if out_path.exists():
            continue
        receipt = read(root / "receipts" / key[:8] / (key+".json"))
        if not receipt or receipt.get("status") != "confirmed_before_deadline":
            continue
        deadline = datetime.fromisoformat(forecast["deadline_at"])
        if now < deadline + timedelta(minutes=5):
            continue
        checked += 1
        try:
            url = official.official_url("raceresult",key[:8], forecast["jcd"], int(key[-2:]))
            result = parse_payout(official.fetch(url))
            result["observed_at"] = now.isoformat()
            result["source_url"] = url
            if result.get("status") == "pending":
                continue
            review = evaluate(forecast, receipt, result)
            save_immutable(out_path, review)
            saved += 1
        except Exception as exc:
            errors.append({"race_id": key, "error_type": type(exc).__name__,
                           "message": str(exc)[:180]})
    summary = summarize(root, now.strftime("%Y%m%d"))
    out = root / "summary" / "latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Derived summary may be recomputed; immutable pre-race source files never are.
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"checked_results": checked, "new_reviews": saved, "errors": errors,
            "by_venue": summary["venues"]}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True)
    args=p.parse_args()
    print(json.dumps(run(args.out), ensure_ascii=False))


if __name__ == "__main__":
    main()
