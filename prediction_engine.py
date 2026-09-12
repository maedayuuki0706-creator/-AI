"""Boat-race prediction engine.

Turns normalized race inputs into boat strength, trifecta probabilities,
fair odds and expected value.  The model intentionally separates hard data
from heuristic adjustments so weights can be calibrated later.
"""

from __future__ import annotations

from itertools import permutations
from math import exp
from typing import Any, Dict, Iterable, List, Mapping


VENUE_PROFILES: Dict[str, Dict[str, float]] = {
    # Conservative course priors based on long-run venue tendencies.
    # Values are multipliers, not win probabilities.
    "徳山": {"1": 1.10, "2": 0.99, "3": 0.98, "4": 0.97, "5": 0.96, "6": 0.95},
    "大村": {"1": 1.10, "2": 0.99, "3": 0.98, "4": 0.97, "5": 0.96, "6": 0.95},
    "芦屋": {"1": 1.08, "2": 1.00, "3": 0.99, "4": 0.98, "5": 0.97, "6": 0.96},
    "下関": {"1": 1.07, "2": 1.00, "3": 0.99, "4": 0.99, "5": 0.97, "6": 0.96},
    "戸田": {"1": 0.90, "2": 1.03, "3": 1.04, "4": 1.04, "5": 1.02, "6": 1.00},
    "平和島": {"1": 0.92, "2": 1.02, "3": 1.03, "4": 1.03, "5": 1.01, "6": 0.99},
    "江戸川": {"1": 0.93, "2": 1.01, "3": 1.02, "4": 1.03, "5": 1.01, "6": 1.00},
    "鳴門": {"1": 0.96, "2": 1.00, "3": 1.03, "4": 1.00, "5": 1.03, "6": 0.98},
    "蒲郡": {"1": 1.00, "2": 0.99, "3": 1.00, "4": 1.04, "5": 1.00, "6": 0.98},
    "津": {"1": 1.00, "2": 1.03, "3": 1.01, "4": 1.00, "5": 0.98, "6": 0.97},
    "福岡": {"1": 0.97, "2": 1.00, "3": 1.04, "4": 1.01, "5": 1.00, "6": 0.98},
}

WEIGHTS = {
    "racer": 0.22,
    "course": 0.16,
    "start": 0.15,
    "motor": 0.15,
    "exhibition": 0.15,
    "local": 0.06,
    "entry": 0.05,
    "conditions": 0.04,
    "comments": 0.02,
}


def _clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def _norm_rate(value: Any, *, scale: float = 100.0, default: float = 0.5) -> float:
    if value is None:
        return default
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v > 1.0:
        v /= scale
    return _clip(v)


def _norm_st(value: Any, default: float = 0.5) -> float:
    """Convert ST to quality where 1 is strong. .10≈0.83, .20≈0.50."""
    if value is None:
        return default
    try:
        st = float(value)
    except (TypeError, ValueError):
        return default
    return _clip((0.35 - st) / 0.30)


def _grade(value: Any, default: float = 0.5) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return _clip(value)
    mapping = {
        "S": 1.00, "A": 0.85, "B": 0.68, "C": 0.50, "D": 0.32,
        "◎": 0.90, "○": 0.72, "△": 0.55, "×": 0.30,
        "good": 0.82, "average": 0.50, "bad": 0.25,
    }
    return mapping.get(str(value).strip(), default)


def _condition_adjustment(boat: Mapping[str, Any], race: Mapping[str, Any]) -> float:
    """Small, bounded adjustments for wind/tide/time; never dominate hard data."""
    course = int(boat.get("predicted_course") or boat.get("course") or boat.get("lane") or 0)
    if not 1 <= course <= 6:
        return 0.5

    score = 0.5
    wind_speed = float(race.get("wind_speed") or 0.0)
    wind_dir = str(race.get("wind_direction") or "").lower()
    tide = str(race.get("tide") or "").lower()
    night = bool(race.get("night"))

    if wind_speed >= 4:
        if course == 1:
            score -= 0.12
        elif course in (3, 4, 5):
            score += 0.08

    if "向かい" in wind_dir or "head" in wind_dir:
        if course in (3, 4, 5):
            score += 0.05
        if course == 1:
            score -= 0.04
    elif "追い" in wind_dir or "tail" in wind_dir:
        if wind_speed <= 3 and course == 1:
            score += 0.04
        elif wind_speed >= 5 and course == 1:
            score -= 0.05

    if any(k in tide for k in ("干潮", "下げ", "ebb", "low")):
        if course in (3, 4, 5):
            score += 0.04
    elif any(k in tide for k in ("満潮", "上げ", "flood", "high")):
        if course in (1, 2):
            score += 0.04

    if night and course == 1:
        score += 0.03

    return _clip(score)


def _venue_multiplier(venue: str, course: int) -> float:
    profile = VENUE_PROFILES.get(venue)
    if not profile:
        return 1.0
    return profile.get(str(course), 1.0)


def score_boat(boat: Mapping[str, Any], race: Mapping[str, Any]) -> Dict[str, Any]:
    course = int(boat.get("predicted_course") or boat.get("course") or boat.get("lane") or 0)
    lane = int(boat.get("lane") or course or 0)

    racer = (
        0.55 * _norm_rate(boat.get("win_rate"), scale=10.0)
        + 0.25 * _norm_rate(boat.get("top2_rate"))
        + 0.20 * _norm_rate(boat.get("top3_rate"))
    )
    course_form = (
        0.70 * _norm_rate(boat.get("course_win_rate"))
        + 0.30 * _norm_rate(boat.get("course_top2_rate"))
    )
    start = (
        0.55 * _norm_st(boat.get("avg_st"))
        + 0.45 * _norm_st(boat.get("exhibition_st"))
    )
    if boat.get("flying"):
        start *= 0.92

    motor = (
        0.45 * _norm_rate(boat.get("motor_top2_rate"))
        + 0.20 * _norm_rate(boat.get("motor_top3_rate"))
        + 0.35 * _grade(boat.get("motor_grade"))
    )
    exhibition = (
        0.30 * _grade(boat.get("exhibition_grade"))
        + 0.25 * _grade(boat.get("turn_grade"))
        + 0.20 * _grade(boat.get("straight_grade"))
        + 0.15 * _grade(boat.get("pit_out_grade"))
        + 0.10 * _grade(boat.get("lap_grade"))
    )
    local = (
        0.65 * _norm_rate(boat.get("local_win_rate"), scale=10.0)
        + 0.35 * _norm_rate(boat.get("local_top2_rate"))
    )

    entry = _grade(boat.get("entry_grade"))
    if boat.get("deep_inside"):
        entry = _clip(entry - 0.18)
    if boat.get("front_entry") and course <= 3:
        entry = _clip(entry + 0.05)

    comments = _grade(boat.get("comment_grade"))
    conditions = _condition_adjustment(boat, race)

    parts = {
        "racer": racer,
        "course": course_form,
        "start": start,
        "motor": motor,
        "exhibition": exhibition,
        "local": local,
        "entry": entry,
        "conditions": conditions,
        "comments": comments,
    }
    raw = sum(parts[name] * WEIGHTS[name] for name in WEIGHTS)
    raw *= _venue_multiplier(str(race.get("venue") or ""), course)

    if course == 1:
        raw *= 1.06
    elif course == 2:
        raw *= 1.01
    elif course == 6:
        raw *= 0.97

    return {
        "lane": lane,
        "predicted_course": course,
        "score": round(_clip(raw), 6),
        "components": {k: round(v, 4) for k, v in parts.items()},
    }


def _softmax_strength(score: float, temperature: float = 0.12) -> float:
    return exp(score / temperature)


def trifecta_probabilities(scored: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Plackett-Luce style ordered probabilities for all 120 combinations."""
    boats = list(scored)
    if len(boats) < 3:
        return []
    strengths = {int(b["lane"]): _softmax_strength(float(b["score"])) for b in boats}
    lanes = list(strengths)

    rows: List[Dict[str, Any]] = []
    total_s = sum(strengths.values())
    for first, second, third in permutations(lanes, 3):
        p1 = strengths[first] / total_s
        rem1 = total_s - strengths[first]
        p2 = strengths[second] / rem1
        rem2 = rem1 - strengths[second]
        p3 = strengths[third] / rem2
        rows.append({"combination": f"{first}-{second}-{third}", "probability": p1 * p2 * p3})
    rows.sort(key=lambda x: x["probability"], reverse=True)
    return rows


def analyze_race(payload: Mapping[str, Any]) -> Dict[str, Any]:
    race = payload.get("race") if isinstance(payload.get("race"), Mapping) else payload
    boats = payload.get("boats") or race.get("boats") or []
    scored = [score_boat(b, race) for b in boats]
    scored.sort(key=lambda x: x["score"], reverse=True)

    trifectas = trifecta_probabilities(scored)
    odds = payload.get("trifecta_odds") or race.get("trifecta_odds") or {}
    for row in trifectas:
        odd = odds.get(row["combination"]) if isinstance(odds, Mapping) else None
        row["fair_odds"] = round(1 / row["probability"], 2)
        if odd is None:
            row["expected_value"] = None
            continue
        try:
            odd_value = float(odd)
        except (TypeError, ValueError):
            odd_value = 0.0
        row["odds"] = odd_value
        row["expected_value"] = round(row["probability"] * odd_value, 3)

    value_bets = [
        r for r in trifectas
        if r.get("expected_value") is not None and r["expected_value"] >= 1.05
    ]

    top_score = scored[0]["score"] if scored else 0.0
    second_score = scored[1]["score"] if len(scored) > 1 else top_score
    confidence = _clip(0.5 + (top_score - second_score) * 2.5)

    return {
        "model_version": "kyoutei-navi-knowledge-v1",
        "venue": race.get("venue"),
        "boats": scored,
        "trifecta": trifectas,
        "value_bets": value_bets[:20],
        "confidence": round(confidence, 3),
    }
