from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path

BUDGET_YEN = 2000
UNIT_YEN = 100
TOTAL_UNITS = BUDGET_YEN // UNIT_YEN

PRED_ROOT = Path("data/prototype3_delivery/predictions")
RESULT_ROOT = Path("data/prototype_scoreboard")
OUT_ROOT = Path("data/pt3_stake_simulations")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def send_snapshot(model: dict):
    rows = {r["combination"]: r for r in model.get("trifecta") or [] if r.get("combination")}
    picks = [p for p in model.get("picks") or [] if p in rows and float(rows[p].get("odds") or 0) > 0]
    odds = {p: float(rows[p]["odds"]) for p in picks}
    probs = {p: float(rows[p].get("probability") or 0) for p in picks}
    return picks, odds, probs


def fixed_2000_dutch(picks, odds):
    if not picks or len(picks) > TOTAL_UNITS:
        return {}
    units = {p: 1 for p in picks}
    for _ in range(TOTAL_UNITS - len(picks)):
        p = min(picks, key=lambda x: (units[x] * odds[x], odds[x], x))
        units[p] += 1
    return units


def no_torigami_2000(picks, odds, probs):
    # Spend exactly 2,000 yen. Only keep combinations whose send-time projected
    # gross return can be >= 2,000 yen. Pick the subset maximizing model
    # probability mass under the required-unit cost, then use leftover units
    # to strengthen the weakest projected return.
    if not picks:
        return {}

    cost = {p: max(1, math.ceil(TOTAL_UNITS / odds[p] - 1e-12)) for p in picks}
    usable = [p for p in picks if cost[p] <= TOTAL_UNITS]

    # 0/1 knapsack over 20 units, maximizing probability mass. Tie-break toward
    # more covered picks, then lower required units.
    dp = [(0.0, 0, (), 0) for _ in range(TOTAL_UNITS + 1)]
    for p in usable:
        c = cost[p]
        prob = probs.get(p, 0.0)
        for u in range(TOTAL_UNITS, c - 1, -1):
            prev = dp[u - c]
            cand = (prev[0] + prob, prev[1] + 1, prev[2] + (p,), prev[3] + c)
            cur = dp[u]
            if (cand[0], cand[1], -cand[3]) > (cur[0], cur[1], -cur[3]):
                dp[u] = cand

    best = max(dp, key=lambda z: (z[0], z[1], -z[3]))
    selected = list(best[2])
    if not selected:
        return {}

    units = {p: cost[p] for p in selected}
    remaining = TOTAL_UNITS - sum(units.values())
    for _ in range(remaining):
        p = min(selected, key=lambda x: (units[x] * odds[x], odds[x], x))
        units[p] += 1
    return units


def settle(units, official):
    stake = sum(units.values()) * UNIT_YEN
    payouts = official.get("payouts") or {}
    returned = sum(units.get(combo, 0) * int(payout) for combo, payout in payouts.items())
    winning = [combo for combo in payouts if units.get(combo, 0) > 0]
    return {
        "stake_yen": stake,
        "return_yen": returned,
        "profit_yen": returned - stake,
        "hit": bool(winning),
        "winning_combos": winning,
        "torigami": bool(winning) and returned < stake,
    }


def projected_floor(units, odds):
    if not units:
        return 0
    return min(round(units[p] * odds[p] * UNIT_YEN) for p in units)


def build(day: str):
    result_dir = RESULT_ROOT / day / "results"
    rows = []
    totals = {
        "fixed_2000": {"stake": 0, "return": 0, "hits": 0, "torigami": 0, "races": 0},
        "no_torigami_2000": {"stake": 0, "return": 0, "hits": 0, "torigami": 0, "races": 0},
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

        model = pred.get("model") or {}
        picks, odds, probs = send_snapshot(model)
        if not picks:
            continue

        plans = {
            "fixed_2000": fixed_2000_dutch(picks, odds),
            "no_torigami_2000": no_torigami_2000(picks, odds, probs),
        }
        race = {
            "key": key,
            "venue": pred.get("venue"),
            "rno": pred.get("rno"),
            "point_count": len(picks),
            "original_picks": picks,
            "official_payouts_per_100": official.get("payouts") or {},
            "plans": {},
        }

        for name, units in plans.items():
            if not units:
                continue
            actual = settle(units, official)
            floor = projected_floor(units, odds)
            covered_mass = sum(probs.get(p, 0) for p in units)
            race["plans"][name] = {
                "covered_picks": list(units),
                "covered_points": len(units),
                "covered_probability_mass": covered_mass,
                "allocation_yen": {p: u * UNIT_YEN for p, u in units.items()},
                "projected_min_return_yen_at_send": floor,
                **actual,
            }
            t = totals[name]
            t["races"] += 1
            t["stake"] += actual["stake_yen"]
            t["return"] += actual["return_yen"]
            t["hits"] += int(actual["hit"])
            t["torigami"] += int(actual["torigami"])
        rows.append(race)

    out_totals = {}
    for name, t in totals.items():
        out_totals[name] = {
            "races": t["races"],
            "hits": t["hits"],
            "hit_rate": 100 * t["hits"] / t["races"] if t["races"] else None,
            "torigami_hits": t["torigami"],
            "total_stake_yen": t["stake"],
            "total_return_yen": t["return"],
            "profit_yen": t["return"] - t["stake"],
            "roi": 100 * t["return"] / t["stake"] if t["stake"] else None,
        }

    out = {
        "day": day,
        "generated_at": datetime.now().astimezone().isoformat(),
        "budget_per_race_yen": BUDGET_YEN,
        "unit_yen": UNIT_YEN,
        "principle": "Only odds/probabilities stored with the pre-race PT3 prediction are used to size stakes. Official payouts are used only for settlement.",
        "strategies": {
            "fixed_2000": "Keep every PT3 pick at >=100 yen and allocate the rest to equalize projected gross return.",
            "no_torigami_2000": "Spend 2,000 yen only on a probability-maximizing subset of PT3 picks whose send-time projected gross return can each reach >=2,000 yen.",
        },
        "totals": out_totals,
        "races": rows,
    }
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    path = OUT_ROOT / f"{day}_2000.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out_totals, ensure_ascii=False, sort_keys=True))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--day", required=True)
    args = p.parse_args()
    datetime.strptime(args.day, "%Y%m%d")
    build(args.day)


if __name__ == "__main__":
    main()
