"""Collect first-hand motor performance for newly introduced motor cycles.

The official motor 2-ren / 3-ren rates are not useful on the first day of a
new motor cycle.  This collector rebuilds a small, transparent evidence set
from official race cards/results so later analysis can distinguish "unknown"
from "bad" motors without rewriting historical predictions.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import direct_discord_notify as base

JST = ZoneInfo("Asia/Tokyo")
CYCLE_PATH = Path("data/motor_cycles.json")
RESULT_DIR = Path("data/official_results")
OUT_DIR = Path("data/motor_learning")


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def daterange(start: str, end: str):
    cur = datetime.strptime(start, "%Y%m%d").date()
    stop = datetime.strptime(end, "%Y%m%d").date()
    while cur <= stop:
        yield cur.strftime("%Y%m%d")
        cur += timedelta(days=1)


def result_positions(result_row: dict) -> dict[int, int]:
    """Return best observed finishing position (1-3) from official trifecta payouts."""
    positions: dict[int, int] = {}
    if not isinstance(result_row, dict) or result_row.get("status") != "settled":
        return positions
    for combo in (result_row.get("payouts") or {}):
        try:
            lanes = [int(x) for x in str(combo).split("-")]
        except Exception:
            continue
        if len(lanes) != 3 or len(set(lanes)) != 3:
            continue
        for index, lane in enumerate(lanes, 1):
            positions[lane] = min(index, positions.get(lane, 9))
    return positions


def exhibition_ranks(preview: dict) -> dict[int, float]:
    values = {
        int(lane): float(row["exhibition_time"])
        for lane, row in (preview.get("boats") or {}).items()
        if row.get("exhibition_time") is not None
    }
    ranks = {}
    for lane, value in values.items():
        # Dense-enough ranking for learning: ties share the same rank.
        ranks[lane] = 1.0 + sum(1 for other in values.values() if other < value)
    return ranks


def collect_day(day: str, cycle: dict) -> dict | None:
    jcd = str(cycle["jcd"]).zfill(2)
    official = load_json(RESULT_DIR / f"{day}.json", {})
    if not official:
        return None

    motors = defaultdict(lambda: {
        "starts": 0,
        "wins": 0,
        "top2": 0,
        "top3": 0,
        "exhibition_samples": 0,
        "exhibition_time_sum": 0.0,
        "exhibition_rank_sum": 0.0,
        "racer_ids": set(),
        "racer_names": set(),
        "official_top2_rates": set(),
        "official_top3_rates": set(),
        "races": [],
    })
    settled_races = 0
    races_with_motor_data = 0

    for rno in range(1, 13):
        result_row = official.get(f"{jcd}:{rno}") or {}
        positions = result_positions(result_row)
        if not positions:
            continue
        settled_races += 1
        try:
            boats = base.parse_racelist_boats(day, jcd, rno)
        except Exception:
            boats = []
        if len(boats) != 6:
            continue
        races_with_motor_data += 1

        try:
            raw = base.fetch(base.official_url("beforeinfo", day, jcd, rno))
            preview = base.parse_beforeinfo(raw)
        except Exception:
            preview = {"boats": {}}
        ranks = exhibition_ranks(preview)

        for boat in boats:
            motor_number = boat.get("motor_number")
            if motor_number is None:
                continue
            lane = int(boat["lane"])
            key = str(int(motor_number))
            row = motors[key]
            row["starts"] += 1
            finish = positions.get(lane)
            if finish == 1:
                row["wins"] += 1
            if finish is not None and finish <= 2:
                row["top2"] += 1
            if finish is not None and finish <= 3:
                row["top3"] += 1

            racer_id = boat.get("racer_id")
            if racer_id:
                row["racer_ids"].add(str(racer_id))
            if boat.get("name"):
                row["racer_names"].add(str(boat["name"]))
            if boat.get("motor_top2_rate") is not None:
                row["official_top2_rates"].add(float(boat["motor_top2_rate"]))
            if boat.get("motor_top3_rate") is not None:
                row["official_top3_rates"].add(float(boat["motor_top3_rate"]))

            pboat = (preview.get("boats") or {}).get(lane, {})
            if pboat.get("exhibition_time") is not None:
                row["exhibition_samples"] += 1
                row["exhibition_time_sum"] += float(pboat["exhibition_time"])
                row["exhibition_rank_sum"] += float(ranks.get(lane, 0.0))

            row["races"].append({
                "rno": rno,
                "lane": lane,
                "finish_top3": finish,
                "exhibition_time": pboat.get("exhibition_time"),
                "exhibition_rank": ranks.get(lane),
            })

    if not motors:
        return None

    output_motors = {}
    for motor, row in sorted(motors.items(), key=lambda item: int(item[0])):
        starts = row["starts"]
        exn = row["exhibition_samples"]
        output_motors[motor] = {
            "starts": starts,
            "wins": row["wins"],
            "top2": row["top2"],
            "top3": row["top3"],
            "observed_win_rate": round(row["wins"] / starts, 4) if starts else None,
            "observed_top2_rate": round(row["top2"] / starts, 4) if starts else None,
            "observed_top3_rate": round(row["top3"] / starts, 4) if starts else None,
            "avg_exhibition_time": round(row["exhibition_time_sum"] / exn, 3) if exn else None,
            "avg_exhibition_rank": round(row["exhibition_rank_sum"] / exn, 3) if exn else None,
            "racer_ids": sorted(row["racer_ids"]),
            "racer_names": sorted(row["racer_names"]),
            "official_top2_rates_seen": sorted(row["official_top2_rates"]),
            "official_top3_rates_seen": sorted(row["official_top3_rates"]),
            "races": row["races"],
        }

    return {
        "day": day,
        "settled_races": settled_races,
        "races_with_motor_data": races_with_motor_data,
        "motors": output_motors,
    }


def cumulative(days: dict) -> dict:
    acc = defaultdict(lambda: {
        "starts": 0, "wins": 0, "top2": 0, "top3": 0,
        "exhibition_samples": 0, "exhibition_time_sum": 0.0,
        "exhibition_rank_sum": 0.0,
        "racer_names": set(),
    })
    for day_row in days.values():
        for motor, row in (day_row.get("motors") or {}).items():
            dst = acc[motor]
            for field in ("starts", "wins", "top2", "top3"):
                dst[field] += int(row.get(field) or 0)
            exn = sum(1 for race in row.get("races", []) if race.get("exhibition_time") is not None)
            dst["exhibition_samples"] += exn
            dst["exhibition_time_sum"] += sum(float(race["exhibition_time"]) for race in row.get("races", []) if race.get("exhibition_time") is not None)
            dst["exhibition_rank_sum"] += sum(float(race["exhibition_rank"]) for race in row.get("races", []) if race.get("exhibition_rank") is not None)
            dst["racer_names"].update(row.get("racer_names") or [])

    out = {}
    for motor, row in sorted(acc.items(), key=lambda item: int(item[0])):
        starts = row["starts"]
        exn = row["exhibition_samples"]
        # Small-sample shrinkage toward 50% is included as a reference only;
        # live prediction weights are intentionally not changed by this file.
        shrink_n = 4.0
        out[motor] = {
            "starts": starts,
            "wins": row["wins"],
            "top2": row["top2"],
            "top3": row["top3"],
            "observed_win_rate": round(row["wins"] / starts, 4) if starts else None,
            "observed_top2_rate": round(row["top2"] / starts, 4) if starts else None,
            "observed_top3_rate": round(row["top3"] / starts, 4) if starts else None,
            "shrunk_top2_rate": round((row["top2"] + 0.5 * shrink_n) / (starts + shrink_n), 4) if starts else None,
            "shrunk_top3_rate": round((row["top3"] + 0.5 * shrink_n) / (starts + shrink_n), 4) if starts else None,
            "avg_exhibition_time": round(row["exhibition_time_sum"] / exn, 3) if exn else None,
            "avg_exhibition_rank": round(row["exhibition_rank_sum"] / exn, 3) if exn else None,
            "racer_names": sorted(row["racer_names"]),
        }
    return out


def update_cycle(cycle: dict, target_day: str) -> Path | None:
    start = str(cycle["start_date"])
    end = cycle.get("end_date") or target_day
    if target_day < start:
        return None
    end = min(str(end), target_day)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{cycle['cycle_id']}.json"
    existing = load_json(path, {})
    days = dict(existing.get("days") or {})

    for day in daterange(start, end):
        if not (RESULT_DIR / f"{day}.json").exists():
            continue
        row = collect_day(day, cycle)
        if row:
            days[day] = row

    if not days:
        return None

    payload = {
        "cycle_id": cycle["cycle_id"],
        "jcd": str(cycle["jcd"]).zfill(2),
        "venue": cycle["venue"],
        "start_date": start,
        "end_date": cycle.get("end_date"),
        "new_motor": bool(cycle.get("new_motor")),
        "fuel": cycle.get("fuel"),
        "source": cycle.get("source"),
        "note": cycle.get("note"),
        "updated_at": datetime.now(JST).isoformat(),
        "days": dict(sorted(days.items())),
        "cumulative": cumulative(days),
        "guidance": {
            "prediction_use": "record_first",
            "minimum_starts_before_strong_motor_judgment": 6,
            "rule": "Do not over-weight day-1/day-2 motor rates. Use exhibition and observed results as provisional evidence until enough starts accumulate."
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", default=datetime.now(JST).strftime("%Y%m%d"))
    args = parser.parse_args()
    config = load_json(CYCLE_PATH, {"cycles": []})
    written = []
    for cycle in config.get("cycles") or []:
        path = update_cycle(cycle, args.day)
        if path:
            written.append(str(path))
    print("motor learning updated:", ", ".join(written) if written else "no eligible cycle data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
