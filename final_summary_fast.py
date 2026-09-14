from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
from pathlib import Path

import daily_report as dr
import direct_discord_notify as base
import stake_simulation_3000 as sim

DAY = "20260914"
OUT = Path(f"data/final_summary_{DAY}.json")
RESULT_PATH = Path(f"data/official_results/{DAY}.json")


def fetch_result(key, row):
    url = base.official_url("raceresult", DAY, str(row["jcd"]).zfill(2), int(row["rno"]))
    try:
        parsed = dr.parse_payout(base.fetch(url))
        return key, {**parsed, "source_url": url, "checked_at": datetime.now(base.JST).isoformat()}, None
    except Exception as exc:
        return key, None, f"{type(exc).__name__}: {exc}"


def uniform_settle(row, result):
    picks = dr.disclosed_picks(row)
    return dr.settle({
        **row,
        "main": picks,
        "cover": [],
        "outsiders": [],
        "virtual_bets": [{"combination": p, "units": 1} for p in picks],
        "virtual_total_units": len(picks),
        "virtual_unit_yen": 100,
    }, result)


def hit_bucket(row, result):
    winners = set((result.get("payouts") or {}).keys())
    picks = set(dr.disclosed_picks(row))
    matched = winners & picks
    if not matched:
        return None
    if any((result["payouts"].get(c) or 0) >= 10000 for c in matched):
        return "man"
    if set(row.get("main") or []) & winners:
        return "main"
    return "mid"


def main():
    base.fetch.cache_clear()
    predictions = dr.read_jsonl(base.LOG_PATH)
    chosen, excluded = dr.latest_predictions(predictions, DAY)

    results = {}
    errors = {}
    with ThreadPoolExecutor(max_workers=24) as pool:
        futures = {pool.submit(fetch_result, key, row): key for key, row in chosen.items()}
        for future in as_completed(futures):
            key, result, error = future.result()
            if result:
                results[key] = result
            if error:
                errors[key] = error

    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    settled = []
    venues = defaultdict(lambda: {"races": 0, "hits": 0, "main": 0, "mid": 0, "man": 0})
    for key, row in chosen.items():
        result = results.get(key) or {"status": "pending", "payouts": {}, "refund_lanes": []}
        if result.get("status") != "settled":
            continue
        actual = dr.settle(row, result)
        uniform = uniform_settle(row, result)
        bucket = hit_bucket(row, result)
        payout = max((result.get("payouts") or {}).values(), default=0)
        hit = bool(actual["prediction_hit"])
        settled.append((row, result, actual, uniform, bucket, payout, hit))
        v = venues[row.get("venue") or str(row.get("jcd"))]
        v["races"] += 1
        v["hits"] += int(hit)
        if bucket:
            v[bucket] += 1

    hits = sum(x[6] for x in settled)
    main_hits = sum(x[4] == "main" for x in settled)
    mid_hits = sum(x[4] == "mid" for x in settled)
    man_hits = sum(x[4] == "man" for x in settled)
    final_rows = [x for x in settled if x[0].get("phase") == "final"]
    prelim_rows = [x for x in settled if x[0].get("phase") != "final"]
    final_hits = sum(x[6] for x in final_rows)
    prelim_hits = sum(x[6] for x in prelim_rows)
    uniform_stake = sum(x[3]["stake_yen"] for x in settled)
    uniform_return = sum(x[3]["return_yen"] for x in settled)
    virtual_rows = [x for x in settled if x[2]["stake_yen"] > 0]
    virtual_stake = sum(x[2]["stake_yen"] for x in virtual_rows)
    virtual_return = sum(x[2]["return_yen"] for x in virtual_rows)
    missed_man = [x for x in settled if x[5] >= 10000 and not x[6]]

    # Recalculate the requested 3,000-yen-per-race allocation on this final result snapshot.
    sim.main()
    sim_data = json.loads(Path(f"data/stake_simulations/{DAY}_3000.json").read_text(encoding="utf-8"))

    out = {
        "day": DAY,
        "as_of": datetime.now(base.JST).isoformat(),
        "predicted_races": len(chosen),
        "settled_races": len(settled),
        "pending_races": len(chosen) - len(settled),
        "hits": hits,
        "hit_rate": hits / len(settled) * 100 if settled else None,
        "main_hits": main_hits,
        "mid_hits": mid_hits,
        "man_hits": man_hits,
        "final_hits": final_hits,
        "final_samples": len(final_rows),
        "prelim_hits": prelim_hits,
        "prelim_samples": len(prelim_rows),
        "uniform_stake_yen": uniform_stake,
        "uniform_return_yen": uniform_return,
        "uniform_profit_yen": uniform_return - uniform_stake,
        "uniform_roi": uniform_return / uniform_stake * 100 if uniform_stake else None,
        "virtual_stake_yen": virtual_stake,
        "virtual_return_yen": virtual_return,
        "virtual_profit_yen": virtual_return - virtual_stake,
        "virtual_roi": virtual_return / virtual_stake * 100 if virtual_stake else None,
        "missed_man": len(missed_man),
        "venues": dict(sorted(venues.items())),
        "result_fetch_errors": errors,
        "excluded_deliveries": len(excluded),
        "stake_3000": {
            "races": sim_data.get("confirmed_races"),
            "hits": sim_data.get("hits"),
            "hit_rate": sim_data.get("hit_rate"),
            "stake_yen": sim_data.get("total_stake_yen"),
            "return_yen": sim_data.get("total_return_yen"),
            "profit_yen": sim_data.get("profit_yen"),
            "roi": sim_data.get("roi"),
            "note": sim_data.get("important_note"),
        },
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
