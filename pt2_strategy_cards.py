"""Purpose-specific strategy cards for new PT2.

The live PT2 balanced card remains untouched. These sub-cards are alternative
views over the same DB-adjusted trifecta distribution so each objective can be
tracked and learned independently.
"""
from __future__ import annotations

from math import isfinite

STRATEGY_VERSION = "pt2-multi-strategy-v1"
UNIT_YEN = 100


def _number(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _rows(analysis):
    rows = []
    for raw in analysis.get("trifecta") or []:
        combo = str(raw.get("combination") or "")
        probability = _number(raw.get("probability"))
        odds = _number(raw.get("odds"))
        ev = _number(raw.get("expected_value"))
        if not combo or probability is None or probability <= 0:
            continue
        rows.append({
            "combination": combo,
            "probability": probability,
            "odds": odds,
            "expected_value": ev,
        })
    return rows


def _card(label, policy, selected, *, notes=None):
    picks = [row["combination"] for row in selected]
    main_count = min(4, len(picks))
    return {
        "label": label,
        "selection_policy": policy,
        "strategy_version": STRATEGY_VERSION,
        "main_picks": picks[:main_count],
        "cover_picks": picks[main_count:],
        "picks": picks,
        "point_count": len(picks),
        "stake_yen": len(picks) * UNIT_YEN,
        "notes": notes or [],
        "pick_metrics": [
            {
                "combination": row["combination"],
                "probability": round(row["probability"], 8),
                "odds": row["odds"],
                "expected_value": row["expected_value"],
            }
            for row in selected
        ],
    }


def _probability_card(rows):
    selected = sorted(
        rows,
        key=lambda row: (-row["probability"], row["combination"]),
    )[:8]
    return _card(
        "本命型",
        "db-adjusted-probability-top8",
        selected,
        notes=["DB補正後の3連単確率を最優先", "的中率の比較用"],
    )


def _value_card(rows):
    qualified = [
        row for row in rows
        if row["odds"] is not None
        and row["expected_value"] is not None
        and row["probability"] >= 0.003
        and row["expected_value"] >= 0.90
    ]
    qualified.sort(
        key=lambda row: (
            -row["expected_value"],
            -row["probability"],
            row["combination"],
        )
    )
    selected = qualified[:8]
    if len(selected) < 4:
        fallback = [
            row for row in rows
            if row["odds"] is not None
            and row["expected_value"] is not None
            and row["probability"] >= 0.002
            and row not in selected
        ]
        fallback.sort(
            key=lambda row: (
                -row["expected_value"],
                -row["probability"],
                row["combination"],
            )
        )
        selected.extend(fallback[: 4 - len(selected)])
    return _card(
        "妙味型",
        "db-adjusted-ev-with-probability-floor",
        selected,
        notes=["EVとモデル確率を両立", "市場の過小評価候補を残す"],
    )


def _longshot_card(rows):
    qualified = [
        row for row in rows
        if row["odds"] is not None
        and row["expected_value"] is not None
        and row["odds"] >= 60.0
        and row["probability"] >= 0.0025
        and row["expected_value"] >= 0.50
    ]
    qualified.sort(
        key=lambda row: (
            -row["expected_value"],
            -row["probability"],
            -row["odds"],
            row["combination"],
        )
    )
    return _card(
        "高配当型",
        "odds60plus-db-probability-and-ev-filter",
        qualified[:8],
        notes=["高配当候補専用", "オッズだけでなく確率とEVの下限を要求"],
    )


def build_strategy_cards(db_adjusted_analysis, balanced_model):
    rows = _rows(db_adjusted_analysis)
    balanced_picks = list(dict.fromkeys(balanced_model.get("picks") or []))
    balanced_main = list(dict.fromkeys(balanced_model.get("main_picks") or []))
    balanced_main_set = set(balanced_main)
    balanced = {
        "label": "総合型",
        "selection_policy": balanced_model.get("selection_policy"),
        "strategy_version": STRATEGY_VERSION,
        "main_picks": balanced_main,
        "cover_picks": [p for p in balanced_picks if p not in balanced_main_set],
        "picks": balanced_picks,
        "point_count": len(balanced_picks),
        "stake_yen": len(balanced_picks) * UNIT_YEN,
        "notes": ["現行PT2をそのまま保存", "母体・比較基準"],
    }
    cards = {
        "balanced": balanced,
        "probability": _probability_card(rows),
        "value": _value_card(rows),
        "longshot": _longshot_card(rows),
    }
    return {
        "version": STRATEGY_VERSION,
        "cards": cards,
    }
