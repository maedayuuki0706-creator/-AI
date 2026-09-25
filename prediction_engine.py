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
    # Recent official course data show Tokoname is materially more inside-favoring
    # than Toda, so keep a conservative venue-specific boost rather than a
    # blanket stronger No.1-lane rule for every venue.
    "常滑": {"1": 1.08, "2": 1.00, "3": 0.99, "4": 0.99, "5": 0.97, "6": 0.95},
    "戸田": {"1": 0.90, "2": 1.03, "3": 1.04, "4": 1.04, "5": 1.02, "6": 1.00},
    "平和島": {"1": 0.92, "2": 1.02, "3": 1.03, "4": 1.03, "5": 1.01, "6": 0.99},
    "江戸川": {"1": 0.93, "2": 1.01, "3": 1.02, "4": 1.03, "5": 1.01, "6": 1.00},
    "鳴門": {"1": 0.96, "2": 1.00, "3": 1.03, "4": 1.00, "5": 1.03, "6": 0.98},
    "蒲郡": {"1": 1.00, "2": 0.99, "3": 1.00, "4": 1.04, "5": 1.00, "6": 0.98},
    "津": {"1": 1.00, "2": 1.03, "3": 1.01, "4": 1.00, "5": 0.98, "6": 0.97},
    "福岡": {"1": 0.97, "2": 1.00, "3": 1.04, "4": 1.01, "5": 1.00, "6": 0.98},
}

WEIGHTS = {
    # Course structure gets priority over raw racer strength. Venue profiles
    # still decide how much that helps or hurts the inside at each stadium.
    "racer": 0.16,
    "course": 0.22,
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
    # Inputs use official units: rates in percent, win rate on the 0–10 scale.
    return _clip(v / scale)


def _norm_st(value: Any, default: float = 0.5) -> float:
    """Convert ST to quality where 1 is strong. .10≈0.83, .20≈0.50."""
    if value is None:
        return default
    try:
        st = float(value)
    except (TypeError, ValueError):
        return default
    if st < 0 or st > 1:
        return default
    return _clip((0.35 - st) / 0.30)


def _history_sample_weight(value: Any) -> float:
    """Require a useful sample before historical race style can move the model."""
    try:
        samples = int(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if samples < 6:
        return 0.0
    return _clip((samples - 5) / 25.0)


# Model baselines, not claims about any one current race. They match the
# conservative course priors used by racer_profiles and keep the new feature
# bounded until prospective results justify recalibration.
_HISTORY_METHOD_BASELINE = {1: 55.0, 2: 15.0, 3: 13.0, 4: 11.0, 5: 5.0, 6: 2.0}


def _historical_course_signal(boat: Mapping[str, Any], course: int) -> float:
    """Return -1..1 historical style signal with strong sample shrinkage."""
    weight = _history_sample_weight(
        boat.get("course_history_samples") or boat.get("racer_profile_course_samples")
    )
    if weight <= 0 or course not in _HISTORY_METHOD_BASELINE:
        return 0.0

    key = "in_escape_rate" if course == 1 else "course_attack_rate"
    value = boat.get(key)
    if value is None:
        return 0.0
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not 0 <= rate <= 100:
        return 0.0

    baseline = _HISTORY_METHOD_BASELINE[course]
    # A 20-point deviation is a full signal. The final score adjustment below
    # is still deliberately small, so exhibition/motor/current form stay primary.
    signal = _clip((rate - baseline) / 20.0, -1.0, 1.0)
    return signal * weight


def _blended_historical_st(boat: Mapping[str, Any]) -> Any:
    """Blend course-specific historical ST into the current published average."""
    current = boat.get("avg_st")
    course_st = boat.get("course_history_avg_st")
    weight = _history_sample_weight(
        boat.get("course_history_samples") or boat.get("racer_profile_course_samples")
    )
    if course_st is None or weight <= 0:
        return current
    try:
        historical = float(course_st)
        if not 0 <= historical <= 1:
            return current
        if current is None:
            return historical
        current_value = float(current)
        if not 0 <= current_value <= 1:
            return historical
    except (TypeError, ValueError):
        return current
    # Never let history replace live/current form; cap it at 35%.
    historical_weight = 0.35 * weight
    return (1.0 - historical_weight) * current_value + historical_weight * historical


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
    tide_raw = race.get("tide")
    if isinstance(tide_raw, Mapping):
        if tide_raw.get("available"):
            phase = str(tide_raw.get("phase") or "").lower()
            level = str(tide_raw.get("level_band") or "").lower()
            tide = " ".join([phase, level])
        else:
            tide = ""
    else:
        tide = str(tide_raw or "").lower()
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

    if any(k in tide for k in ("干潮", "下げ", "ebb", "low", "falling")):
        if course in (3, 4, 5):
            score += 0.04
        elif course == 1:
            score -= 0.02
    elif any(k in tide for k in ("満潮", "上げ", "flood", "high", "rising")):
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
        0.55 * _norm_st(_blended_historical_st(boat))
        + 0.45 * _norm_st(boat.get("exhibition_st"))
    )
    if boat.get("flying"):
        start *= 0.92

    motor = (
        0.45 * _norm_rate(boat.get("motor_top2_rate"))
        + 0.20 * _norm_rate(boat.get("motor_top3_rate"))
        + 0.35 * _grade(boat.get("motor_grade"))
    )
    # BOAT RACE publishes separate hull/boat performance beside motor stats.
    # Blend it lightly so the more stable motor history remains dominant.
    if boat.get("boat_top2_rate") is not None or boat.get("boat_top3_rate") is not None:
        hull = (
            0.60 * _norm_rate(boat.get("boat_top2_rate"))
            + 0.40 * _norm_rate(boat.get("boat_top3_rate"))
        )
        motor = 0.90 * motor + 0.10 * hull
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

    # Shared historical race-style adjustment. This is intentionally capped at
    # +/-0.008 raw score; it refines the current model rather than overriding it.
    history_signal = _historical_course_signal(boat, course)
    raw += 0.008 * history_signal
    parts["history"] = 0.5 + 0.5 * history_signal

    if course == 1:
        raw *= 1.06
    elif course == 2:
        raw *= 1.01
    elif course == 6:
        raw *= 0.97

    raw += max(-0.01, min(0.01, float(boat.get("previous_day_score_delta") or 0)))

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
        "model_version": "kyoutei-navi-course-v3-shared-history-unvalidated",
        "venue": race.get("venue"),
        "boats": scored,
        "trifecta": trifectas,
        "value_bets": value_bets[:20],
        "confidence": round(confidence, 3),
    }
