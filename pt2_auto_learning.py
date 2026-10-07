"""Automatic learning monitor for the new PT2 model.

This job never mutates live PT2 weights. It continuously evaluates whether the
Google-Sheets DB adjustment helped or hurt settled races, summarizes signal
families, and emits evidence-based candidate recommendations. Live promotion is
kept behind sample-size gates.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
PREDICTION_ROOT = Path("data/prototype12_delivery/predictions")
SCORE_ROOT = Path("data/prototype_scoreboard")
OUT_ROOT = Path("data/pt2_learning")

MODEL_VERSION = "new-pt2-full-sheet-db-v2"
LEGACY_VERSION = "legacy-pt2-pre-full-db"
NEW_DB_SNAPSHOT_MIN = "2026-10-07T13:02:56+09:00"

UNIT_YEN = 100
MIN_REVIEW_SAMPLES = 50
MIN_SHADOW_TUNE_SAMPLES = 100
MIN_SIGNAL_SAMPLES = 30
POSITION_WEIGHTS = (1.0, 0.45, 0.20)


def read_json(path: Path, default=None):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value
    except (OSError, ValueError):
        return default


def write_json_if_changed(path: Path, value) -> bool:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return True


def pt2_model_version(model: dict) -> str:
    explicit = str(model.get("model_version") or "")
    if explicit:
        return explicit
    snapshot_at = str((model.get("database") or {}).get("snapshot_at") or "")
    if snapshot_at and snapshot_at >= NEW_DB_SNAPSHOT_MIN:
        return MODEL_VERSION
    return LEGACY_VERSION


def _winner_from_official(official: dict) -> str | None:
    if not isinstance(official, dict) or official.get("status") != "settled":
        return None
    payouts = official.get("payouts") or {}
    winners = []
    for combo, payout in payouts.items():
        try:
            value = int(payout or 0)
        except (TypeError, ValueError):
            continue
        if value > 0 and _valid_combo(combo):
            winners.append((value, str(combo)))
    # Dead heats can expose multiple valid winning combinations. Use the first
    # deterministic combination for probability calibration; hit/return scoring
    # still checks every payout below.
    if not winners:
        return None
    return sorted(winners, key=lambda item: item[1])[0][1]


def _valid_combo(combo) -> bool:
    bits = str(combo or "").split("-")
    return len(bits) == 3 and all(bit in {"1", "2", "3", "4", "5", "6"} for bit in bits) and len(set(bits)) == 3


def _official_for(day: str, key: str) -> dict | None:
    direct = SCORE_ROOT / day / "official" / f"{key}.json"
    value = read_json(direct)
    if isinstance(value, dict):
        return value
    scored = read_json(SCORE_ROOT / day / "results" / f"{key}.json")
    if isinstance(scored, dict):
        official = scored.get("official")
        if isinstance(official, dict):
            return official
    return None


def _signal_family(signal: str) -> str:
    text = str(signal or "").strip()
    if not text:
        return "unknown"
    return text.split("=", 1)[0].strip() or "unknown"


def _float(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def evaluate_prediction(record: dict, official: dict) -> dict | None:
    model = ((record.get("models") or {}).get("prototype2") or {})
    if not isinstance(model, dict) or pt2_model_version(model) != MODEL_VERSION:
        return None
    audit = model.get("learning_audit") or {}
    db = model.get("database") or {}
    probability_audit = db.get("probability_audit") or {}
    if not isinstance(audit, dict) or not audit:
        return None

    winner = _winner_from_official(official)
    if not winner:
        return None

    adjusted_rows = {
        str(row.get("combination")): row
        for row in model.get("trifecta") or []
        if row.get("combination")
    }
    winner_row = adjusted_rows.get(winner) or {}
    base_p = _float((probability_audit.get("base_probability") or {}).get(winner))
    adjusted_p = _float(winner_row.get("probability"))
    delta_pp = None
    logloss_base = None
    logloss_adjusted = None
    if base_p is not None and adjusted_p is not None:
        delta_pp = (adjusted_p - base_p) * 100
        logloss_base = -math.log(max(base_p, 1e-12))
        logloss_adjusted = -math.log(max(adjusted_p, 1e-12))

    picks = list(dict.fromkeys(model.get("picks") or []))
    payouts = official.get("payouts") or {}
    stake = len(picks) * UNIT_YEN
    returned = 0
    winning_picks = []
    for pick in picks:
        try:
            payout = int(payouts.get(pick, 0) or 0)
        except (TypeError, ValueError):
            payout = 0
        if payout > 0:
            winning_picks.append(pick)
            returned += payout

    added = set(audit.get("added_by_db") or [])
    removed = set(audit.get("removed_by_db") or [])
    retained = set(audit.get("retained_after_db") or [])
    baseline = retained | removed
    db_candidates = retained | added

    signal_occurrences = []
    winner_lanes = [int(bit) for bit in winner.split("-")]
    lane_factors = audit.get("lane_factors") or {}
    for position, lane in enumerate(winner_lanes):
        lane_info = lane_factors.get(str(lane)) or {}
        for signal in lane_info.get("signals") or []:
            signal_occurrences.append({
                "family": _signal_family(signal),
                "signal": str(signal),
                "position": position + 1,
                "position_weight": POSITION_WEIGHTS[position],
            })

    return {
        "key": record.get("key"),
        "day": record.get("day"),
        "venue": record.get("venue"),
        "jcd": str(record.get("jcd") or "").zfill(2),
        "rno": int(record.get("rno") or 0),
        "prediction_created_at": record.get("created_at"),
        "model_version": MODEL_VERSION,
        "db_snapshot_at": db.get("snapshot_at"),
        "db_player_matches": db.get("player_matches"),
        "db_motor_matches": db.get("motor_matches"),
        "winner": winner,
        "winner_base_probability": base_p,
        "winner_adjusted_probability": adjusted_p,
        "winner_delta_pp": round(delta_pp, 6) if delta_pp is not None else None,
        "winner_probability_improved": bool(delta_pp is not None and delta_pp > 0),
        "winner_probability_hurt": bool(delta_pp is not None and delta_pp < 0),
        "logloss_base": logloss_base,
        "logloss_adjusted": logloss_adjusted,
        "logloss_improvement": (
            logloss_base - logloss_adjusted
            if logloss_base is not None and logloss_adjusted is not None
            else None
        ),
        "winner_in_baseline_candidates": winner in baseline,
        "winner_in_db_candidates": winner in db_candidates,
        "winner_added_by_db": winner in added,
        "winner_removed_by_db": winner in removed,
        "winner_retained_after_db": winner in retained,
        "winner_in_final_picks": winner in picks,
        "hit": bool(winning_picks),
        "winning_picks": winning_picks,
        "point_count": len(picks),
        "stake_yen": stake,
        "return_yen": returned,
        "profit_yen": returned - stake,
        "signal_occurrences": signal_occurrences,
    }


def collect_rows() -> list[dict]:
    rows = []
    if not PREDICTION_ROOT.exists():
        return rows
    for path in sorted(PREDICTION_ROOT.glob("*.json")):
        record = read_json(path)
        if not isinstance(record, dict):
            continue
        day = str(record.get("day") or "")
        key = str(record.get("key") or "")
        if not day or not key:
            continue
        official = _official_for(day, key)
        if not isinstance(official, dict):
            continue
        evaluated = evaluate_prediction(record, official)
        if evaluated is not None:
            rows.append(evaluated)
    return rows


def _avg(values):
    values = [float(x) for x in values if x is not None]
    return sum(values) / len(values) if values else None


def _pct(num: int, den: int):
    return 100 * num / den if den else None


def build_state(rows: list[dict]) -> dict:
    samples = len(rows)
    hits = sum(bool(row.get("hit")) for row in rows)
    stake = sum(int(row.get("stake_yen") or 0) for row in rows)
    returned = sum(int(row.get("return_yen") or 0) for row in rows)

    comparable = [
        row for row in rows
        if row.get("winner_base_probability") is not None
        and row.get("winner_adjusted_probability") is not None
    ]
    improved = sum(bool(row.get("winner_probability_improved")) for row in comparable)
    hurt = sum(bool(row.get("winner_probability_hurt")) for row in comparable)

    signal_stats = defaultdict(lambda: {
        "weighted_occurrences": 0.0,
        "raw_occurrences": 0,
        "positive_delta_weight": 0.0,
        "negative_delta_weight": 0.0,
        "delta_weighted_sum": 0.0,
        "logloss_improvement_weighted_sum": 0.0,
        "examples": [],
    })
    for row in rows:
        delta = _float(row.get("winner_delta_pp"))
        lli = _float(row.get("logloss_improvement"))
        for occurrence in row.get("signal_occurrences") or []:
            family = occurrence.get("family") or "unknown"
            weight = _float(occurrence.get("position_weight")) or 0.0
            stat = signal_stats[family]
            stat["weighted_occurrences"] += weight
            stat["raw_occurrences"] += 1
            if delta is not None:
                stat["delta_weighted_sum"] += delta * weight
                if delta > 0:
                    stat["positive_delta_weight"] += weight
                elif delta < 0:
                    stat["negative_delta_weight"] += weight
            if lli is not None:
                stat["logloss_improvement_weighted_sum"] += lli * weight
            if len(stat["examples"]) < 5:
                stat["examples"].append({
                    "key": row.get("key"),
                    "signal": occurrence.get("signal"),
                    "winner_delta_pp": row.get("winner_delta_pp"),
                })

    by_signal = {}
    for family, stat in sorted(signal_stats.items()):
        weight = stat["weighted_occurrences"]
        by_signal[family] = {
            "raw_occurrences": stat["raw_occurrences"],
            "weighted_occurrences": round(weight, 3),
            "mean_winner_delta_pp": (
                round(stat["delta_weighted_sum"] / weight, 6) if weight else None
            ),
            "mean_logloss_improvement": (
                round(stat["logloss_improvement_weighted_sum"] / weight, 6) if weight else None
            ),
            "positive_delta_share": (
                round(stat["positive_delta_weight"] / weight, 4) if weight else None
            ),
            "negative_delta_share": (
                round(stat["negative_delta_weight"] / weight, 4) if weight else None
            ),
            "examples": stat["examples"],
        }

    return {
        "updated_at": datetime.now(JST).isoformat(),
        "learning_version": "pt2-auto-learning-v1",
        "model_version": MODEL_VERSION,
        "safety": {
            "live_weights_mutated": False,
            "minimum_review_samples": MIN_REVIEW_SAMPLES,
            "minimum_shadow_tune_samples": MIN_SHADOW_TUNE_SAMPLES,
            "minimum_signal_samples": MIN_SIGNAL_SAMPLES,
        },
        "samples": samples,
        "performance": {
            "hits": hits,
            "hit_rate": _pct(hits, samples),
            "stake_yen": stake,
            "return_yen": returned,
            "profit_yen": returned - stake,
            "roi": (100 * returned / stake) if stake else None,
            "avg_points": _avg([row.get("point_count") for row in rows]),
        },
        "db_effect": {
            "comparable_samples": len(comparable),
            "winner_probability_improved": improved,
            "winner_probability_hurt": hurt,
            "winner_probability_improved_rate": _pct(improved, len(comparable)),
            "winner_probability_hurt_rate": _pct(hurt, len(comparable)),
            "avg_winner_delta_pp": _avg([row.get("winner_delta_pp") for row in comparable]),
            "avg_logloss_base": _avg([row.get("logloss_base") for row in comparable]),
            "avg_logloss_adjusted": _avg([row.get("logloss_adjusted") for row in comparable]),
            "avg_logloss_improvement": _avg([row.get("logloss_improvement") for row in comparable]),
            "winner_added_by_db": sum(bool(row.get("winner_added_by_db")) for row in rows),
            "winner_removed_by_db": sum(bool(row.get("winner_removed_by_db")) for row in rows),
            "winner_retained_after_db": sum(bool(row.get("winner_retained_after_db")) for row in rows),
            "winner_in_final_picks": sum(bool(row.get("winner_in_final_picks")) for row in rows),
        },
        "by_signal_family": by_signal,
        "recent_rows": rows[-20:],
    }


def build_recommendation(state: dict) -> dict:
    samples = int(state.get("samples") or 0)
    db = state.get("db_effect") or {}
    improvement = _float(db.get("avg_logloss_improvement"))
    improved_rate = _float(db.get("winner_probability_improved_rate"))
    performance = state.get("performance") or {}

    if samples < MIN_REVIEW_SAMPLES:
        phase = "collecting"
        action = "keep_live_weights"
        reason = f"Need at least {MIN_REVIEW_SAMPLES} settled audited races before weight review."
    elif improvement is not None and improvement > 0 and (improved_rate or 0) >= 52:
        phase = "evidence_positive"
        action = "build_shadow_candidate" if samples >= MIN_SHADOW_TUNE_SAMPLES else "keep_collecting"
        reason = "DB adjustment is improving winner probability on average; keep live weights stable while collecting more evidence."
    else:
        phase = "needs_review"
        action = "build_shadow_candidate" if samples >= MIN_SHADOW_TUNE_SAMPLES else "keep_collecting"
        reason = "DB adjustment is not yet showing robust probability improvement; do not strengthen live weights."

    signal_actions = {}
    for family, metrics in (state.get("by_signal_family") or {}).items():
        raw = int(metrics.get("raw_occurrences") or 0)
        mean_delta = _float(metrics.get("mean_winner_delta_pp"))
        mean_ll = _float(metrics.get("mean_logloss_improvement"))
        if raw < MIN_SIGNAL_SAMPLES:
            signal_actions[family] = {
                "status": "collecting",
                "raw_occurrences": raw,
                "recommended_multiplier_change": 0.0,
            }
            continue
        if (mean_delta or 0) > 0.02 and (mean_ll or 0) > 0:
            change = 0.05
            status = "positive_candidate"
        elif (mean_delta or 0) < -0.02 and (mean_ll or 0) < 0:
            change = -0.10
            status = "weaken_candidate"
        else:
            change = 0.0
            status = "neutral"
        signal_actions[family] = {
            "status": status,
            "raw_occurrences": raw,
            "recommended_multiplier_change": change,
            "mean_winner_delta_pp": mean_delta,
            "mean_logloss_improvement": mean_ll,
        }

    return {
        "updated_at": datetime.now(JST).isoformat(),
        "model_version": MODEL_VERSION,
        "phase": phase,
        "action": action,
        "reason": reason,
        "automatic_live_promotion": False,
        "promotion_gate": {
            "minimum_samples": MIN_SHADOW_TUNE_SAMPLES,
            "requires_positive_logloss_improvement": True,
            "requires_shadow_backtest": True,
            "requires_no_material_roi_regression": True,
        },
        "current_metrics": {
            "samples": samples,
            "hit_rate": performance.get("hit_rate"),
            "roi": performance.get("roi"),
            "avg_logloss_improvement": improvement,
            "winner_probability_improved_rate": improved_rate,
        },
        "signal_candidates": signal_actions,
    }


def main() -> int:
    rows = collect_rows()
    state = build_state(rows)
    recommendation = build_recommendation(state)
    changed = False
    changed |= write_json_if_changed(OUT_ROOT / "state.json", state)
    changed |= write_json_if_changed(OUT_ROOT / "recommendation.json", recommendation)
    print(json.dumps({
        "changed": changed,
        "samples": state["samples"],
        "phase": recommendation["phase"],
        "action": recommendation["action"],
        "roi": state["performance"]["roi"],
        "avg_logloss_improvement": state["db_effect"]["avg_logloss_improvement"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
