"""Dedicated Prototype 1/2 Discord delivery loop.

Kept separate from the five-way research workflow so experimental failures
cannot block the two production test channels.
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

import bridge_learning
import direct_discord_notify as base
import four_way_prototype as trial
import hiyori_model
import hiyori_source

ROOT = Path("data/prototype12_delivery")
STREAMS = ("prototype1", "prototype2")
WEBHOOKS = {
    "prototype1": ("PROTO1_DISCORD_WEBHOOK_URL", "プロトタイプ1"),
    "prototype2": ("PROTO2_DISCORD_WEBHOOK_URL", "プロトタイプ2"),
}


def now_jst():
    return datetime.now(base.JST)


def key_for(day, jcd, rno):
    return trial.identity(day, jcd, rno)


def path_for(kind, stream, key):
    return ROOT / kind / stream / f"{key}.json"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    trial.write_json(path, value)


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


def model_message(record, stream):
    model = record["models"][stream]
    if stream == "prototype1":
        title = "プロトタイプ1｜PT3＋穴スナイパー"
        ratio = "PT3コア＋穴くん厳選ブースト（最大3点）"
    else:
        title = "プロトタイプ2｜PT3×既存メイン圧縮"
        ratio = "PT3を既存メインとの一致度で7〜10点へ圧縮"
    main = " / ".join(model.get("main_picks") or [])
    cover = " / ".join(model.get("cover_picks") or [])
    return (
        f"🧪 **{title}**\n"
        f"🏁 **{record['venue']} {record['rno']}R**｜締切 {record['deadline']}\n"
        f"⚖️ {ratio}\n"
        f"◎ **本線 {len(model.get('main_picks') or [])}点**\n"
        f"`{main}`\n"
        f"○ **迎え {len(model.get('cover_picks') or [])}点**\n"
        f"`{cover}`\n"
        f"🎯 **合計 {model['point_count']}点**\n"
        f"📊 Grade {model['grade']}｜比較テスト配信"
    )


def build_record(day, jcd, rno, deadline):
    captured = now_jst()
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

    native_hiyori = [row["combination"] for row in base.displayed_picks_variable(
        hiyori, True)] if hasattr(base, "displayed_picks_variable") else [
            row["combination"] for row in trial.cards.displayed_picks_variable(hiyori, True)]

    existing_native = [row["combination"] for row in base.displayed_picks_variable(
        official, True)] if hasattr(base, "displayed_picks_variable") else [
            row["combination"] for row in trial.cards.displayed_picks_variable(official, True)]
    existing_native = [row["combination"] for row in bridge_learning._reallocate(
        official, [{"combination": p} for p in existing_native]
    )] if False else existing_native

    models = {
        "prototype1": trial._prototype1_attack(
            hiyori, official, odds, native_hiyori),
        "prototype2": trial._prototype2_compress(
            hiyori, official, odds, native_hiyori, existing_native),
    }

    key = key_for(day, jcd, rno)
    record = {
        "key": key,
        "day": day,
        "jcd": str(jcd).zfill(2),
        "rno": int(rno),
        "venue": official["venue"],
        "deadline": deadline,
        "created_at": now_jst().isoformat(),
        "models": models,
    }
    record["digest"] = sha256(
        json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return record, "ready"


def delivery_complete(key):
    return all(path_for("deliveries", stream, key).exists() for stream in STREAMS)


def deliver(record):
    key = record["key"]
    if not trial.before_deadline(record["day"], record["deadline"], now_jst()):
        return
    for stream in STREAMS:
        receipt = path_for("deliveries", stream, key)
        if receipt.exists():
            continue
        env_name, username = WEBHOOKS[stream]
        url = os.getenv(env_name, "").strip()
        if not url:
            print(f"{env_name} missing; {stream} remains pending", flush=True)
            continue
        try:
            post_webhook(url, {"username": username, "content": model_message(record, stream)})
            write_json(receipt, {
                "key": key,
                "stream": stream,
                "prediction_digest": record["digest"],
                "delivered_at": now_jst().isoformat(),
            })
            print(f"delivery confirmed {key} {stream}", flush=True)
        except Exception as exc:
            print(f"delivery retry pending {key} {stream}: {type(exc).__name__}", flush=True)


def process_race(day, jcd, rno, deadline):
    key = key_for(day, jcd, rno)
    prediction = ROOT / "predictions" / f"{key}.json"
    if prediction.exists():
        deliver(read(prediction))
        return

    if not trial.before_deadline(day, deadline, now_jst()):
        write_json(ROOT / "status" / f"{key}.json", {
            "key": key, "state": "missed_deadline", "updated_at": now_jst().isoformat()
        })
        return

    try:
        record, state = build_record(day, jcd, rno, deadline)
        if record is None:
            write_json(ROOT / "status" / f"{key}.json", {
                "key": key, "state": state, "updated_at": now_jst().isoformat()
            })
            return
        trial.write_once(
            prediction,
            (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"),
        )
        deliver(read(prediction))
        write_json(ROOT / "status" / f"{key}.json", {
            "key": key, "state": "recorded", "updated_at": now_jst().isoformat()
        })
    except Exception as exc:
        write_json(ROOT / "status" / f"{key}.json", {
            "key": key, "state": "data_error", "error_type": type(exc).__name__,
            "updated_at": now_jst().isoformat()
        })
        print(f"analysis pending {key}: {type(exc).__name__}", flush=True)


def get_schedule(day, jcd):
    try:
        return jcd, base.deadlines(day, jcd)
    except Exception as exc:
        print(f"schedule pending {jcd}: {type(exc).__name__}", flush=True)
        return jcd, []


def retry_saved(day):
    folder = ROOT / "predictions"
    if not folder.exists():
        return
    for path in sorted(folder.glob(f"{day}_*.json")):
        record = read(path)
        if not delivery_complete(record["key"]):
            deliver(record)


def run(watch_seconds=210):
    for env_name, _ in WEBHOOKS.values():
        if not os.getenv(env_name, "").strip():
            raise RuntimeError(f"{env_name} is not configured")

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
    run(int(os.getenv("PROTOTYPE12_WATCH_SECONDS", "210")))
