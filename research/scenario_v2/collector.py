"""Standalone research-only pre-race freeze, with zero delivery or sheet writes."""
from __future__ import annotations
from datetime import datetime, timedelta
from hashlib import sha256
import argparse
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from . import engine
from .run import write_once

JST = ZoneInfo("Asia/Tokyo")
LEAD = timedelta(minutes=3)


def save_immutable(path, record):
    path = Path(path)
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != record:
            raise ValueError("Frozen data conflict; refusing to overwrite")
        return False
    try:
        write_once(path, record)
        return True
    except FileExistsError:
        if json.loads(path.read_text(encoding="utf-8")) != record:
            raise ValueError("Concurrent frozen data conflict")
        return False


def _source_input(day, jcd, rno, deadline, boats, preview, captured, evidence):
    if len(boats) != 6 or not preview.get("entry_observed") or preview.get("exhibition_count") != 6:
        raise ValueError("All six exhibition records and observed entry required")
    if set(preview.get("boats") or {}) != set(range(1, 7)):
        raise ValueError("Exhibition incomplete")
    rows = []
    for b in boats:
        lane = int(b["lane"])
        v = preview["boats"][lane]
        if v.get("exhibition_time") is None or v.get("predicted_course") is None:
            raise ValueError("Exhibition time or course missing")
        rows.append({"lane": lane, "course": v["predicted_course"],
                     "racer_id": str(b["racer_id"]), "name": b.get("name"),
                     "avg_st": b.get("avg_st"), "exhibition_st": v.get("exhibition_st_timing"),
                     "motor_top2_rate": b.get("motor_top2_rate"),
                     "motor_number": b.get("motor_number"), "exhibition_time": v["exhibition_time"],
                     "tilt": v.get("tilt")})
    return {"meta": {"day": day, "jcd": str(jcd).zfill(2), "rno": int(rno),
                     "deadline": deadline, "captured_at": captured.isoformat()},
            "boats": rows, "source": evidence,
            "environment": {"wind_speed": preview.get("wind_speed"),
                            "wave_cm": preview.get("wave_cm")}}


def collect_once(day, jcd, rno, deadline, out, *, clock=None, source=None):
    clock = clock or (lambda: datetime.now(JST))
    race_id = f"{day}_{int(jcd):02}_{int(rno):02}"
    finish = datetime.strptime(f"{day} {deadline}", "%Y%m%d %H:%M").replace(tzinfo=JST)
    if clock().date() != finish.date() or finish - clock() < LEAD:
        raise ValueError("Too late for a prospective capture")
    base = Path(out)
    frozen = base / "forecasts" / day / f"{race_id}.json"
    if frozen.exists():
        current = json.loads(frozen.read_text(encoding="utf-8"))
        engine.verify(current)
        if current["meta"]["race_id"] != race_id:
            raise ValueError("Race identity mismatch")
        return {"race_id": race_id, "status": "already_frozen"}
    if source is None:
        import direct_discord_notify as source
    jcd = str(jcd).zfill(2)
    boats = source.parse_racelist_boats(day, jcd, int(rno))
    url = source.official_url("beforeinfo", day, jcd, int(rno))
    html = source.fetch(url)
    preview = source.parse_beforeinfo(html)
    captured = clock()
    if finish - captured < LEAD:
        raise ValueError("Official data arrived too late; no retroactive freeze")
    payload = _source_input(day, jcd, rno, deadline, boats, preview, captured,
                            {"provider": "BOAT RACE official", "url": url,
                             "beforeinfo_sha256": sha256(html.encode()).hexdigest()})
    result = engine.generate(payload, mode="live", now=clock().isoformat())
    save_immutable(base / "inputs" / day / f"{race_id}.json", payload)
    if finish - clock() < LEAD:
        raise ValueError("Forecast timed out; do not claim pre-deadline prediction")
    save_immutable(frozen, result)
    return {"race_id": race_id, "status": "locally_frozen_uncheckpointed",
            "digest": result["digest"]}


def verify_remote_receipt(root, race_id, commit_sha, committed_at, read_remote):
    """Confirm immutable Git persistence; a local file alone is not sufficient."""
    if not isinstance(commit_sha, str) or len(commit_sha) != 40:
        raise ValueError("Missing full commit SHA")
    day = race_id[:8]
    root = Path(root)
    frozen = root / "forecasts" / day / f"{race_id}.json"
    original = json.loads(frozen.read_text(encoding="utf-8"))
    engine.verify(original)
    if original["meta"]["race_id"] != race_id:
        raise ValueError("Race mismatch")
    path = f"data/yuuki_v2_log/forecasts/{day}/{race_id}.json"
    remote = json.loads(read_remote(commit_sha, path))
    if remote != original:
        raise ValueError("Remote record differs from frozen one")
    deadline = engine.aware(original["meta"]["deadline_at"])
    saved = engine.aware(committed_at)
    receipt = {"race_id": race_id, "digest": original["digest"],
               "commit_sha": commit_sha, "committed_at": saved.isoformat(),
               "status": "confirmed_before_deadline" if saved < deadline else "late_checkpoint_excluded"}
    save_immutable(root / "receipts" / day / f"{race_id}.json", receipt)
    return receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--day", required=True)
    p.add_argument("--jcd", required=True)
    p.add_argument("--rno", required=True, type=int)
    p.add_argument("--deadline", required=True)
    p.add_argument("--out", required=True)
    x = p.parse_args()
    result = collect_once(x.day, x.jcd, x.rno, x.deadline, x.out)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
