"""Expanded boat-race prediction model built on prediction_engine v1.

Adds all 24 venue priors, water/weight, tilt/parts and course-flow (suji) adjustments
while keeping hard data dominant. Heuristics are deliberately bounded so they can
be calibrated later from results.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

import prediction_engine as v1

# Conservative multipliers. These are not literal win rates; they only nudge the
# base score and are intentionally close to 1.00.
ALL_VENUE_PROFILES = {
    "桐生":{"1":1.03,"2":1.00,"3":1.00,"4":1.02,"5":0.99,"6":0.97},
    "戸田":{"1":0.90,"2":1.03,"3":1.04,"4":1.04,"5":1.02,"6":1.00},
    "江戸川":{"1":0.93,"2":1.01,"3":1.02,"4":1.03,"5":1.01,"6":1.00},
    "平和島":{"1":0.92,"2":1.02,"3":1.03,"4":1.03,"5":1.01,"6":0.99},
    "多摩川":{"1":1.01,"2":1.00,"3":1.00,"4":1.01,"5":0.99,"6":0.98},
    "浜名湖":{"1":1.01,"2":1.00,"3":1.01,"4":1.01,"5":0.99,"6":0.98},
    "蒲郡":{"1":1.00,"2":0.99,"3":1.00,"4":1.04,"5":1.00,"6":0.98},
    "常滑":{"1":1.03,"2":1.00,"3":1.00,"4":1.01,"5":0.98,"6":0.97},
    "津":{"1":1.00,"2":1.03,"3":1.01,"4":1.00,"5":0.98,"6":0.97},
    "三国":{"1":1.04,"2":1.00,"3":1.00,"4":1.01,"5":0.98,"6":0.97},
    "びわこ":{"1":0.99,"2":1.01,"3":1.02,"4":1.01,"5":1.00,"6":0.98},
    "住之江":{"1":1.04,"2":1.00,"3":1.00,"4":1.01,"5":0.98,"6":0.97},
    "尼崎":{"1":1.03,"2":1.01,"3":1.00,"4":1.00,"5":0.98,"6":0.97},
    "鳴門":{"1":0.96,"2":1.00,"3":1.03,"4":1.00,"5":1.03,"6":0.98},
    "丸亀":{"1":1.03,"2":1.00,"3":1.00,"4":1.02,"5":0.99,"6":0.98},
    "児島":{"1":1.03,"2":1.00,"3":1.01,"4":1.01,"5":0.98,"6":0.97},
    "宮島":{"1":1.02,"2":1.00,"3":1.01,"4":1.01,"5":0.99,"6":0.98},
    "徳山":{"1":1.10,"2":0.99,"3":0.98,"4":0.97,"5":0.96,"6":0.95},
    "下関":{"1":1.07,"2":1.00,"3":0.99,"4":0.99,"5":0.97,"6":0.96},
    "若松":{"1":1.03,"2":1.00,"3":1.00,"4":1.02,"5":0.99,"6":0.98},
    "芦屋":{"1":1.08,"2":1.00,"3":0.99,"4":0.98,"5":0.97,"6":0.96},
    "福岡":{"1":0.97,"2":1.00,"3":1.04,"4":1.01,"5":1.00,"6":0.98},
    "唐津":{"1":1.04,"2":1.00,"3":1.00,"4":1.01,"5":0.98,"6":0.97},
    "大村":{"1":1.10,"2":0.99,"3":0.98,"4":0.97,"5":0.96,"6":0.95},
}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _augment_boat(boat: Mapping[str, Any], race: Mapping[str, Any]) -> dict:
    b = dict(boat)
    course = int(b.get("predicted_course") or b.get("course") or b.get("lane") or 0)

    # Water/weight is only a small tiebreaker; never a main factor.
    water = str(race.get("water_quality") or "").lower()
    weight = _f(b.get("weight"), 52.0)
    water_adj = 0.0
    if any(k in water for k in ("淡水", "fresh")):
        water_adj = max(-0.04, min(0.04, (52.0 - weight) * 0.008))
    elif any(k in water for k in ("海水", "sea", "salt")):
        water_adj = max(-0.02, min(0.02, (52.0 - weight) * 0.003))

    # Tilt: high tilt is treated as a mild straight/attack signal, especially outside.
    tilt = _f(b.get("tilt"), 0.0)
    tilt_adj = 0.0
    if tilt >= 0.5 and course >= 3:
        tilt_adj = min(0.10, tilt * 0.04)
    elif tilt < 0 and course <= 2:
        tilt_adj = 0.02

    # Parts exchange is contextual: no automatic penalty, only a small uncertainty drag
    # if many parts changed and there is no positive comment/exhibition grade.
    parts = b.get("parts_changed") or []
    if isinstance(parts, str):
        parts = [x for x in parts.replace("、", ",").split(",") if x.strip()]
    parts_penalty = -0.03 if isinstance(parts, (list, tuple)) and len(parts) >= 2 else 0.0

    # Fold bounded technical context into grades the v1 scorer already understands.
    technical = max(0.20, min(0.90, 0.50 + water_adj + tilt_adj + parts_penalty))
    current_comment = b.get("comment_grade")
    if current_comment is None:
        b["comment_grade"] = technical
    elif isinstance(current_comment, (int, float)):
        b["comment_grade"] = max(0.0, min(1.0, 0.8 * float(current_comment) + 0.2 * technical))
    return b


def _flow_multiplier(first: int, second: int, third: int) -> float:
    """Small course-flow/suji adjustment for ordered trifectas."""
    mult = 1.0
    # 2-course attack often leaves 1 or 3 in the follow-up lane.
    if first == 2 and second in (1, 3):
        mult *= 1.05
    # 3-course attack: 4 follows a makuri; 1 remains common on makuri-sashi.
    if first == 3 and second in (4, 1):
        mult *= 1.07
    # 4-course attack frequently drags 5/6 into the outside follow-up.
    if first == 4 and second in (5, 6):
        mult *= 1.08
    # 5/6 winners are more credible when an adjacent outside boat follows.
    if first == 5 and second in (4, 6):
        mult *= 1.05
    if first == 6 and second in (4, 5):
        mult *= 1.04
    # Inside escape/difference patterns.
    if first == 1 and second in (2, 3, 4):
        mult *= 1.03
    if third == 6 and first == 1:
        mult *= 0.99
    return mult


def analyze_race_v2(payload: Mapping[str, Any]) -> dict:
    data = deepcopy(dict(payload))
    race = data.get("race") if isinstance(data.get("race"), Mapping) else data
    boats = data.get("boats") or race.get("boats") or []

    # Extend venue knowledge used by v1 without modifying its API.
    v1.VENUE_PROFILES.update(ALL_VENUE_PROFILES)
    augmented = [_augment_boat(b, race) for b in boats]
    data["boats"] = augmented
    if isinstance(data.get("race"), dict):
        data["race"]["boats"] = augmented

    out = v1.analyze_race(data)

    # Re-rank all 120 combinations with bounded flow knowledge, then renormalize.
    rows = out.get("trifecta", [])
    if rows:
        adjusted = []
        for row in rows:
            a, b, c = map(int, row["combination"].split("-"))
            p = float(row["probability"]) * _flow_multiplier(a, b, c)
            adjusted.append((row, p))
        total = sum(p for _, p in adjusted) or 1.0
        new_rows = []
        odds = payload.get("trifecta_odds") or race.get("trifecta_odds") or {}
        for row, p in adjusted:
            nr = dict(row)
            nr["probability"] = p / total
            nr["fair_odds"] = round(1.0 / nr["probability"], 2)
            odd = odds.get(nr["combination"]) if isinstance(odds, Mapping) else None
            if odd is not None:
                try:
                    nr["odds"] = float(odd)
                    nr["expected_value"] = round(nr["probability"] * nr["odds"], 3)
                except (TypeError, ValueError):
                    nr["expected_value"] = None
            new_rows.append(nr)
        new_rows.sort(key=lambda x: x["probability"], reverse=True)
        out["trifecta"] = new_rows
        out["value_bets"] = [x for x in new_rows if x.get("expected_value") is not None and x["expected_value"] >= 1.05][:20]

    out["model_version"] = "kyoutei-navi-knowledge-v2"
    out["knowledge"] = [
        "24 venue priors", "entry/start/motor/exhibition", "wind/tide/night",
        "water/weight", "tilt/parts", "course-flow/suji", "fair odds/EV"
    ]
    return out
