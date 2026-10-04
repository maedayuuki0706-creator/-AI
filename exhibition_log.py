"""Persist complete BOAT RACE exhibition snapshots and settled outcomes."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import csv
import io
import json
import re

import direct_discord_notify as base
import race_context

ROOT = Path("data/exhibition_log")
RECENT_CSV = ROOT / "recent.csv"
RECENT_DAYS = 3

VENUE_MEDIANS = {
    "01": 6.77, "02": 6.77, "03": 6.91, "04": 6.82, "05": 6.78, "06": 6.73,
    "07": 6.74, "08": 6.77, "09": 6.88, "10": 6.80, "11": 6.77, "12": 6.93,
    "13": 6.84, "14": 6.86, "15": 6.82, "16": 6.82, "17": 6.76, "18": 6.99,
    "19": 6.86, "20": 6.95, "21": 6.81, "22": 6.93, "23": 6.80, "24": 6.96,
}

CSV_FIELDS = [
    "日付", "場", "R", "枠", "選手", "展示タイム", "展示順位", "場平均との差",
    "展示ST", "展示ST順位", "展示進入", "本番進入", "チルト", "体重", "調整重量",
    "プロペラ交換", "部品交換", "本番ST", "着順", "決まり手", "風速", "波高",
]

def _race_path(day: str, jcd: str, rno: int) -> Path:
    return ROOT / str(day) / f"{str(jcd).zfill(2)}_{int(rno):02d}.json"

def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}

def _write_json_if_changed(path: Path, value: dict) -> bool:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True

def _rank(values: dict[int, float | None]) -> dict[int, int | None]:
    valid = sorted((float(v), int(lane)) for lane, v in values.items() if v is not None)
    out = {int(lane): None for lane in values}
    for idx, (_, lane) in enumerate(valid, 1):
        out[lane] = idx
    return out

def _deadline(day: str, jcd: str, rno: int) -> str | None:
    try:
        values = base.deadlines(day, jcd)
    except Exception:
        return None
    return values[int(rno) - 1] if len(values) >= int(rno) else None

def _deadline_dt(day: str, hhmm: str | None) -> datetime | None:
    if not hhmm:
        return None
    try:
        value = datetime.strptime(f"{day} {hhmm}", "%Y%m%d %H:%M")
        return value.replace(tzinfo=base.JST)
    except ValueError:
        return None

def _merge_result_fields(new_rows: list[dict], old: dict) -> None:
    old_rows = {
        int(row.get("lane") or 0): row
        for row in (old.get("rows") or [])
        if isinstance(row, dict) and 1 <= int(row.get("lane") or 0) <= 6
    }
    for row in new_rows:
        prior = old_rows.get(int(row["lane"]))
        if not prior:
            continue
        for key in ("actual_course", "actual_st", "finish", "method"):
            if prior.get(key) is not None:
                row[key] = prior[key]

def record_analysis(day: str, jcd: str, rno: int, analysis: dict | None) -> bool:
    if not analysis:
        return False
    day = str(day)
    jcd = str(jcd).zfill(2)
    rno = int(rno)
    preview = analysis.get("preview") or {}
    boats = list(analysis.get("inputs") or [])
    if int(preview.get("exhibition_count") or 0) != 6 or len(boats) != 6:
        return False
    if {int(b.get("lane") or 0) for b in boats} != set(range(1, 7)):
        return False

    median = VENUE_MEDIANS.get(jcd)
    st_values = {
        int(b["lane"]): (
            b.get("exhibition_st_timing")
            if b.get("exhibition_st_timing") is not None
            else b.get("exhibition_st")
        )
        for b in boats
    }
    st_ranks = _rank(st_values)

    rows = []
    for boat in sorted(boats, key=lambda b: int(b["lane"])):
        lane = int(boat["lane"])
        exhibition_time = boat.get("exhibition_time")
        rows.append({
            "day": day, "jcd": jcd, "venue": base.VENUES.get(jcd, jcd),
            "rno": rno, "lane": lane,
            "racer_id": str(boat.get("racer_id") or ""),
            "name": str(boat.get("name") or ""),
            "exhibition_time": exhibition_time,
            "exhibition_rank": boat.get("exhibition_rank"),
            "venue_median_delta": (
                round(float(exhibition_time) - float(median), 3)
                if exhibition_time is not None and median is not None else None
            ),
            "exhibition_st": st_values.get(lane),
            "exhibition_st_rank": st_ranks.get(lane),
            "exhibition_course": boat.get("predicted_course"),
            "actual_course": None,
            "tilt": boat.get("tilt"),
            "weight_kg": boat.get("weight_kg"),
            "adjustment_weight_kg": boat.get("adjustment_weight_kg"),
            "propeller_exchange": boat.get("propeller_exchange"),
            "parts_exchange": boat.get("parts_exchange"),
            "actual_st": None, "finish": None, "method": None,
            "wind_m": preview.get("wind_speed"), "wave_cm": preview.get("wave_cm"),
        })

    path = _race_path(day, jcd, rno)
    old = _read_json(path)
    _merge_result_fields(rows, old)
    payload = {
        "day": day, "jcd": jcd, "venue": base.VENUES.get(jcd, jcd), "rno": rno,
        "deadline": old.get("deadline") or _deadline(day, jcd, rno),
        "captured_at": old.get("captured_at") or datetime.now(base.JST).isoformat(),
        "updated_at": datetime.now(base.JST).isoformat(),
        "settled": bool(old.get("settled")),
        "source": "BOAT RACE official beforeinfo",
        "rows": rows,
    }
    if old.get("settled_at"):
        payload["settled_at"] = old["settled_at"]
    changed = _write_json_if_changed(path, payload)
    if changed:
        rebuild_recent_csv()
    return changed

def _apply_result(payload: dict, result: dict) -> bool:
    by_lane = {
        int(row.get("lane") or 0): row
        for row in (result.get("finish") or [])
        if 1 <= int(row.get("lane") or 0) <= 6
    }
    if len(by_lane) != 6:
        return False
    method = result.get("method")
    changed = False
    for row in payload.get("rows") or []:
        lane = int(row.get("lane") or 0)
        official = by_lane.get(lane)
        if not official:
            continue
        updates = {
            "actual_course": official.get("course"),
            "actual_st": official.get("st"),
            "finish": official.get("finish"),
            "method": method,
        }
        for key, value in updates.items():
            if row.get(key) != value:
                row[key] = value
                changed = True
        if result.get("wind_m") is not None and row.get("wind_m") != result.get("wind_m"):
            row["wind_m"] = result.get("wind_m"); changed = True
        if result.get("wave_cm") is not None and row.get("wave_cm") != result.get("wave_cm"):
            row["wave_cm"] = result.get("wave_cm"); changed = True
    if not payload.get("settled"):
        payload["settled"] = True; changed = True
    if changed:
        payload["settled_at"] = datetime.now(base.JST).isoformat()
        payload["updated_at"] = datetime.now(base.JST).isoformat()
    return changed

def refresh_pending_results(now: datetime | None = None, lookback_days: int = 1) -> int:
    now = now or datetime.now(base.JST)
    changed = 0
    for delta in range(max(0, int(lookback_days)) + 1):
        day = (now - timedelta(days=delta)).strftime("%Y%m%d")
        day_dir = ROOT / day
        if not day_dir.exists():
            continue
        for path in sorted(day_dir.glob("*.json")):
            payload = _read_json(path)
            if not payload or payload.get("settled"):
                continue
            deadline = _deadline_dt(day, payload.get("deadline"))
            if deadline is not None and now < deadline + timedelta(seconds=45):
                continue
            jcd = str(payload.get("jcd") or "").zfill(2)
            rno = int(payload.get("rno") or 0)
            if not re.fullmatch(r"\d{2}", jcd) or not 1 <= rno <= 12:
                continue
            try:
                raw = base.fetch(base.official_url("raceresult", day, jcd, rno))
                result = race_context.parse_result(raw, day, jcd, rno)
            except Exception:
                continue
            if _apply_result(payload, result):
                _write_json_if_changed(path, payload)
                changed += 1
    if changed:
        rebuild_recent_csv()
    return changed

def _st_text(value) -> str:
    if value is None:
        return ""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if value < 0:
        return "F" + f"{abs(value):.2f}"[1:]
    return f"{value:.2f}"

def _date_text(day: str) -> str:
    return f"{day[:4]}/{day[4:6]}/{day[6:8]}" if re.fullmatch(r"\d{8}", day) else day

def _csv_row(row: dict) -> list:
    return [
        _date_text(str(row.get("day") or "")), row.get("venue") or "",
        row.get("rno") or "", row.get("lane") or "", row.get("name") or "",
        row.get("exhibition_time") if row.get("exhibition_time") is not None else "",
        row.get("exhibition_rank") or "",
        row.get("venue_median_delta") if row.get("venue_median_delta") is not None else "",
        _st_text(row.get("exhibition_st")), row.get("exhibition_st_rank") or "",
        row.get("exhibition_course") or "", row.get("actual_course") or "",
        row.get("tilt") if row.get("tilt") is not None else "",
        row.get("weight_kg") if row.get("weight_kg") is not None else "",
        row.get("adjustment_weight_kg") if row.get("adjustment_weight_kg") is not None else "",
        row.get("propeller_exchange") or "", row.get("parts_exchange") or "",
        _st_text(row.get("actual_st")), row.get("finish") or "", row.get("method") or "",
        row.get("wind_m") if row.get("wind_m") is not None else "",
        row.get("wave_cm") if row.get("wave_cm") is not None else "",
    ]

def rebuild_recent_csv(now: datetime | None = None, days: int = RECENT_DAYS) -> bool:
    now = now or datetime.now(base.JST)
    cutoff = (now - timedelta(days=max(1, int(days)) - 1)).strftime("%Y%m%d")
    rows = []
    if ROOT.exists():
        for day_dir in sorted((p for p in ROOT.iterdir() if p.is_dir()), key=lambda p: p.name):
            if not re.fullmatch(r"\d{8}", day_dir.name) or day_dir.name < cutoff:
                continue
            for path in sorted(day_dir.glob("*.json")):
                payload = _read_json(path)
                for row in payload.get("rows") or []:
                    if isinstance(row, dict):
                        rows.append(row)
    rows.sort(key=lambda row: (
        str(row.get("day") or ""), str(row.get("jcd") or ""),
        int(row.get("rno") or 0), int(row.get("lane") or 0),
    ))
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(CSV_FIELDS)
    for row in rows:
        writer.writerow(_csv_row(row))
    text = stream.getvalue()
    try:
        if RECENT_CSV.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    RECENT_CSV.parent.mkdir(parents=True, exist_ok=True)
    RECENT_CSV.write_text(text, encoding="utf-8")
    return True

if __name__ == "__main__":
    count = refresh_pending_results()
    rebuild_recent_csv()
    print(f"exhibition log result updates: {count}", flush=True)
