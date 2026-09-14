from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
from pathlib import Path

import daily_report as dr
import direct_discord_notify as base

BUDGET_YEN = 3000
UNIT_YEN = 100
TOTAL_UNITS = BUDGET_YEN // UNIT_YEN


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
        return units, "legacy_final_official_odds_dutch"

    for i in range(remaining):
        units[picks[i % len(picks)]] += 1
    return units, "legacy_equal_fallback_missing_odds"


def recorded_plan(row: dict, picks: list[str]) -> dict[str, int] | None:
    raw = row.get("stake_3000_units")
    if not isinstance(raw, dict):
        return None
    if set(raw) != set(picks):
        return None
    units = {}
    for combo in picks:
        value = raw.get(combo)
        if type(value) is not int or value <= 0:
            return None
        units[combo] = value
    if sum(units.values()) != TOTAL_UNITS:
        return None
    return units


def fetch_odds(day: str, key: str) -> tuple[str, dict[str, float] | None, str | None]:
    jcd, rno = key.split(":")
    try:
        raw = base.fetch(base.official_url("odds3t", day, jcd, int(rno)))
        odds = base.parse_odds(raw)
        return key, odds, None if odds else "empty_odds"
    except Exception as exc:
        return key, None, f"{type(exc).__name__}: {exc}"


def build_simulation(day: str) -> dict:
    result_path = Path(f"data/official_results/{day}.json")
    output_path = Path(f"data/stake_simulations/{day}_3000.json")
    if not result_path.exists():
        raise FileNotFoundError(result_path)

    predictions = dr.read_jsonl(base.LOG_PATH)
    chosen, _ = dr.latest_predictions(predictions, day)
    results = json.loads(result_path.read_text(encoding="utf-8"))
    settled_keys = [key for key, result in results.items() if result.get("status") == "settled" and key in chosen]

    legacy_hit_keys = []
    for key in settled_keys:
        row = chosen[key]
        picks = dr.disclosed_picks(row)
        if recorded_plan(row, picks) is not None:
            continue
        winners = set((results[key].get("payouts") or {}).keys())
        if winners & set(picks):
            legacy_hit_keys.append(key)

    odds_by_key: dict[str, dict[str, float]] = {}
    odds_errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(fetch_odds, day, key): key for key in legacy_hit_keys}
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
    recorded_plan_races = 0
    complete_send_odds_races = 0
    torigami_hits = profitable_hits = break_even_hits = 0

    for key in sorted(settled_keys):
        row = chosen[key]
        result = results[key]
        picks = dr.disclosed_picks(row)
        winners = set((result.get("payouts") or {}).keys())
        prediction_hit = bool(winners & set(picks))

        units = recorded_plan(row, picks)
        recorded = units is not None
        if recorded:
            recorded_plan_races += 1
            mode = str(row.get("stake_3000_allocation_mode") or "recorded_send_time_plan")
            if row.get("send_odds_complete"):
                complete_send_odds_races += 1
        elif prediction_hit:
            odds = odds_by_key.get(key, {})
            units, mode = allocate_dutch(picks, odds)
            missing_pick_odds += sum(1 for p in picks if p not in odds)
        else:
            units = {p: 1 for p in picks}
            for i in range(TOTAL_UNITS - len(picks)):
                units[picks[i % len(picks)]] += 1
            mode = "legacy_equal_miss_no_send_plan"

        mode_counts[mode] += 1
        stake = sum(units.values()) * UNIT_YEN
        returned = sum(units.get(combo, 0) * payout for combo, payout in (result.get("payouts") or {}).items())
        winning = [combo for combo in (result.get("payouts") or {}) if units.get(combo, 0) > 0]

        if winning:
            if returned > stake:
                profitable_hits += 1
            elif returned == stake:
                break_even_hits += 1
            else:
                torigami_hits += 1

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
            "send_odds": row.get("send_odds") or {},
            "send_odds_complete": bool(row.get("send_odds_complete")),
            "allocation_recorded_at_prediction": recorded,
            "allocation_units": units,
            "allocation_yen": {combo: count * UNIT_YEN for combo, count in units.items()},
            "allocation_mode": mode,
            "min_projected_return_yen_at_send": row.get("stake_3000_min_projected_return_yen"),
            "torigami_risk_at_send": row.get("stake_3000_torigami_risk_at_send"),
            "winning_combos": winning,
            "official_payouts_per_100": result.get("payouts") or {},
            "stake_yen": stake,
            "return_yen": returned,
            "profit_yen": returned - stake,
            "torigami": bool(winning) and 0 < returned < stake,
        })

    legacy_races = len(rows) - recorded_plan_races
    if rows and recorded_plan_races == len(rows):
        note = (
            "Every settled race used the 3,000-yen allocation recorded with the prediction. "
            "Official payouts settle those recorded stakes; no post-race odds were used to choose stake sizes."
        )
    else:
        note = (
            f"Send-time 3,000-yen plans were recorded for {recorded_plan_races}/{len(rows)} settled races. "
            f"The remaining {legacy_races} legacy races use the old fallback because their send-time plan was not stored."
        )

    out = {
        "day": day,
        "generated_at": datetime.now(base.JST).isoformat(),
        "budget_per_race_yen": BUDGET_YEN,
        "unit_yen": UNIT_YEN,
        "allocation_rule": "all disclosed picks receive at least 100 yen; remaining 100-yen units equalize projected gross return using the odds snapshot stored with the prediction",
        "important_note": note,
        "confirmed_races": len(rows),
        "recorded_send_time_plan_races": recorded_plan_races,
        "complete_send_odds_races": complete_send_odds_races,
        "legacy_fallback_races": legacy_races,
        "hits": hits,
        "hit_rate": hits / len(rows) * 100 if rows else None,
        "profitable_hits": profitable_hits,
        "break_even_hits": break_even_hits,
        "torigami_hits": torigami_hits,
        "total_stake_yen": total_stake,
        "total_return_yen": total_return,
        "profit_yen": total_return - total_stake,
        "roi": total_return / total_stake * 100 if total_stake else None,
        "allocation_mode_counts": dict(mode_counts),
        "odds_fetch_errors": odds_errors,
        "missing_pick_odds": missing_pick_odds,
        "races": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", default=datetime.now(base.JST).strftime("%Y%m%d"))
    args = parser.parse_args()
    datetime.strptime(args.day, "%Y%m%d")
    out = build_simulation(args.day)
    keys = (
        "confirmed_races", "recorded_send_time_plan_races", "complete_send_odds_races",
        "hits", "hit_rate", "profitable_hits", "torigami_hits", "total_stake_yen",
        "total_return_yen", "profit_yen", "roi", "allocation_mode_counts",
    )
    print(json.dumps({k: out[k] for k in keys}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
