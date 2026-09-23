from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path

UNIT_YEN = 100
MIN_PROFIT_YEN = 100
MIN_PROFIT_UNITS = MIN_PROFIT_YEN // UNIT_YEN
PRED_ROOT = Path("data/prototype3_delivery/predictions")
RESULT_ROOT = Path("data/prototype_scoreboard")
OUT_ROOT = Path("data/pt3_stake_simulations")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def send_snapshot(model: dict):
    rows = {r["combination"]: r for r in model.get("trifecta") or [] if r.get("combination")}
    picks = [p for p in model.get("picks") or [] if p in rows and float(rows[p].get("odds") or 0) > 0]
    odds = {p: float(rows[p]["odds"]) for p in picks}
    return picks, odds


def minimum_profit_dutch(picks, odds):
    """Minimum 100-yen-unit stake plan where every covered hit projects >= +100 yen.

    For total stake T units, each pick needs ceil((T+1)/odds) units.
    A solution exists asymptotically only when sum(1/odds) < 1.
    """
    picks = list(dict.fromkeys(picks))
    if not picks:
        return None
    inverse_sum = sum(1.0 / odds[p] for p in picks)
    if inverse_sum >= 1.0 - 1e-12:
        return None

    # Fixed-point search. If required units exceed the current total, jump to
    # that requirement. With inverse_sum < 1 this converges to a feasible T.
    total_units = len(picks)
    for _ in range(10000):
        required = {
            p: max(1, math.ceil((total_units + MIN_PROFIT_UNITS) / odds[p] - 1e-12))
            for p in picks
        }
        need = sum(required.values())
        if need <= total_units:
            units = required
            extra = total_units - need
            # Extras do not change total stake (already fixed at total_units),
            # so place them on the currently weakest projected-return ticket.
            for _ in range(extra):
                target = min(picks, key=lambda p: (units[p] * odds[p], odds[p], p))
                units[target] += 1
            return {
                "units": units,
                "total_units": total_units,
                "inverse_odds_sum": inverse_sum,
                "projected_min_return_yen": min(
                    round(units[p] * odds[p] * UNIT_YEN) for p in picks
                ),
                "projected_min_profit_yen": min(
                    round(units[p] * odds[p] * UNIT_YEN) for p in picks
                ) - total_units * UNIT_YEN,
            }
        total_units = need
    raise RuntimeError("profit dutch did not converge")


def settle(plan, official):
    units = plan["units"]
    stake = plan["total_units"] * UNIT_YEN
    payouts = official.get("payouts") or {}
    returned = 0
    winning = []
    for combo, payout in payouts.items():
        if combo in units:
            returned += units[combo] * int(payout)
            winning.append(combo)
    return {
        "stake_yen": stake,
        "return_yen": returned,
        "profit_yen": returned - stake,
        "hit": bool(winning),
        "winning_combos": winning,
        "torigami": bool(winning) and returned < stake,
        "profitable_hit": bool(winning) and returned > stake,
        "break_even_hit": bool(winning) and returned == stake,
    }


def build(day: str):
    result_dir = RESULT_ROOT / day / "results"
    races = []
    stats = {
        "settled_pt3_races": 0,
        "feasible_races": 0,
        "infeasible_races": 0,
        "hits": 0,
        "profitable_hits": 0,
        "break_even_hits": 0,
        "torigami_hits": 0,
        "total_stake_yen": 0,
        "total_return_yen": 0,
        "min_stake_yen": None,
        "max_stake_yen": 0,
        "sum_stake_yen": 0,
    }

    for pred_path in sorted(PRED_ROOT.glob(f"{day}_*.json")):
        pred = read_json(pred_path)
        key = pred.get("key")
        if not key:
            continue
        result_path = result_dir / f"{key}.json"
        if not result_path.exists():
            continue
        result = read_json(result_path)
        if "prototype3" not in (result.get("models") or {}):
            continue
        official = result.get("official") or {}
        if official.get("status") != "settled":
            continue

        stats["settled_pt3_races"] += 1
        model = pred.get("model") or {}
        picks, odds = send_snapshot(model)
        if not picks:
            continue

        plan = minimum_profit_dutch(picks, odds)
        race = {
            "key": key,
            "venue": pred.get("venue"),
            "rno": pred.get("rno"),
            "point_count": len(picks),
            "inverse_odds_sum": sum(1.0 / odds[p] for p in picks),
            "feasible_all_picks": plan is not None,
            "official_payouts_per_100": official.get("payouts") or {},
        }
        if plan is None:
            stats["infeasible_races"] += 1
            races.append(race)
            continue

        stats["feasible_races"] += 1
        actual = settle(plan, official)
        stake = actual["stake_yen"]
        stats["hits"] += int(actual["hit"])
        stats["profitable_hits"] += int(actual["profitable_hit"])
        stats["break_even_hits"] += int(actual["break_even_hit"])
        stats["torigami_hits"] += int(actual["torigami"])
        stats["total_stake_yen"] += stake
        stats["total_return_yen"] += actual["return_yen"]
        stats["sum_stake_yen"] += stake
        stats["min_stake_yen"] = stake if stats["min_stake_yen"] is None else min(stats["min_stake_yen"], stake)
        stats["max_stake_yen"] = max(stats["max_stake_yen"], stake)

        race["plan"] = {
            "allocation_yen": {p: u * UNIT_YEN for p, u in plan["units"].items()},
            "stake_yen": stake,
            "projected_min_return_yen": plan["projected_min_return_yen"],
            "projected_min_profit_yen": plan["projected_min_profit_yen"],
        }
        race["actual"] = actual
        races.append(race)

    feasible = stats["feasible_races"]
    stake = stats["total_stake_yen"]
    stats["hit_rate_on_feasible"] = 100 * stats["hits"] / feasible if feasible else None
    stats["profitable_hit_rate_on_hits"] = 100 * stats["profitable_hits"] / stats["hits"] if stats["hits"] else None
    stats["average_stake_yen"] = stats["sum_stake_yen"] / feasible if feasible else None
    stats["profit_yen"] = stats["total_return_yen"] - stake
    stats["roi"] = 100 * stats["total_return_yen"] / stake if stake else None
    stats.pop("sum_stake_yen", None)

    out = {
        "day": day,
        "generated_at": datetime.now().astimezone().isoformat(),
        "unit_yen": UNIT_YEN,
        "minimum_projected_profit_per_hit_yen": MIN_PROFIT_YEN,
        "principle": "Use only send-time PT3 odds to compute the minimum variable stake allocation where every selected PT3 combination projects at least +100 yen if it wins. Official payouts are used only for settlement.",
        "important_note": "Because boat-race odds move until close, a send-time no-torigami plan can still become break-even or torigami at final official payout.",
        "totals": stats,
        "races": races,
    }
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    path = OUT_ROOT / f"{day}_profit_variable.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", required=True)
    args = parser.parse_args()
    datetime.strptime(args.day, "%Y%m%d")
    build(args.day)


if __name__ == "__main__":
    main()
