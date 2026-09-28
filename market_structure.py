"""Market-structure diagnostics for 3-ren-tan odds.

The goal is not "split odds => buy".  We quantify how dispersed the public
market is, then compare that with the model's own first-place distribution.
Only when the market is split *and* the model is materially clearer do we emit
an actionable disagreement signal.
"""
from __future__ import annotations

from math import log
from typing import Any, Iterable, Mapping


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _head(combo: str) -> int | None:
    try:
        lane = int(str(combo).split("-")[0])
    except (TypeError, ValueError):
        return None
    return lane if 1 <= lane <= 6 else None


def analyze_market_structure(
    odds: Mapping[str, Any] | None,
    trifectas: Iterable[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Return public-market dispersion and model-vs-market head disagreement.

    Public head shares use normalized reciprocal odds as a relative popularity
    proxy.  This is deliberately diagnostic: the output never overrides model
    probability or EV by itself.
    """
    rows = list(trifectas or [])
    odds_map: dict[str, float] = {}

    if isinstance(odds, Mapping):
        for combo, raw in odds.items():
            value = _num(raw)
            if value > 0 and _head(str(combo)) is not None:
                odds_map[str(combo)] = value

    # Hiyori/PT paths attach odds to the rows after model analysis, so accept
    # row-level prices as a fallback.
    if not odds_map:
        for row in rows:
            combo = str(row.get("combination") or "")
            value = _num(row.get("odds"))
            if value > 0 and _head(combo) is not None:
                odds_map[combo] = value

    coverage = len(odds_map)
    if coverage < 30:
        return {
            "available": False,
            "odds_coverage": coverage,
            "market_type": "未判定",
            "split_index": None,
            "actionability": "insufficient_odds",
        }

    implied = {combo: 1.0 / value for combo, value in odds_map.items() if value > 0}
    implied_total = sum(implied.values())
    if implied_total <= 0:
        return {
            "available": False,
            "odds_coverage": coverage,
            "market_type": "未判定",
            "split_index": None,
            "actionability": "insufficient_odds",
        }

    market_heads = {lane: 0.0 for lane in range(1, 7)}
    for combo, weight in implied.items():
        lane = _head(combo)
        if lane is not None:
            market_heads[lane] += weight / implied_total

    ranked_market_heads = sorted(market_heads, key=market_heads.get, reverse=True)
    market_top = ranked_market_heads[0]
    market_top_share = market_heads[market_top]

    popular = sorted(odds_map.items(), key=lambda item: item[1])[:10]
    top10_counts = {lane: 0 for lane in range(1, 7)}
    for combo, _ in popular:
        lane = _head(combo)
        if lane is not None:
            top10_counts[lane] += 1
    top10_unique_heads = sum(1 for value in top10_counts.values() if value > 0)

    entropy = 0.0
    for share in market_heads.values():
        if share > 0:
            entropy -= share * log(share)
    entropy_pct = 100.0 * entropy / log(6.0)

    diversity_pct = 100.0 * top10_unique_heads / 6.0
    if len(popular) >= 2 and popular[0][1] > 0:
        spread_ratio = popular[-1][1] / popular[0][1]
    else:
        spread_ratio = 999.0
    # Similar prices through the popular band = a flatter, more divided market.
    flatness_pct = _clip((4.0 - spread_ratio) / 3.0 * 100.0)
    split_index = _clip(
        0.55 * entropy_pct + 0.25 * diversity_pct + 0.20 * flatness_pct
    )

    dominant_top10_count = top10_counts.get(market_top, 0)
    if market_top_share < 0.36 and top10_unique_heads >= 4:
        market_type = "完全混戦型"
    elif market_top_share < 0.55 and top10_unique_heads >= 3:
        market_type = "頭割れ型"
    elif market_top_share >= 0.68 and dominant_top10_count >= 7 and spread_ratio >= 2.5:
        market_type = "集中型"
    elif market_top_share >= 0.55 and dominant_top10_count >= 6:
        market_type = "ヒモ割れ型"
    else:
        market_type = "中間型"

    model_heads = {lane: 0.0 for lane in range(1, 7)}
    for row in rows:
        lane = _head(str(row.get("combination") or ""))
        probability = _num(row.get("probability"))
        if lane is not None and probability > 0:
            model_heads[lane] += probability

    model_total = sum(model_heads.values())
    if model_total > 0:
        model_heads = {lane: value / model_total for lane, value in model_heads.items()}

    ranked_model_heads = sorted(model_heads, key=model_heads.get, reverse=True)
    model_top = ranked_model_heads[0]
    model_top_share = model_heads[model_top]
    market_share_for_model_top = market_heads.get(model_top, 0.0)
    edge_pp = (model_top_share - market_share_for_model_top) * 100.0
    head_edge_pp = {
        str(lane): round((model_heads[lane] - market_heads[lane]) * 100.0, 1)
        for lane in range(1, 7)
    }

    model_conviction = _clip((model_top_share - 0.30) / 0.25 * 100.0)
    positive_edge = _clip((edge_pp - 4.0) / 16.0 * 100.0)

    if split_index >= 55 and model_top_share >= 0.38 and edge_pp >= 4.0:
        actionability = "market_split_model_clear"
        signal_score = _clip(
            0.45 * split_index + 0.35 * model_conviction + 0.20 * positive_edge
        )
    elif split_index >= 55:
        actionability = "split_but_model_unclear"
        signal_score = _clip(0.60 * split_index + 0.40 * model_conviction)
    else:
        actionability = "normal"
        signal_score = _clip(0.50 * split_index + 0.50 * model_conviction)

    return {
        "available": True,
        "odds_coverage": coverage,
        "market_type": market_type,
        "split_index": round(split_index, 1),
        "head_entropy": round(entropy_pct, 1),
        "top10_unique_heads": top10_unique_heads,
        "top10_head_counts": {str(k): v for k, v in top10_counts.items()},
        "top10_odds": [round(value, 1) for _, value in popular],
        "top10_spread_ratio": round(spread_ratio, 2),
        "market_head_probabilities": {
            str(k): round(v, 4) for k, v in market_heads.items()
        },
        "market_top_head": market_top,
        "market_top_head_share": round(market_top_share, 4),
        "model_head_probabilities": {
            str(k): round(v, 4) for k, v in model_heads.items()
        },
        "model_top_head": model_top,
        "model_top_head_share": round(model_top_share, 4),
        "model_market_head_edge_pp": round(edge_pp, 1),
        "head_edge_pp": head_edge_pp,
        "actionability": actionability,
        "signal_score": round(signal_score, 1),
    }
