"""Learn persistent racer/course/winning-pattern profiles from official results."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import direct_discord_notify as base
from race_context import parse_result
import racer_profiles

JST = ZoneInfo("Asia/Tokyo")
PROFILE_PATH = Path("data/racer_profiles.json")
DEFAULT_BACKFILL_FLOOR = "20200101"
MAX_RECENT_RACE_KEYS = 50000
FETCH_WORKERS = 8


def _parse_day(day: str) -> datetime:
    return datetime.strptime(day, "%Y%m%d")


def _day_before(day: str) -> str:
    return (_parse_day(day) - timedelta(days=1)).strftime("%Y%m%d")


def _observation_weight(day: str, anchor_day: str) -> float:
    """Keep old history, but make recent behavior count more in live scoring."""
    age = max(0, (_parse_day(anchor_day) - _parse_day(day)).days)
    if age <= 180:
        return 1.0
    if age <= 365:
        return 0.85
    if age <= 730:
        return 0.65
    if age <= 1095:
        return 0.48
    return 0.35


def _counter_bucket(mapping: dict, key: object) -> dict:
    key = str(key)
    return mapping.setdefault(key, {
        "starts": 0, "wins": 0, "top2": 0, "top3": 0,
        "weighted_starts": 0.0, "weighted_wins": 0.0,
        "weighted_top2": 0.0, "weighted_top3": 0.0,
        "st_sum": 0.0, "st_samples": 0, "avg_st": None,
        "win_methods": {},
    })


def _observe_bucket(
    row: dict,
    finish: int | None,
    *,
    weight: float,
    st: float | None = None,
    method: str | None = None,
) -> None:
    row["starts"] = int(row.get("starts") or 0) + 1
    row["weighted_starts"] = round(float(row.get("weighted_starts") or 0.0) + weight, 6)

    if finish == 1:
        row["wins"] = int(row.get("wins") or 0) + 1
        row["weighted_wins"] = round(float(row.get("weighted_wins") or 0.0) + weight, 6)
        if method:
            methods = row.setdefault("win_methods", {})
            methods[method] = int(methods.get(method) or 0) + 1

    if isinstance(finish, int) and finish <= 2:
        row["top2"] = int(row.get("top2") or 0) + 1
        row["weighted_top2"] = round(float(row.get("weighted_top2") or 0.0) + weight, 6)
    if isinstance(finish, int) and finish <= 3:
        row["top3"] = int(row.get("top3") or 0) + 1
        row["weighted_top3"] = round(float(row.get("weighted_top3") or 0.0) + weight, 6)

    if isinstance(st, (int, float)) and 0 <= float(st) <= 1:
        row["st_sum"] = round(float(row.get("st_sum") or 0.0) + float(st), 6)
        row["st_samples"] = int(row.get("st_samples") or 0) + 1
        row["avg_st"] = round(row["st_sum"] / row["st_samples"], 4)


def _observe_start_correction_bucket(
    row: dict,
    *,
    exhibition_timing: float,
    actual_st: float,
    finish: int | None,
    method: str | None,
) -> None:
    """Learn how a racer changes timing from exhibition to the actual start.

    correction = exhibition timing - actual ST.
    Positive values mean the racer moved the actual start earlier
    (e.g. exhibition .22 -> actual .10 => +.12).
    """
    ex = float(exhibition_timing)
    actual = float(actual_st)
    correction = ex - actual

    row["samples"] = int(row.get("samples") or 0) + 1
    row["correction_sum"] = round(float(row.get("correction_sum") or 0.0) + correction, 6)
    row["avg_correction"] = round(row["correction_sum"] / row["samples"], 4)
    row["actual_st_sum"] = round(float(row.get("actual_st_sum") or 0.0) + actual, 6)
    row["avg_actual_st"] = round(row["actual_st_sum"] / row["samples"], 4)

    if ex >= 0.18:
        row["late_samples"] = int(row.get("late_samples") or 0) + 1
        row["late_correction_sum"] = round(
            float(row.get("late_correction_sum") or 0.0) + correction, 6
        )
        row["late_avg_correction"] = round(
            row["late_correction_sum"] / row["late_samples"], 4
        )
        if actual <= 0.12:
            row["late_to_fast"] = int(row.get("late_to_fast") or 0) + 1
        if actual <= 0.10:
            row["late_to_zero"] = int(row.get("late_to_zero") or 0) + 1
        if finish == 1 and method == "まくり":
            row["late_makuri_wins"] = int(row.get("late_makuri_wins") or 0) + 1
        if finish == 1 and method == "まくり差し":
            row["late_makurisashi_wins"] = int(row.get("late_makurisashi_wins") or 0) + 1

    if ex < 0:
        row["exhibition_f_samples"] = int(row.get("exhibition_f_samples") or 0) + 1
        retreat = actual - ex
        row["exhibition_f_retreat_sum"] = round(
            float(row.get("exhibition_f_retreat_sum") or 0.0) + retreat, 6
        )
        row["exhibition_f_avg_retreat"] = round(
            row["exhibition_f_retreat_sum"] / row["exhibition_f_samples"], 4
        )


def update_start_correction_from_result(state: dict, result: dict) -> int:
    racers = state.setdefault("racers", {})
    method = result.get("method")
    learned = 0
    for item in result.get("finish") or []:
        ex = item.get("exhibition_st_timing")
        actual = item.get("st")
        if not isinstance(ex, (int, float)) or not isinstance(actual, (int, float)):
            continue
        if not (-0.5 <= float(ex) <= 1.0 and 0 <= float(actual) <= 1.0):
            continue

        rid = str(item.get("racer_id") or "")
        if not rid:
            continue
        racer = racers.setdefault(rid, _new_racer(rid, item.get("name")))
        finish = item.get("finish") if item.get("status") == "finished" else None
        _observe_start_correction_bucket(
            racer.setdefault("start_correction", {}),
            exhibition_timing=float(ex),
            actual_st=float(actual),
            finish=finish,
            method=method,
        )
        course = int(item.get("course") or item.get("lane") or 0)
        if 1 <= course <= 6:
            bucket = racer.setdefault("start_correction_courses", {}).setdefault(str(course), {})
            _observe_start_correction_bucket(
                bucket,
                exhibition_timing=float(ex),
                actual_st=float(actual),
                finish=finish,
                method=method,
            )
        learned += 1
    return learned


def _new_racer(rid: str, name: str | None) -> dict:
    return {
        "racer_id": rid,
        "name": name,
        "starts": 0,
        "wins": 0,
        "top2": 0,
        "top3": 0,
        "weighted_starts": 0.0,
        "weighted_wins": 0.0,
        "weighted_top2": 0.0,
        "weighted_top3": 0.0,
        "st_sum": 0.0,
        "st_samples": 0,
        "avg_st": None,
        "lanes": {},
        "courses": {},
        "venues": {},
        "years": {},
        "win_methods": {},
        "course_win_methods": {},
        "first_seen": None,
        "last_seen": None,
    }


def update_from_result(state: dict, result: dict) -> None:
    racers = state.setdefault("racers", {})
    jcd = str(result.get("jcd") or "").zfill(2)
    method = result.get("method")
    day = str(result.get("day") or "")
    year = day[:4] if len(day) >= 4 else "unknown"
    anchor_day = str(state.get("weight_anchor_day") or day or datetime.now(JST).strftime("%Y%m%d"))
    weight = _observation_weight(day, anchor_day) if len(day) == 8 else 1.0

    for item in result.get("finish") or []:
        rid = str(item.get("racer_id") or "")
        if not rid:
            continue
        finish = item.get("finish") if item.get("status") == "finished" else None
        racer = racers.setdefault(rid, _new_racer(rid, item.get("name")))
        if item.get("name"):
            racer["name"] = item["name"]

        racer["starts"] = int(racer.get("starts") or 0) + 1
        racer["weighted_starts"] = round(float(racer.get("weighted_starts") or 0.0) + weight, 6)
        if finish == 1:
            racer["wins"] = int(racer.get("wins") or 0) + 1
            racer["weighted_wins"] = round(float(racer.get("weighted_wins") or 0.0) + weight, 6)
        if isinstance(finish, int) and finish <= 2:
            racer["top2"] = int(racer.get("top2") or 0) + 1
            racer["weighted_top2"] = round(float(racer.get("weighted_top2") or 0.0) + weight, 6)
        if isinstance(finish, int) and finish <= 3:
            racer["top3"] = int(racer.get("top3") or 0) + 1
            racer["weighted_top3"] = round(float(racer.get("weighted_top3") or 0.0) + weight, 6)

        lane = int(item.get("lane") or 0)
        course = int(item.get("course") or lane or 0)
        st = item.get("st")
        if 1 <= lane <= 6:
            _observe_bucket(
                _counter_bucket(racer.setdefault("lanes", {}), lane),
                finish, weight=weight, st=st, method=method,
            )
        if 1 <= course <= 6:
            _observe_bucket(
                _counter_bucket(racer.setdefault("courses", {}), course),
                finish, weight=weight, st=st, method=method,
            )
        if jcd and jcd != "00":
            _observe_bucket(
                _counter_bucket(racer.setdefault("venues", {}), jcd),
                finish, weight=weight, st=st, method=method,
            )
        _observe_bucket(
            _counter_bucket(racer.setdefault("years", {}), year),
            finish, weight=1.0, st=st, method=method,
        )

        if isinstance(st, (int, float)) and 0 <= float(st) <= 1:
            racer["st_sum"] = round(float(racer.get("st_sum") or 0.0) + float(st), 6)
            racer["st_samples"] = int(racer.get("st_samples") or 0) + 1
            racer["avg_st"] = round(racer["st_sum"] / racer["st_samples"], 4)

        if finish == 1 and method:
            methods = racer.setdefault("win_methods", {})
            methods[method] = int(methods.get(method) or 0) + 1
            if 1 <= course <= 6:
                course_methods = racer.setdefault("course_win_methods", {}).setdefault(str(course), {})
                course_methods[method] = int(course_methods.get(method) or 0) + 1

        if day:
            if not racer.get("first_seen") or day < racer["first_seen"]:
                racer["first_seen"] = day
            if not racer.get("last_seen") or day > racer["last_seen"]:
                racer["last_seen"] = day


def _load_state(anchor_day: str) -> dict:
    if PROFILE_PATH.exists():
        try:
            state = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    else:
        state = {}
    state.setdefault("version", "racer-profile-v3-start-correction")
    state.setdefault("racers", {})
    state.setdefault("processed_races", [])
    state.setdefault("start_correction_processed_races", [])
    state.setdefault("weight_anchor_day", anchor_day)
    state.setdefault("backfill", {})
    return state


def _save_state(state: dict, *, last_learning_day: str) -> None:
    state["version"] = "racer-profile-v3-start-correction"
    state["updated_at"] = datetime.now(JST).isoformat()
    state["last_learning_day"] = last_learning_day
    # This recent-key guard is enough for overlapping current/retry runs; the
    # monotonic historical cursor prevents old days from being processed twice.
    state["processed_races"] = sorted(set(state.get("processed_races") or []))[-MAX_RECENT_RACE_KEYS:]
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    racer_profiles.clear_cache()


def _fetch_one(day: str, jcd: str, rno: int) -> tuple[str, dict | None]:
    key = f"{day}:{str(jcd).zfill(2)}:{rno}"
    try:
        raw = base.fetch(base.official_url("raceresult", day, jcd, rno))
        result = parse_result(raw, day, str(jcd).zfill(2), rno)
        try:
            preview_raw = base.fetch(base.official_url("beforeinfo", day, jcd, rno))
            preview = base.parse_beforeinfo(preview_raw)
            for item in result.get("finish") or []:
                pre = (preview.get("boats") or {}).get(int(item.get("lane") or 0), {})
                if pre.get("exhibition_st_timing") is not None:
                    item["exhibition_st_timing"] = pre.get("exhibition_st_timing")
                    item["exhibition_flying"] = bool(pre.get("exhibition_flying"))
                    item["exhibition_course"] = pre.get("predicted_course")
        except Exception:
            pass
        return key, result
    except Exception:
        return key, None


def learn_day_into_state(state: dict, day: str) -> dict:
    seen = set(state.get("processed_races") or [])
    try:
        venues = base.discover_venues(day)
    except Exception as exc:
        print(f"racer profile discover failed: day={day} {type(exc).__name__}")
        return {"day": day, "fatal": True, "added": 0, "skipped": 0, "failed": 0, "expected": 0}

    jobs = []
    skipped = 0
    for jcd in venues:
        for rno in range(1, 13):
            key = f"{day}:{str(jcd).zfill(2)}:{rno}"
            if key in seen:
                skipped += 1
            else:
                jobs.append((str(jcd).zfill(2), rno))

    added = 0
    failed = 0
    if jobs:
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            futures = [pool.submit(_fetch_one, day, jcd, rno) for jcd, rno in jobs]
            for future in as_completed(futures):
                key, result = future.result()
                if result is None:
                    failed += 1
                    continue
                update_from_result(state, result)
                correction_learned = update_start_correction_from_result(state, result)
                if correction_learned:
                    correction_seen = set(state.get("start_correction_processed_races") or [])
                    correction_seen.add(key)
                    state["start_correction_processed_races"] = sorted(correction_seen)[-MAX_RECENT_RACE_KEYS:]
                seen.add(key)
                added += 1

    state["processed_races"] = sorted(seen)[-MAX_RECENT_RACE_KEYS:]
    expected = len(venues) * 12
    # Result pages for cancellations/abnormal races may not parse. Only hold
    # the cursor when failures are widespread enough to look like a fetch issue.
    incomplete = bool(jobs) and failed > max(8, int(len(jobs) * 0.30))
    print(
        f"racer profile day={day} venues={len(venues)} added={added} "
        f"skipped={skipped} failed={failed} racers={len(state.get('racers') or {})}"
    )
    return {
        "day": day,
        "fatal": False,
        "incomplete": incomplete,
        "added": added,
        "skipped": skipped,
        "failed": failed,
        "expected": expected,
    }


def learn_start_corrections_day_into_state(state: dict, day: str) -> dict:
    seen = set(state.get("start_correction_processed_races") or [])
    try:
        venues = base.discover_venues(day)
    except Exception as exc:
        print(f"start correction discover failed: day={day} {type(exc).__name__}")
        return {"day": day, "fatal": True, "added": 0, "failed": 0}

    jobs = []
    for jcd in venues:
        for rno in range(1, 13):
            key = f"{day}:{str(jcd).zfill(2)}:{rno}"
            if key not in seen:
                jobs.append((str(jcd).zfill(2), rno))

    added = 0
    failed = 0
    if jobs:
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            futures = [pool.submit(_fetch_one, day, jcd, rno) for jcd, rno in jobs]
            for future in as_completed(futures):
                key, result = future.result()
                if result is None:
                    failed += 1
                    continue
                learned = update_start_correction_from_result(state, result)
                if learned <= 0:
                    failed += 1
                    continue
                seen.add(key)
                added += 1

    state["start_correction_processed_races"] = sorted(seen)[-MAX_RECENT_RACE_KEYS:]
    incomplete = bool(jobs) and failed > max(8, int(len(jobs) * 0.35))
    print(
        f"start correction day={day} venues={len(venues)} added={added} "
        f"failed={failed}"
    )
    return {
        "day": day,
        "fatal": False,
        "incomplete": incomplete,
        "added": added,
        "failed": failed,
    }


def run_start_correction_backfill(
    state: dict, *, recent_day: str, days: int, floor_day: str
) -> dict:
    backfill = state.setdefault("start_correction_backfill", {})
    backfill["floor_day"] = floor_day
    next_day = str(backfill.get("next_day") or _day_before(recent_day))
    processed_days = 0
    added_races = 0

    for _ in range(max(0, int(days))):
        if next_day < floor_day:
            backfill["completed"] = True
            break
        summary = learn_start_corrections_day_into_state(state, next_day)
        if summary.get("fatal") or summary.get("incomplete"):
            break
        processed_days += 1
        added_races += int(summary.get("added") or 0)
        backfill["last_completed_day"] = next_day
        next_day = _day_before(next_day)
        backfill["next_day"] = next_day
        backfill["completed"] = next_day < floor_day

    backfill["days_processed"] = int(backfill.get("days_processed") or 0) + processed_days
    backfill["races_added"] = int(backfill.get("races_added") or 0) + added_races
    backfill["next_day"] = next_day
    return {
        "processed_days": processed_days,
        "added_races": added_races,
        "next_day": next_day,
        "completed": bool(backfill.get("completed")),
        "floor_day": floor_day,
    }


def run_backfill(state: dict, *, recent_day: str, days: int, floor_day: str) -> dict:
    backfill = state.setdefault("backfill", {})
    backfill["floor_day"] = floor_day
    next_day = str(backfill.get("next_day") or _day_before(recent_day))
    processed_days = 0
    added_races = 0

    for _ in range(max(0, int(days))):
        if next_day < floor_day:
            backfill["completed"] = True
            break
        summary = learn_day_into_state(state, next_day)
        if summary.get("fatal") or summary.get("incomplete"):
            # Retry the same historical day next run; successful race keys from
            # this partial pass are retained so they are not double-counted.
            break
        processed_days += 1
        added_races += int(summary.get("added") or 0)
        backfill["last_completed_day"] = next_day
        next_day = _day_before(next_day)
        backfill["next_day"] = next_day
        backfill["completed"] = next_day < floor_day

    backfill["days_processed"] = int(backfill.get("days_processed") or 0) + processed_days
    backfill["races_added"] = int(backfill.get("races_added") or 0) + added_races
    backfill["next_day"] = next_day
    return {
        "processed_days": processed_days,
        "added_races": added_races,
        "next_day": next_day,
        "completed": bool(backfill.get("completed")),
        "floor_day": floor_day,
    }


def learn(day: str, *, backfill_days: int = 0, backfill_floor: str = DEFAULT_BACKFILL_FLOOR) -> dict:
    state = _load_state(day)
    current = learn_day_into_state(state, day)
    start_current = learn_start_corrections_day_into_state(state, day)
    backfill = run_backfill(
        state,
        recent_day=day,
        days=backfill_days,
        floor_day=backfill_floor,
    )
    start_backfill = run_start_correction_backfill(
        state,
        recent_day=day,
        days=backfill_days,
        floor_day=backfill_floor,
    )
    _save_state(state, last_learning_day=day)
    print(
        "racer profile learning complete: "
        f"day={day} current_added={current.get('added', 0)} "
        f"start_current={start_current.get('added', 0)} "
        f"backfill_days={backfill['processed_days']} "
        f"backfill_races={backfill['added_races']} "
        f"start_backfill_days={start_backfill['processed_days']} "
        f"start_backfill_races={start_backfill['added_races']} "
        f"next={backfill['next_day']} start_next={start_backfill['next_day']} "
        f"racers={len(state.get('racers') or {})}"
    )
    return state


def default_day() -> str:
    now = datetime.now(JST)
    if now.hour < 6:
        now -= timedelta(days=1)
    return now.strftime("%Y%m%d")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", default=default_day())
    parser.add_argument("--backfill-days", type=int, default=0)
    parser.add_argument("--backfill-floor", default=DEFAULT_BACKFILL_FLOOR)
    args = parser.parse_args()
    learn(args.day, backfill_days=args.backfill_days, backfill_floor=args.backfill_floor)
