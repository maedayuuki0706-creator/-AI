"""Conservative cover reallocation based on learned near-miss structure.

The goal is not to widen every race. When historical settled predictions show
that a meaningful share of misses were one slot away (or the same three boats
in the wrong order), use at most two existing cover slots for high-probability
"bridge" combinations. Core six picks and total point count stay unchanged.
"""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Any

STATE_PATH = Path("data/learning_state.json")
MIN_GLOBAL_SAMPLES = 100
MIN_VENUE_SAMPLES = 30
MIN_BRIDGE_MISS_RATE = 0.10
MAX_REPLACEMENTS = 2


@lru_cache(maxsize=1)
def _state() -> dict:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _metrics_for(venue: str | None) -> tuple[bool, dict]:
    state = _state()
    overall = state.get("overall") or {}
    samples = int(state.get("samples") or overall.get("samples") or 0)
    rate = float(overall.get("bridge_rescue_rate_of_misses") or 0.0)
    enabled = (
        state.get("learning_version") == "near-miss-v2"
        and samples >= MIN_GLOBAL_SAMPLES
        and rate >= MIN_BRIDGE_MISS_RATE
    )

    venue_metrics = ((state.get("by_venue") or {}).get(str(venue)) or {}) if venue else {}
    venue_samples = int(venue_metrics.get("samples") or 0)
    venue_rate = float(venue_metrics.get("bridge_rescue_rate_of_misses") or 0.0)
    if enabled and venue_samples >= MIN_VENUE_SAMPLES:
        enabled = venue_rate >= MIN_BRIDGE_MISS_RATE

    same_three = float(venue_metrics.get("same_three_set_rate") or 0.0)
    ordered_top2 = float(venue_metrics.get("ordered_top2_rate") or 0.0)
    pattern = "neutral"
    if venue_samples >= MIN_VENUE_SAMPLES:
        if same_three >= ordered_top2 + 0.02:
            pattern = "same_three_order"
        elif ordered_top2 >= same_three + 0.08:
            pattern = "ordered_top2_third"

    return enabled, {
        "learning_version": state.get("learning_version"),
        "samples": samples,
        "global_bridge_miss_rate": rate,
        "venue_samples": venue_samples,
        "venue_bridge_miss_rate": venue_rate if venue_samples else None,
        "venue_same_three_set_rate": same_three if venue_samples else None,
        "venue_ordered_top2_rate": ordered_top2 if venue_samples else None,
        "venue_pattern": pattern,
    }


def _parts(row: dict) -> tuple[int, int, int] | None:
    combo = str(row.get("combination") or "")
    bits = combo.split("-")
    if len(bits) != 3 or any(bit not in {"1", "2", "3", "4", "5", "6"} for bit in bits):
        return None
    values = tuple(int(bit) for bit in bits)
    return values if len(set(values)) == 3 else None


def _prob(row: dict) -> float:
    try:
        return float(row.get("probability") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _ev(row: dict) -> float | None:
    value = row.get("expected_value")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bridge_kind(
    candidate: tuple[int, int, int],
    base: tuple[int, int, int],
    allow_head_swap: bool,
    *,
    order_bias: float = 0.0,
    third_bias: float = 0.0,
) -> float:
    if candidate[:2] == base[:2] and candidate[2] != base[2]:
        return 3.0 + max(0.0, third_bias)
    if set(candidate) == set(base) and candidate != base:
        return 2.6 + max(0.0, order_bias)
    if candidate[0] == base[0] and candidate[2] == base[2] and candidate[1] != base[1]:
        return 2.2 + max(0.0, order_bias * 0.5)
    if allow_head_swap and candidate[1:] == base[1:] and candidate[0] != base[0]:
        return 1.8
    return 0.0


def _reallocate(analysis: dict, picks: list[dict]) -> list[dict]:
    venue = str(analysis.get("venue") or "")
    enabled, metrics = _metrics_for(venue)
    meta = {
        **metrics,
        "enabled": enabled,
        "replacements": [],
        "point_count_before": len(picks),
        "point_count_after": len(picks),
    }
    analysis["bridge_learning"] = meta

    # Preserve the original six core picks. Reallocate only variable-width
    # cover slots that were already going to be used.
    if not enabled or len(picks) <= 6:
        return picks

    rows = list(analysis.get("trifecta") or [])
    selected = list(picks)
    selected_combos = {str(row.get("combination") or "") for row in selected}
    core = [item for item in (_parts(row) for row in selected[:6]) if item is not None]
    if not core:
        return selected

    heads = analysis.get("heads") or {}
    ranked_heads = sorted(heads.items(), key=lambda item: float(item[1]), reverse=True)
    allowed_heads = {int(item[0]) for item in ranked_heads[:2]}
    head_gap = (
        float(ranked_heads[0][1]) - float(ranked_heads[1][1])
        if len(ranked_heads) >= 2 else 1.0
    )
    allow_head_swap = head_gap < 0.10

    # Venue learning changes only the *priority* of bridge candidates. Core six,
    # point count, probability floor and EV floor remain untouched.
    pattern = str(metrics.get("venue_pattern") or "neutral")
    same_three = float(metrics.get("venue_same_three_set_rate") or 0.0)
    ordered_top2 = float(metrics.get("venue_ordered_top2_rate") or 0.0)
    order_bias = 0.0
    third_bias = 0.0
    if int(metrics.get("venue_samples") or 0) >= MIN_VENUE_SAMPLES:
        if pattern == "same_three_order":
            order_bias = min(0.60, max(0.15, (same_three - ordered_top2) * 8.0))
        elif pattern == "ordered_top2_third":
            third_bias = min(0.60, max(0.15, (ordered_top2 - same_three) * 5.0))
    meta["venue_pattern"] = pattern
    meta["order_bias"] = round(order_bias, 3)
    meta["third_bias"] = round(third_bias, 3)

    candidates = []
    for row in rows:
        combo = str(row.get("combination") or "")
        if not combo or combo in selected_combos:
            continue
        parts = _parts(row)
        if parts is None or parts[0] not in allowed_heads:
            continue

        kind = max((
            _bridge_kind(
                parts,
                base,
                allow_head_swap,
                order_bias=order_bias,
                third_bias=third_bias,
            )
            for base in core
        ), default=0.0)
        if kind <= 0:
            continue

        probability = _prob(row)
        if probability < 0.004:
            continue
        ev = _ev(row)
        if ev is not None and ev < 0.70:
            continue

        score = kind + probability * 100.0 + (min(ev, 2.0) * 0.20 if ev is not None else 0.0)
        candidates.append((score, probability, row, kind))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if not candidates:
        return selected

    replaceable = sorted(
        range(6, len(selected)),
        key=lambda index: (_prob(selected[index]), index),
    )
    replacements = 0
    for _, probability, candidate, kind in candidates:
        if replacements >= MAX_REPLACEMENTS or not replaceable:
            break

        victim_index = replaceable.pop(0)
        victim = selected[victim_index]
        victim_probability = _prob(victim)

        # Do not trade a clearly stronger cover point for a weak hedge.
        if victim_probability > 0 and probability < victim_probability * 0.55:
            continue

        old_combo = str(victim.get("combination") or "")
        new_combo = str(candidate.get("combination") or "")
        if new_combo in {str(row.get("combination") or "") for row in selected}:
            continue

        selected[victim_index] = candidate
        meta["replacements"].append({
            "out": old_combo,
            "in": new_combo,
            "bridge_strength": round(kind, 2),
            "probability": round(probability, 6),
        })
        replacements += 1

    meta["point_count_after"] = len(selected)
    meta["applied"] = bool(meta["replacements"])
    return selected


def install(app: Any) -> None:
    """Wrap detailed_discord_notify without changing core six or point count."""
    original_displayed = app.displayed_picks_variable
    original_message = app.analysis_message_with_virtual
    original_log = app.log_prediction_with_virtual
    meta_cache: dict[tuple, dict] = {}

    def displayed(analysis, required):
        return _reallocate(analysis, list(original_displayed(analysis, required)))

    def message(day, jcd, rno, deadline, phase, analysis, rows, required):
        key = (day, str(jcd), int(rno), phase)
        meta_cache[key] = dict(analysis.get("bridge_learning") or {})
        return original_message(day, jcd, rno, deadline, phase, analysis, rows, required)

    def logged(record):
        key = (
            record.get("day"),
            str(record.get("jcd")),
            int(record.get("rno", 0)),
            record.get("phase", "final"),
        )
        meta = meta_cache.get(key)
        if meta:
            record = dict(record)
            record["bridge_learning"] = meta
            record["bridge_learning_version"] = "bridge-cover-v2-venue-pattern"
            policy = str(record.get("prediction_point_policy") or "")
            record["prediction_point_policy"] = (
                policy + "+bridge_reallocation" if policy else "bridge_reallocation"
            )
        return original_log(record)

    app.displayed_picks_variable = displayed
    app.analysis_message_with_virtual = message
    app.log_prediction_with_virtual = logged
