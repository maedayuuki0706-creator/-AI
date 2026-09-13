"""Virtual betting helpers for BOAT RACE predictions.

All stake sizes are expressed as units (1 unit = 100 yen in the UI). The helper
never recommends a virtual allocation whose currently quoted payout would be
below the total number of units staked across the selected combinations.
"""
from __future__ import annotations

from itertools import combinations
from math import ceil


def _integer_dutch(rows, *, min_margin=1.02, max_total_units=30):
    """Return integer dutching allocation or None when no-gami is infeasible."""
    if not rows:
        return None
    # A reciprocal-odds sum >= 1 cannot be dutched to a positive guaranteed
    # margin before integer rounding.
    if sum(1.0 / float(row["odds"]) for row in rows) >= 1.0 / min_margin:
        return None
    for target_return in range(max(6, len(rows)), 121):
        stakes = [max(1, ceil(target_return / float(row["odds"]))) for row in rows]
        total = sum(stakes)
        if total > max_total_units:
            continue
        returns = [stake * float(row["odds"]) for stake, row in zip(stakes, rows)]
        if min(returns) + 1e-9 >= total * min_margin:
            return {
                "bets": [
                    {
                        "combination": row["combination"],
                        "odds": float(row["odds"]),
                        "probability": float(row.get("probability") or 0.0),
                        "expected_value": row.get("expected_value"),
                        "units": stake,
                        "return_units": stake * float(row["odds"]),
                    }
                    for stake, row in zip(stakes, rows)
                ],
                "total_units": total,
                "min_return_units": min(returns),
                "min_roi": min(returns) / total,
            }
    return None


def allocate_virtual_bets(rows, *, max_bets=5, min_ev=1.00, min_probability=0.008):
    """Choose a compact positive-EV subset and dutch it to avoid gami.

    `rows` should be model trifecta rows containing combination, probability,
    odds and expected_value. Missing odds are never guessed.
    """
    eligible = [
        row for row in rows
        if row.get("odds") is not None
        and row.get("expected_value") is not None
        and float(row["expected_value"]) >= min_ev
        and float(row.get("probability") or 0.0) >= min_probability
    ]
    if not eligible:
        return {"status": "pass", "reason": "期待値条件を満たす公開オッズなし", "bets": [], "total_units": 0}

    # Keep the search small but allow a value pick slightly below the model's
    # first few probability-ranked combinations.
    pool = sorted(
        eligible,
        key=lambda row: (
            float(row.get("probability") or 0.0) * min(float(row.get("expected_value") or 0.0), 3.0),
            float(row.get("expected_value") or 0.0),
        ),
        reverse=True,
    )[:8]

    best = None
    max_size = min(max_bets, len(pool))
    for size in range(1, max_size + 1):
        for subset in combinations(pool, size):
            allocation = _integer_dutch(list(subset))
            if not allocation:
                continue
            hit_mass = sum(float(row.get("probability") or 0.0) for row in subset)
            avg_ev = sum(float(row.get("expected_value") or 0.0) for row in subset) / size
            # Accuracy first, then value, then fewer units.
            score = (hit_mass, avg_ev, -allocation["total_units"])
            if best is None or score > best[0]:
                best = (score, allocation)

    if best is None:
        return {"status": "pass", "reason": "ガミ回避できる配分なし", "bets": [], "total_units": 0}
    result = best[1]
    result["status"] = "bet"
    return result


def compact_virtual_text(allocation):
    """Compact one-line Discord representation."""
    if allocation.get("status") != "bet":
        return f"仮想投票：見送り 0口（{allocation.get('reason', '条件未達')}）"
    items = [f"{b['combination']}@{b['odds']:.1f}×{b['units']}口" for b in allocation["bets"]]
    profit = allocation["min_return_units"] - allocation["total_units"]
    return (
        "仮想投票：" + " / ".join(items)
        + f"｜計{allocation['total_units']}口 → 最低払戻{allocation['min_return_units']:.1f}口相当"
        + f"（最低+{profit:.1f}口）"
    )
