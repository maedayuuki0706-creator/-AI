"""Pre-deadline 4-venue research capture; no Discord/X/Sheets side effects.

Uses existing official parsers without calling production prediction/delivery
entrypoints. Persists an immutable JSON input and forecast. GitHub remote
persistence must be independently confirmed by the workflow after a push.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from research.scenario_v2.collector import save_immutable
from .engine import VENUES, analyze, digest

JST = ZoneInfo("Asia/Tokyo")
EARLIEST_LEAD = 6 * 60
LATEST_LEAD = 28 * 60


def now_jst():
    return datetime.now(JST)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def race_id(day, code, rno):
    return f"{day}_{code}_{int(rno):02}"


def _deadline(day, hhmm):
    return datetime.strptime(f"{day} {hhmm}", "%Y%m%d %H:%M").replace(tzinfo=JST)


def collect_race(day, jcd, rno, hhmm, root, *, official=None, tide_source=None,
                 venue_stats=None, motors=None, clock=None):
    clock = clock or now_jst
    official = official or __import__("direct_discord_notify")
    deadline = _deadline(day, hhmm)
    key = race_id(day, jcd, rno)
    paths = Path(root)
    input_path = paths / "inputs" / day / f"{key}.json"
    path = paths / "forecasts" / day / f"{key}.json"
    if clock().date() != deadline.date() or (deadline-clock()).total_seconds() < 180:
        raise ValueError("Not enough time to produce a genuine pre-race forecast")
    if path.exists():
        obj = _read_json(path)
        if obj.get("race_id") != key or obj.get("digest") != digest({k: v for k,v in obj.items() if k != "digest"}):
            raise ValueError("Existing immutable forecast corrupt or mismatched")
        return {"race_id": key, "status": "already_frozen"}
    boats = official.parse_racelist_boats(day, jcd, rno)
    if len(boats) != 6 or {int(b["lane"]) for b in boats} != set(range(1, 7)):
        raise ValueError("Six valid official entrants are mandatory")
    url = official.official_url("beforeinfo", day, jcd, rno)
    html = official.fetch(url)
    preview = official.parse_beforeinfo(html)
    if preview.get("exhibition_count") != 6 or not preview.get("entry_observed"):
        raise ValueError("Awaiting complete six-boat exhibition and entry")
    v = preview.get("boats") or {}
    if set(v) != set(range(1, 7)):
        raise ValueError("Official exhibition incomplete")
    observed = clock()
    if deadline - observed < timedelta(minutes=3):
        raise ValueError("Official input too late")
    rows = []
    for row in boats:
        lane = int(row["lane"])
        ex = v[lane]
        if ex.get("predicted_course") is None or ex.get("exhibition_time") is None:
            raise ValueError("Missing observed course/exhibition time")
        rows.append({
            "lane": lane, "course": int(ex["predicted_course"]),
            "racer_id": str(row["racer_id"]), "name": row.get("name"),
            "avg_st": row.get("avg_st"), "motor_top2_rate": row.get("motor_top2_rate"),
            "motor_number": row.get("motor_number"),
            "exhibition_time": ex.get("exhibition_time"), "exhibition_st": ex.get("exhibition_st_timing"),
            "tilt": ex.get("tilt"), "parts_exchange": ex.get("parts_exchange"),
        })
    tide = None
    if VENUES[jcd]["tide_enabled"]:
        try:
            if tide_source is None:
                import tide_context as tide_source
            tide = tide_source.get_tide_context(day, jcd, hhmm)
        except Exception:
            tide = {"available": False, "status": "tide_fetch_error"}
    snapshot = {
        "meta": {"day": day, "jcd": jcd, "rno": int(rno), "deadline": hhmm,
                 "captured_at": observed.isoformat()},
        "boats": rows,
        "source": {"provider": "BOAT RACE official", "beforeinfo_url": url,
                   "beforeinfo_sha256": sha256(html.encode("utf-8")).hexdigest(),
                   "venue_priors_snapshot_digest": digest(venue_stats or {}),
                   "motor_snapshot_digest": digest(motors or {}),
                   "research_code_sha": os.getenv("VENUE_SPECIALIST_CODE_SHA")},
        "environment": {"wind_speed": preview.get("wind_speed"),
                        "wave_cm": preview.get("wave_cm"),
                        "air_temp_c": preview.get("air_temp_c"),
                        "water_temp_c": preview.get("water_temp_c"),
                        # This parser does not reliably extract direction; missing is explicit.
                        "wind_direction": preview.get("wind_direction"),
                        "tide": tide},
    }
    forecast = analyze(snapshot, venues_db=venue_stats, motor_db=motors,
                       mode="live", now=clock().isoformat())
    # Input and forecast write-once. A partial write must be reported, not
    # fabricated as a successful prediction.
    save_immutable(input_path, snapshot)
    if deadline - clock() < timedelta(minutes=3):
        raise ValueError("Analysis completed too late; retain partial input for audit")
    save_immutable(path, forecast)
    return {"race_id": key, "status": "locally_frozen_uncheckpointed",
            "digest": forecast["digest"], "selected_picks": len(forecast["virtual_card"])}


def schedule(day, *, official, clock):
    """Only selected research venues, after their first days, with safe lead time."""
    available = [code for code, v in VENUES.items() if day >= v["first_day"]]
    future = []
    errors = []
    for code in available:
        try:
            deadlines = official.deadlines(day, code)
        except Exception as exc:
            errors.append({"venue": code, "type": type(exc).__name__})
            continue
        for rno, hhmm in enumerate(deadlines[:12], start=1):
            lead = (_deadline(day, hhmm) - clock()).total_seconds()
            if EARLIEST_LEAD <= lead <= LATEST_LEAD:
                future.append((day, code, rno, hhmm))
    return sorted(future, key=lambda r: (r[3], r[1], r[2])), errors


def run(root, *, clock=None, official=None, max_workers=4):
    clock = clock or now_jst
    if official is None:
        import direct_discord_notify as official
    start = clock()
    day = start.strftime("%Y%m%d")
    venue_db = _read_json("data/sheet_db/venues.json")
    motor_db = _read_json("data/sheet_db/motors.json")
    due, errors = schedule(day, official=official, clock=clock)
    output = []
    def attempt(args):
        try:
            return collect_race(*args, root, clock=clock, official=official,
                                venue_stats=venue_db, motors=motor_db)
        except Exception as exc:
            return {"race_id": race_id(args[0], args[1], args[2]), "status": "missing",
                    "error_type": type(exc).__name__, "reason": str(exc)[:200]}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(attempt, args) for args in due]
        for future in as_completed(futures):
            output.append(future.result())
    output.sort(key=lambda item: item["race_id"])
    # Audit ALL elapsed scheduled races, including those missed by every tick.
    missed = []
    for code, profile in VENUES.items():
        if day < profile["first_day"]:
            continue
        try:
            deadlines = official.deadlines(day, code)
        except Exception:
            continue  # A schedule retrieval error was already recorded above.
        for rno, hhmm in enumerate(deadlines[:12], start=1):
            cutoff = _deadline(day, hhmm)
            if (cutoff-clock()).total_seconds() >= 180:
                continue
            key = race_id(day, code, rno)
            target = Path(root) / "forecasts" / day / (key + ".json")
            if not target.is_file():
                missed.append({"race_id": key, "deadline": hhmm,
                               "status": "no_frozen_forecast_before_deadline"})
            else:
                receipt = Path(root) / "receipts" / day / (key + ".json")
                if not receipt.is_file():
                    missed.append({"race_id": key, "deadline": hhmm,
                                   "status": "remote_checkpoint_pending_or_missing"})
    report = {"version": "venue-specialist-collector-v1", "research_only": True,
              "day": day, "started_at": start.isoformat(), "finished_at": clock().isoformat(),
              "active_venues": {k: v["name"] for k,v in VENUES.items()
                                if day >= v["first_day"]},
              "due": len(due), "capture_results": output,
              "schedule_errors": errors, "forecast_count": sum(
                  x["status"] in ("already_frozen", "locally_frozen_uncheckpointed") for x in output),
              "missing_count": sum(x["status"] == "missing" for x in output),
              "elapsed_races_without_confirmed_forecast": missed}
    coverage = Path(root) / "coverage" / day / (
        start.strftime("%H%M%S") + "_" + str(os.getenv("GITHUB_RUN_ID") or "manual") + ".json")
    save_immutable(coverage, report)
    return report


def verify_commit(root, commit_sha, *, git_show, confirmed_at=None):
    """Second-stage durable check. Only after successful remote push.

    git_show should read SHA:path from the *pushed tree*. A timestamp recorded
    AFTER push completion avoids a false predeadline receipt.
    """
    root = Path(root)
    saved_at = confirmed_at or now_jst()
    confirmed = []
    for path in sorted((root / "forecasts").glob("*/*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("digest") != digest({k:v for k,v in record.items() if k!="digest"}):
            raise ValueError("Frozen local digest mismatch")
        remote_path = "data/venue_specialists_v1/" + str(path.relative_to(root)).replace(os.sep,"/")
        remote = json.loads(git_show(commit_sha, remote_path))
        if remote != record:
            raise ValueError("Remote Git object mismatch")
        receipt_path = root / "receipts" / record["race_id"][:8] / (record["race_id"] + ".json")
        if receipt_path.exists():
            previous = _read_json(receipt_path)
            if previous.get("race_id") != record["race_id"] or previous.get("digest") != record["digest"]:
                raise ValueError("Existing receipt identity/digest mismatch")
            confirmed.append(previous)
            continue
        deadline = datetime.fromisoformat(record["deadline_at"])
        valid = saved_at < deadline
        receipt = {"race_id": record["race_id"], "digest": record["digest"],
                   "commit_sha": commit_sha, "checked_at": saved_at.isoformat(),
                   "status": "confirmed_before_deadline" if valid else "late_remote_save_excluded"}
        save_immutable(receipt_path, receipt)
        confirmed.append(receipt)
    return confirmed


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default="data/venue_specialists_v1")
    p.add_argument("--verify-commit", default="")
    x = p.parse_args()
    if x.verify_commit:
        import subprocess
        from pathlib import Path
        def show(sha, path):
            return subprocess.check_output(["git", "show", f"{sha}:{path}"], text=True)
        result = verify_commit(x.out, x.verify_commit, git_show=show)
    else:
        result = run(x.out)
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
