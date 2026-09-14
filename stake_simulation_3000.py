from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
from pathlib import Path

import daily_report as dr
import direct_discord_notify as base

DAY = "20260914"
BUDGET_YEN = 3000
UNIT_YEN = 100
TOTAL_UNITS = BUDGET_YEN // UNIT_YEN
RESULT_PATH = Path(f"data/official_results/{DAY}.json")
OUTPUT_PATH = Path(f"data/stake_simulations/{DAY}_3000.json")


def allocate_dutch(picks: list[str], odds: dict[str, float]) -> tuple[dict[str, int], str]:
    """Keep every disclosed pick alive with >=100 yen, then equalize gross returns greedily."""
    picks = list(dict.fromkeys(picks))
    if not picks:
        return {}, "none"
    if len(picks) > TOTAL_UNITS:
        raise ValueError(f"Too many picks for {BUDGET_YEN} yen budget: {len(picks)}")

    complete = all(p in odds and odds[p] > 0 for p in picks)
    units = {p: 1 for p in picks}
    remaining = TOTAL_UNITS - len(picks)

    if complete:
        for _ in range(remaining):
            target = min(picks, key=lambda p: (units[p] * odds[p], odds[p], p))
            units[target] += 1
        return units, "final_official_odds_dutch"

    ordered = sorted(picks)
    for i in range(remaining):
        units[ordered[i % len(ordered)]] += 1
    return units, "equal_fallback_missing_odds"


def fetch_odds(key: str) -> tuple[str, dict[str, float] | None, str | None]:
    jcd, rno = key.split(":")
    try:
        raw = base.fetch(base.official_url("odds3t", DAY, jcd, int(rno)))
        odds = base.parse_odds(raw)
        return key, odds, None if odds else "empty_odds"
    except Exception as exc:
        return key, None, f"{type(exc).__name__}: {exc}"


def main() -> None:
    predictions = dr.read_jsonl(base.LOG_PATH)
    chosen, _ = dr.latest_predictions(predictions, DAY)
    results = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    settled_keys = [key for key, result in results.items() if result.get("status") == "settled" and key in chosen]

    # Allocation only affects the return on races whose winning ticket was disclosed.
    # Losing races are always -3000 yen, so skip their odds HTTP request entirely.
    hit_keys = []
    for key in settled_keys:
        winners = set((results[key].get("payouts") or {}).keys())
        if winners & set(dr.disclosed_picks(chosen[key])):
            hit_keys.append(key)

    odds_by_key: dict[str, dict[str, float]] = {}
    odds_errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(fetch_odds, key): key for key in hit_keys}
        for future in as_completed(futures):
            key, odds, error = future.result()
            if odds:
                odds_by_key[key] = odds
            if error:
                odds_errors[key] = error

    rows = []
    total_stake = total_return = hits = 0
    mode_counts = defaultdict(int)
    missing_pick_odds = 0

    for key in sorted(settled_keys):
        row = chosen[key]
        result = results[key]
        picks = dr.disclosed_picks(row)
        winners = set((result.get("payouts") or {}).keys())
        prediction_hit = bool(winners & set(picks))

        if prediction_hit:
            odds = odds_by_key.get(key, {})
            units, mode = allocate_dutch(picks, odds)
            missing_pick_odds += sum(1 for p in picks if p not in odds)
        else:
            # Allocation cannot change a losing race's return; use any valid 30-unit spread.
            units = {p: 1 for p in picks}
            ordered = sorted(picks)
            for i in range(TOTAL_UNITS - len(picks)):
                units[ordered[i % len(ordered)]] += 1
            mode = "not_needed_miss"

        mode_counts[mode] += 1
        stake = sum(units.values()) * UNIT_YEN
        returned = sum(units.get(combo, 0) * payout for combo, payout in (result.get("payouts") or {}).items())
        winning = [combo for combo in (result.get("payouts") or {}) if units.get(combo, 0) > 0]

        total_stake += stake
        total_return += returned
        hits += int(bool(winning))
        rows.append({
            "key": key,
            "venue": row.get("venue"),
            "rno": row.get("rno"),
            "phase": row.get("phase"),
            "picks": picks,
            "point_count": len(picks),
            "allocation_units": units,
            "allocation_mode": mode,
            "winning_combos": winning,
            "official_payouts_per_100": result.get("payouts") or {},
            "stake_yen": stake,
            "return_yen": returned,
            "profit_yen": returned - stake,
        })

    out = {
        "day": DAY,
        "generated_at": datetime.now(base.JST).isoformat(),
        "budget_per_race_yen": BUDGET_YEN,
        "unit_yen": UNIT_YEN,
        "allocation_rule": "all disclosed picks receive at least 100 yen; remaining units greedily equalize gross returns using final official trifecta odds",
        "important_note": "Full send-time odds were not stored for every disclosed pick, so this backtest uses final official odds for allocation on hit races. It is an approximation of pre-race dutching, not an exact historical execution simulation.",
        "confirmed_races": len(rows),
        "hits": hits,
        "hit_rate": hits / len(rows) * 100 if rows else None,
        "total_stake_yen": total_stake,
        "total_return_yen": total_return,
        "profit_yen": total_return - total_stake,
        "roi": total_return / total_stake * 100 if total_stake else None,
        "allocation_mode_counts": dict(mode_counts),
        "odds_fetch_errors": odds_errors,
        "missing_pick_odds": missing_pick_odds,
        "races": rows,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("confirmed_races", "hits", "hit_rate", "total_stake_yen", "total_return_yen", "profit_yen", "roi", "allocation_mode_counts", "missing_pick_odds")}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
