"""Intraday venue-affinity signal from settled main-prediction results.

This is deliberately conservative: it never creates a selected race by itself.
It only decorates prediction cards once enough races at the same venue have
settled, and may add a tiny confidence bonus to races that already cleared the
75-point selected threshold.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DELIVERY_PATH = Path("data/hit_alert_deliveries.jsonl")
MIN_VISIBLE_SAMPLES = 4
STRONG_MIN_SAMPLES = 6
GOOD_HIT_RATE = 0.50
STRONG_HIT_RATE = 0.60


def _read_rows() -> list[dict]:
    if not DELIVERY_PATH.exists():
        return []
    rows = []
    for line in DELIVERY_PATH.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def venue_form(day: str, venue: str, *, current_rno: int | None = None) -> dict:
    """Return same-day settled main-prediction form for one venue.

    Only earlier races are used when current_rno is supplied, which prevents a
    later/backfilled result from leaking into an earlier prediction.
    """
    latest: dict[str, dict] = {}
    for row in _read_rows():
        if str(row.get("day") or "") != str(day):
            continue
        if str(row.get("venue") or "") != str(venue):
            continue
        if str(row.get("stream") or "normal") != "normal":
            continue
        if row.get("status") not in {"sent", "miss"}:
            continue
        try:
            rno = int(row.get("rno") or 0)
        except (TypeError, ValueError):
            continue
        if rno <= 0 or (current_rno is not None and rno >= int(current_rno)):
            continue
        key = str(row.get("key") or f"{day}:{venue}:{rno}")
        previous = latest.get(key)
        if previous is None or str(row.get("sent_at") or "") >= str(previous.get("sent_at") or ""):
            latest[key] = row

    settled = sorted(latest.values(), key=lambda row: int(row.get("rno") or 0))
    samples = len(settled)
    hits = sum(1 for row in settled if row.get("status") == "sent")
    hit_rate = hits / samples if samples else 0.0

    recent = settled[-3:]
    recent_hits = sum(1 for row in recent if row.get("status") == "sent")
    streak = 0
    for row in reversed(settled):
        if row.get("status") != "sent":
            break
        streak += 1

    level = "none"
    bonus = 0
    label = None
    if samples >= STRONG_MIN_SAMPLES and hit_rate >= STRONG_HIT_RATE:
        level = "strong"
        bonus = 2
        label = f"🔥 今日この水面かなりハマってる｜{hits}/{samples}的中"
    elif samples >= MIN_VISIBLE_SAMPLES and hit_rate >= GOOD_HIT_RATE:
        level = "good"
        bonus = 1
        label = f"👀 今日この水面、見えてるかも｜{hits}/{samples}的中"

    flow = len(recent) == 3 and recent_hits >= 2
    if label and flow:
        label += "｜流れ継続中"
    if label and streak >= 2:
        label += f"｜{streak}連的中中"

    return {
        "day": str(day),
        "venue": str(venue),
        "samples": samples,
        "hits": hits,
        "hit_rate": round(hit_rate, 4),
        "recent_3_hits": recent_hits,
        "current_streak": streak,
        "level": level,
        "score_bonus": bonus,
        "label": label,
    }


def install(app: Any) -> None:
    """Add live water-form context without increasing selected-race volume."""
    original_message = app.analysis_message_with_virtual
    original_log = app.log_prediction_with_virtual
    cache: dict[tuple, dict] = {}

    def message(day, jcd, rno, deadline, phase, analysis, rows, required):
        venue = app.base.VENUES.get(str(jcd), str(jcd))
        form = venue_form(str(day), venue, current_rno=int(rno))
        key = (str(day), str(jcd), int(rno), str(phase))
        cache[key] = form
        analysis["water_affinity"] = form
        text = original_message(day, jcd, rno, deadline, phase, analysis, rows, required)
        if form.get("label"):
            candidate = str(form["label"]) + "\n" + text
            if len(candidate.encode("utf-16-le")) // 2 <= 2000:
                text = candidate
        return text

    def logged(record):
        key = (
            str(record.get("day") or ""),
            str(record.get("jcd") or ""),
            int(record.get("rno") or 0),
            str(record.get("phase") or "final"),
        )
        form = cache.get(key)
        if form is None:
            form = venue_form(
                key[0],
                str(record.get("venue") or ""),
                current_rno=key[2],
            )

        record = dict(record)
        record["water_affinity"] = form
        record["water_affinity_version"] = "intraday-water-v1"

        # Preserve the 75-point entry border exactly: sub-75 races never become
        # selected because of same-day form. The small bonus only expresses extra
        # confidence after a race already qualified on its own fundamentals.
        try:
            score = int(record.get("selection_score"))
        except (TypeError, ValueError):
            score = None
        bonus = int(form.get("score_bonus") or 0)
        if score is not None and score >= 75 and bonus > 0:
            record["selection_score_before_water"] = score
            record["selection_score"] = min(100, score + bonus)
            breakdown = dict(record.get("selection_score_breakdown") or {})
            breakdown["water_affinity"] = bonus
            record["selection_score_breakdown"] = breakdown

        return original_log(record)

    app.analysis_message_with_virtual = message
    app.log_prediction_with_virtual = logged
