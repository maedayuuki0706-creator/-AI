"""Dedicated Prototype 3 Discord delivery loop.

Prototype 3 = Hiyori native main line + mid-odds cover built on Hiyori probabilities.
Runs independently from the five-way research workflow so research-test failures
cannot block Discord delivery.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import time
import urllib.request

import direct_discord_notify as base
import detailed_discord_notify as cards
import four_way_prototype as trial
import hiyori_model
import hiyori_source

ROOT = Path("data/prototype3_delivery")
WEBHOOK_ENV = "PROTO3_DISCORD_WEBHOOK_URL"


def now_jst():
    return datetime.now(base.JST)


def key_for(day, jcd, rno):
    return trial.identity(day, jcd, rno)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def post_webhook(url, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": base.UA},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"Discord HTTP {response.status}")


def message(record):
    model = record["model"]
    main = " / ".join(model.get("main_picks") or [])
    cover = " / ".join(model.get("cover_picks") or [])
    return (
        f"🧪 **プロトタイプ3｜日和本線＋中穴抑え**\n"
        f"🏁 **{record['venue']} {record['rno']}R**｜締切 {record['deadline']}\n"
        f"🎯 **本線・日和（{len(model.get('main_picks') or [])}点）**\n"
        f"`{main}`\n"
        f"🔥 **抑え・中穴くん＋日和（{len(model.get('cover_picks') or [])}点）**\n"
        f"`{cover or 'なし'}`\n"
        f"📊 計{model['point_count']}点｜Grade {model['grade']}｜比較テスト配信"
    )


def build_record(day, jcd, rno, deadline):
    official = base.analyze_official(day, jcd, rno)
    if not official:
        return None, "official_unavailable"
    if official.get("preview", {}).get("exhibition_count") != 6:
        return None, "waiting_for_exhibition"

    source = hiyori_source.fetch_race(day, jcd, rno)
    source["fetched_at"] = now_jst().isoformat()
    hiyori = hiyori_model.analyze(official, source, day, jcd, rno)
    if not any(f.get("used") for f in hiyori.get("features", [])):
        return None, "hiyori_feature_unavailable"

    odds = {}
    for row in official.get("trifecta") or []:
        try:
            odd = float(row.get("odds"))
            if odd > 0:
                odds[row["combination"]] = odd
        except (TypeError, ValueError, KeyError):
            pass

    copied = json.loads(json.dumps(hiyori, ensure_ascii=False))
    native_rows = cards.displayed_picks_variable(copied, True)
    native_hiyori = [row["combination"] for row in native_rows]
    model = trial._prototype3_card(hiyori, odds, native_hiyori)

    record = {
        "key": key_for(day, jcd, rno),
        "day": day,
        "jcd": str(jcd).zfill(2),
        "rno": int(rno),
        "venue": official["venue"],
        "deadline": deadline,
        "created_at": now_jst().isoformat(),
        "model": model,
    }
    record["digest"] = sha256(
        json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return record, "ready"


def receipt_path(key):
    return ROOT / "deliveries" / f"{key}.json"


def prediction_path(key):
    return ROOT / "predictions" / f"{key}.json"


def deliver(record):
    key = record["key"]
    receipt = receipt_path(key)
    if receipt.exists():
        return
    if not trial.before_deadline(record["day"], record["deadline"], now_jst()):
        return

    url = os.getenv(WEBHOOK_ENV, "").strip()
    if not url:
        raise RuntimeError(f"{WEBHOOK_ENV} is not configured")

    try:
        post_webhook(url, {"username": "プロトタイプ3", "content": message(record)})
        trial.write_json(receipt, {
            "key": key,
            "delivered_at": now_jst().isoformat(),
            "prediction_digest": record["digest"],
        })
        print(f"prototype3 delivery confirmed {key}", flush=True)
    except Exception as exc:
        print(f"prototype3 delivery retry pending {key}: {type(exc).__name__}", flush=True)


def process_race(day, jcd, rno, deadline):
    key = key_for(day, jcd, rno)
    path = prediction_path(key)

    if path.exists():
        deliver(read(path))
        return

    if not trial.before_deadline(day, deadline, now_jst()):
        trial.write_json(ROOT / "status" / f"{key}.json", {
            "key": key, "state": "missed_deadline", "updated_at": now_jst().isoformat()
        })
        return

    try:
        record, state = build_record(day, jcd, rno, deadline)
        if record is None:
            trial.write_json(ROOT / "status" / f"{key}.json", {
                "key": key, "state": state, "updated_at": now_jst().isoformat()
            })
            return

        trial.write_once(
            path,
            (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"),
        )
        deliver(read(path))
        trial.write_json(ROOT / "status" / f"{key}.json", {
            "key": key, "state": "recorded", "updated_at": now_jst().isoformat()
        })
    except Exception as exc:
        trial.write_json(ROOT / "status" / f"{key}.json", {
            "key": key, "state": "data_error", "error_type": type(exc).__name__,
            "updated_at": now_jst().isoformat()
        })
        print(f"prototype3 analysis pending {key}: {type(exc).__name__}", flush=True)


def get_schedule(day, jcd):
    try:
        return jcd, base.deadlines(day, jcd)
    except Exception as exc:
        print(f"prototype3 schedule pending {jcd}: {type(exc).__name__}", flush=True)
        return jcd, []


def retry_saved(day):
    folder = ROOT / "predictions"
    if not folder.exists():
        return
    for path in sorted(folder.glob(f"{day}_*.json")):
        record = read(path)
        if not receipt_path(record["key"]).exists():
            deliver(record)


def run(watch_seconds=210):
    if not os.getenv(WEBHOOK_ENV, "").strip():
        raise RuntimeError(f"{WEBHOOK_ENV} is not configured")

    end = time.monotonic() + max(0, watch_seconds)
    schedules = {}
    schedule_at = float("-inf")
    active_day = None

    while True:
        now = now_jst()
        day = now.strftime("%Y%m%d")
        if day != active_day:
            schedules = {}
            schedule_at = float("-inf")
            active_day = day

        base.fetch.cache_clear()
        if 8 <= now.hour <= 23 and time.monotonic() - schedule_at >= 120:
            venues = base.discover_venues(day)
            with ThreadPoolExecutor(max_workers=8) as pool:
                schedules = dict(pool.map(lambda j: get_schedule(day, j), venues))
            schedule_at = time.monotonic()

        retry_saved(day)
        now = now_jst()
        due = [
            (day, jcd, rno, deadline)
            for jcd, times in schedules.items()
            for rno, deadline in enumerate(times, 1)
            if 1 <= base.minutes_until(now, deadline) <= 30
        ]
        due.sort(key=lambda item: item[3])
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda args: process_race(*args), due))

        if time.monotonic() >= end:
            break
        time.sleep(min(20, max(0, end - time.monotonic())))


if __name__ == "__main__":
    run(int(os.getenv("PROTOTYPE3_WATCH_SECONDS", "210")))
