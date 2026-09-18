"""Learn persistent racer/course/winning-pattern profiles from official results."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import direct_discord_notify as base
from race_context import parse_result
import racer_profiles

JST = ZoneInfo("Asia/Tokyo")
PROFILE_PATH = Path("data/racer_profiles.json")


def _counter_bucket(mapping: dict, key: object) -> dict:
    key = str(key)
    row = mapping.setdefault(key, {"starts": 0, "wins": 0, "top2": 0, "top3": 0})
    return row


def _observe_bucket(row: dict, finish: int | None) -> None:
    row["starts"] = int(row.get("starts") or 0) + 1
    if finish == 1:
        row["wins"] = int(row.get("wins") or 0) + 1
    if isinstance(finish, int) and finish <= 2:
        row["top2"] = int(row.get("top2") or 0) + 1
    if isinstance(finish, int) and finish <= 3:
        row["top3"] = int(row.get("top3") or 0) + 1


def update_from_result(state: dict, result: dict) -> None:
    racers = state.setdefault("racers", {})
    jcd = str(result.get("jcd") or "").zfill(2)
    method = result.get("method")
    for item in result.get("finish") or []:
        rid = str(item.get("racer_id") or "")
        if not rid:
            continue
        finish = item.get("finish") if item.get("status") == "finished" else None
        racer = racers.setdefault(rid, {
            "racer_id": rid,
            "name": item.get("name"),
            "starts": 0,
            "wins": 0,
            "top2": 0,
            "top3": 0,
            "st_sum": 0.0,
            "st_samples": 0,
            "avg_st": None,
            "lanes": {},
            "courses": {},
            "venues": {},
            "win_methods": {},
            "last_seen": None,
        })
        if item.get("name"):
            racer["name"] = item["name"]
        racer["starts"] = int(racer.get("starts") or 0) + 1
        if finish == 1:
            racer["wins"] = int(racer.get("wins") or 0) + 1
        if isinstance(finish, int) and finish <= 2:
            racer["top2"] = int(racer.get("top2") or 0) + 1
        if isinstance(finish, int) and finish <= 3:
            racer["top3"] = int(racer.get("top3") or 0) + 1

        lane = int(item.get("lane") or 0)
        course = int(item.get("course") or lane or 0)
        if 1 <= lane <= 6:
            _observe_bucket(_counter_bucket(racer.setdefault("lanes", {}), lane), finish)
        if 1 <= course <= 6:
            _observe_bucket(_counter_bucket(racer.setdefault("courses", {}), course), finish)
        if jcd and jcd != "00":
            _observe_bucket(_counter_bucket(racer.setdefault("venues", {}), jcd), finish)

        st = item.get("st")
        if isinstance(st, (int, float)) and 0 <= float(st) <= 1:
            racer["st_sum"] = round(float(racer.get("st_sum") or 0.0) + float(st), 6)
            racer["st_samples"] = int(racer.get("st_samples") or 0) + 1
            racer["avg_st"] = round(racer["st_sum"] / racer["st_samples"], 4)

        if finish == 1 and method:
            methods = racer.setdefault("win_methods", {})
            methods[method] = int(methods.get(method) or 0) + 1
        racer["last_seen"] = result.get("day")


def learn_day(day: str) -> dict:
    if PROFILE_PATH.exists():
        state = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    else:
        state = {"version": "racer-profile-v1", "racers": {}, "processed_races": []}
    seen = set(state.get("processed_races") or [])

    venues = base.discover_venues(day)
    added = 0
    skipped = 0
    for jcd in venues:
        for rno in range(1, 13):
            key = f"{day}:{str(jcd).zfill(2)}:{rno}"
            if key in seen:
                skipped += 1
                continue
            try:
                raw = base.fetch(base.official_url("raceresult", day, jcd, rno))
                result = parse_result(raw, day, str(jcd).zfill(2), rno)
            except Exception:
                continue
            update_from_result(state, result)
            seen.add(key)
            added += 1

    state["processed_races"] = sorted(seen)[-20000:]
    state["version"] = "racer-profile-v1"
    state["updated_at"] = datetime.now(JST).isoformat()
    state["last_learning_day"] = day
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    racer_profiles.clear_cache()
    print(f"racer profile learning: day={day} races_added={added} skipped={skipped} racers={len(state.get('racers') or {})}")
    return state


def default_day() -> str:
    now = datetime.now(JST)
    if now.hour < 6:
        now -= timedelta(days=1)
    return now.strftime("%Y%m%d")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", default=default_day())
    args = parser.parse_args()
    learn_day(args.day)
