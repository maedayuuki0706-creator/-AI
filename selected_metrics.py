"""Build exact daily metrics for the dedicated 厳選 prediction stream."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path

from direct_discord_notify import JST
from daily_report import latest_predictions, read_jsonl, totals

PREDICTION_LOG = Path("data/prediction_log.jsonl")
REPORT_DIR = Path("data/daily_reports")
OUTPUT_DIR = Path("data/selected_metrics")


def selected_record(row: dict, threshold: int = 75) -> bool:
    return (
        row.get("phase") == "final"
        and bool(row.get("exhibition"))
        and int(row.get("selection_score") or 0) >= threshold
        and row.get("virtual_status") == "bet"
    )


def subset_summary(records: dict[str, dict], settled_by_key: dict[str, dict], threshold: int) -> dict:
    selected = {
        key: row for key, row in records.items()
        if selected_record(row, threshold)
    }
    settled = [settled_by_key[key] for key in selected if key in settled_by_key]
    base = totals(settled)
    prediction_samples = int(base.get("prediction_samples") or 0)
    prediction_hits = int(base.get("prediction_hits") or 0)
    return {
        "threshold": threshold,
        "selected_races": len(selected),
        "settled_races": len(settled),
        "prediction_hits": prediction_hits,
        "prediction_samples": prediction_samples,
        "prediction_hit_rate": (prediction_hits / prediction_samples * 100) if prediction_samples else None,
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
        "definition": "final + exhibition complete + selection_score threshold + virtual_status=bet",
        "selected": subset_summary(latest, settled_by_key, 75),
        "strong_selected": subset_summary(latest, settled_by_key, 85),
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
