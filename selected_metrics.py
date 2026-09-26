"""Build exact daily metrics for the dedicated 厳選 prediction stream."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path

from direct_discord_notify import JST
from daily_report import disclosed_picks, latest_predictions, read_jsonl, totals
from selection_scoring import (
    SELECTED_THRESHOLD,
    STRONG_SELECTED_THRESHOLD,
    passes_stability_gate,
)

PREDICTION_LOG = Path("data/prediction_log.jsonl")
REPORT_DIR = Path("data/daily_reports")
OUTPUT_DIR = Path("data/selected_metrics")
BUDGET_3000_YEN = 3000
UNIT_YEN = 100
BUDGET_3000_UNITS = BUDGET_3000_YEN // UNIT_YEN


def equal_3000_units(row: dict) -> dict[str, int]:
    """Spread exactly 3,000 yen across every disclosed pick in 100-yen units."""
    picks = disclosed_picks(row)
    if not picks:
        return {}
    if len(picks) > BUDGET_3000_UNITS:
        raise ValueError(f"Too many picks for {BUDGET_3000_YEN} yen budget: {len(picks)}")
    base, extra = divmod(BUDGET_3000_UNITS, len(picks))
    return {pick: base + (1 if index < extra else 0) for index, pick in enumerate(picks)}


def settle_equal_3000(prediction: dict, settled: dict) -> dict:
    units = equal_3000_units(prediction)
    if not units:
        return {"stake_yen": 0, "return_yen": 0, "profit_yen": 0, "allocation_yen": {}}
    official = settled.get("official") or {}
    payouts = official.get("payouts") or {}
    refund_lanes = set(official.get("refund_lanes") or [])
    status = official.get("status") or settled.get("status")
    special = int(official.get("special_per_100") or 0)
    returned = 0
    for combo, count in units.items():
        lanes = {int(x) for x in combo.split("-") if str(x).isdigit()}
        if status == "void" or lanes & refund_lanes:
            returned += count * UNIT_YEN
        elif status == "special":
            returned += count * special
        else:
            returned += count * int(payouts.get(combo) or 0)
    stake = sum(units.values()) * UNIT_YEN
    return {
        "stake_yen": stake,
        "return_yen": returned,
        "profit_yen": returned - stake,
        "allocation_yen": {combo: count * UNIT_YEN for combo, count in units.items()},
    }



def selected_record(
    row: dict,
    threshold: int = SELECTED_THRESHOLD,
    require_stability: bool = True,
) -> bool:
    base = (
        row.get("phase") == "final"
        and bool(row.get("exhibition"))
        and int(row.get("selection_score") or 0) >= threshold
        and row.get("virtual_status") == "bet"
    )
    if not base:
        return False
    return (
        passes_stability_gate(row.get("selection_score_breakdown") or {})
        if require_stability else True
    )


def delivered_selected_record(row: dict) -> bool:
    """Reconstruct the rule that was active when this prediction was logged.

    This prevents a new threshold from rewriting historical delivered counts.
    v1 records used score>=75. v2-stability records use the current stability gate.
    """
    version = str(row.get("selection_score_version") or "")
    recorded_threshold = int(row.get("selection_threshold") or 75)
    if version == "selected-score-v2-stability" or recorded_threshold >= SELECTED_THRESHOLD:
        return selected_record(
            row,
            threshold=max(recorded_threshold, SELECTED_THRESHOLD),
            require_stability=True,
        )
    return selected_record(row, threshold=recorded_threshold, require_stability=False)


def subset_summary_predicate(
    records: dict[str, dict],
    settled_by_key: dict[str, dict],
    predicate,
    *,
    threshold_label=None,
    stability_gate_label=None,
) -> dict:
    selected = {key: row for key, row in records.items() if predicate(row)}
    settled = [settled_by_key[key] for key in selected if key in settled_by_key]
    base = totals(settled)
    prediction_samples = int(base.get("prediction_samples") or 0)
    prediction_hits = int(base.get("prediction_hits") or 0)
    flat_stake = sum(int((row.get("uniform") or {}).get("stake_yen") or 0) for row in settled)
    flat_return = sum(int((row.get("uniform") or {}).get("return_yen") or 0) for row in settled)
    budget_3000_rows = {
        key: settle_equal_3000(selected[key], settled_by_key[key])
        for key in selected if key in settled_by_key
    }
    budget_3000_stake = sum(row["stake_yen"] for row in budget_3000_rows.values())
    budget_3000_return = sum(row["return_yen"] for row in budget_3000_rows.values())
    return {
        "threshold": threshold_label,
        "stability_gate": stability_gate_label,
        "selected_races": len(selected),
        "settled_races": len(settled),
        "prediction_hits": prediction_hits,
        "prediction_samples": prediction_samples,
        "prediction_hit_rate": (prediction_hits / prediction_samples * 100) if prediction_samples else None,
        "flat_100_per_pick_stake_yen": flat_stake,
        "flat_100_per_pick_return_yen": flat_return,
        "flat_100_per_pick_profit_yen": flat_return - flat_stake,
        "flat_100_per_pick_roi": (flat_return / flat_stake * 100) if flat_stake else None,
        "budget_3000_per_race_yen": BUDGET_3000_YEN,
        "budget_3000_allocation_rule": "all disclosed picks; as-even-as-possible 100-yen units; remainder follows disclosed pick order",
        "budget_3000_races": len(budget_3000_rows),
        "budget_3000_stake_yen": budget_3000_stake,
        "budget_3000_return_yen": budget_3000_return,
        "budget_3000_profit_yen": budget_3000_return - budget_3000_stake,
        "budget_3000_roi": (budget_3000_return / budget_3000_stake * 100) if budget_3000_stake else None,
        "virtual_hits": base.get("virtual_hits"),
        "virtual_hit_samples": base.get("virtual_hit_samples"),
        "virtual_hit_rate": base.get("hit_rate"),
        "stake_yen": base.get("settled_stake_yen"),
        "return_yen": base.get("return_yen"),
        "profit_yen": base.get("profit_yen"),
        "roi": base.get("roi"),
        "races": [
            {
                "jcd": str(row.get("jcd")).zfill(2),
                "venue": row.get("venue"),
                "rno": int(row.get("rno", 0)),
                "selection_score": int(row.get("selection_score") or 0),
                "grade": row.get("grade"),
                "selection_score_version": row.get("selection_score_version"),
                "prediction_hit": settled_by_key.get(key, {}).get("prediction_hit"),
                "virtual_hit": settled_by_key.get(key, {}).get("virtual_hit"),
                "stake_yen": settled_by_key.get(key, {}).get("stake_yen"),
                "return_yen": settled_by_key.get(key, {}).get("return_yen"),
                "flat_stake_yen": (settled_by_key.get(key, {}).get("uniform") or {}).get("stake_yen"),
                "flat_return_yen": (settled_by_key.get(key, {}).get("uniform") or {}).get("return_yen"),
                "budget_3000": budget_3000_rows.get(key),
            }
            for key, row in sorted(selected.items())
        ],
    }


def subset_summary(
    records: dict[str, dict],
    settled_by_key: dict[str, dict],
    threshold: int,
    require_stability: bool = True,
) -> dict:
    selected = {
        key: row for key, row in records.items()
        if selected_record(row, threshold, require_stability=require_stability)
    }
    settled = [settled_by_key[key] for key in selected if key in settled_by_key]
    base = totals(settled)
    prediction_samples = int(base.get("prediction_samples") or 0)
    prediction_hits = int(base.get("prediction_hits") or 0)
    flat_stake = sum(int((row.get("uniform") or {}).get("stake_yen") or 0) for row in settled)
    flat_return = sum(int((row.get("uniform") or {}).get("return_yen") or 0) for row in settled)
    budget_3000_rows = {
        key: settle_equal_3000(selected[key], settled_by_key[key])
        for key in selected if key in settled_by_key
    }
    budget_3000_stake = sum(row["stake_yen"] for row in budget_3000_rows.values())
    budget_3000_return = sum(row["return_yen"] for row in budget_3000_rows.values())
    return {
        "threshold": threshold,
        "stability_gate": bool(require_stability),
        "min_exhibition_st_component": 12.0 if require_stability else None,
        "min_ev_component": 13.0 if require_stability else None,
        "selected_races": len(selected),
        "settled_races": len(settled),
        "prediction_hits": prediction_hits,
        "prediction_samples": prediction_samples,
        "prediction_hit_rate": (prediction_hits / prediction_samples * 100) if prediction_samples else None,
        "flat_100_per_pick_stake_yen": flat_stake,
        "flat_100_per_pick_return_yen": flat_return,
        "flat_100_per_pick_profit_yen": flat_return - flat_stake,
        "flat_100_per_pick_roi": (flat_return / flat_stake * 100) if flat_stake else None,
        "budget_3000_per_race_yen": BUDGET_3000_YEN,
        "budget_3000_allocation_rule": "all disclosed picks; as-even-as-possible 100-yen units; remainder follows disclosed pick order",
        "budget_3000_races": len(budget_3000_rows),
        "budget_3000_stake_yen": budget_3000_stake,
        "budget_3000_return_yen": budget_3000_return,
        "budget_3000_profit_yen": budget_3000_return - budget_3000_stake,
        "budget_3000_roi": (budget_3000_return / budget_3000_stake * 100) if budget_3000_stake else None,
        "virtual_hits": base.get("virtual_hits"),
        "virtual_hit_samples": base.get("virtual_hit_samples"),
        "virtual_hit_rate": base.get("hit_rate"),
        "stake_yen": base.get("settled_stake_yen"),
        "return_yen": base.get("return_yen"),
        "profit_yen": base.get("profit_yen"),
        "roi": base.get("roi"),
        "races": [
            {
                "jcd": str(row.get("jcd")).zfill(2),
                "venue": row.get("venue"),
                "rno": int(row.get("rno", 0)),
                "selection_score": int(row.get("selection_score") or 0),
                "grade": row.get("grade"),
                "prediction_hit": settled_by_key.get(key, {}).get("prediction_hit"),
                "virtual_hit": settled_by_key.get(key, {}).get("virtual_hit"),
                "stake_yen": settled_by_key.get(key, {}).get("stake_yen"),
                "return_yen": settled_by_key.get(key, {}).get("return_yen"),
                "flat_stake_yen": (settled_by_key.get(key, {}).get("uniform") or {}).get("stake_yen"),
                "flat_return_yen": (settled_by_key.get(key, {}).get("uniform") or {}).get("return_yen"),
                "budget_3000": budget_3000_rows.get(key),
            }
            for key, row in sorted(selected.items())
        ],
    }


def build(day: str) -> dict:
    report_path = REPORT_DIR / f"{day}.json"
    if not report_path.exists():
        raise FileNotFoundError(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    predictions = read_jsonl(PREDICTION_LOG)
    latest, _ = latest_predictions(predictions, day)
    settled_by_key = {
        f"{str(row['jcd']).zfill(2)}:{int(row['rno'])}": row
        for row in report.get("races", [])
    }
    result = {
        "day": day,
        "definition": "final + exhibition complete + score threshold + stability gate + virtual_status=bet",
        "candidate_selected_75": subset_summary(
            latest, settled_by_key, 75, require_stability=False
        ),
        "selected": subset_summary_predicate(
            latest,
            settled_by_key,
            delivered_selected_record,
            threshold_label="delivery-time rule",
            stability_gate_label="version-aware",
        ),
        "stability_selected": subset_summary(
            latest, settled_by_key, SELECTED_THRESHOLD, require_stability=True
        ),
        "strong_selected": subset_summary(
            latest, settled_by_key, STRONG_SELECTED_THRESHOLD, require_stability=True
        ),
        "generated_at": datetime.now(JST).isoformat(),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"{day}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def default_day() -> str:
    now = datetime.now(JST)
    if now.hour < 6:
        now -= timedelta(days=1)
    return now.strftime("%Y%m%d")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", default=default_day())
    args = parser.parse_args()
    build(args.day)
