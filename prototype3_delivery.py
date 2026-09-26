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
WEBHOOK_ENV = "PT3_DISCORD_WEBHOOK_URL"
LEGACY_WEBHOOK_ENV = "PROTO3_DISCORD_WEBHOOK_URL"
SELECTED_WEBHOOK_ENV = "PT3_SELECTED_DISCORD_WEBHOOK_URL"


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


def _head_values(heads):
    clean = {}
    for lane in range(1, 7):
        value = heads.get(lane, heads.get(str(lane), 0)) if isinstance(heads, dict) else 0
        try:
            clean[lane] = float(value or 0)
        except (TypeError, ValueError):
            clean[lane] = 0.0
    ranked = sorted(clean, key=clean.get, reverse=True)
    top = ranked[0]
    second = ranked[1]
    return clean, top, clean[top], clean[top] - clean[second]


def selection_info(official, model, native_existing):
    """Conservative PT3-specific gate for 新人予想家 ゆうき厳選."""
    h_heads, h_top, h_prob, h_gap = _head_values(model.get("heads") or {})
    e_heads, e_top, e_prob, _ = _head_values(official.get("heads") or {})
    head_agreement = h_top == e_top

    picks = list(dict.fromkeys(model.get("picks") or []))
    existing_set = set(native_existing or [])
    consensus = [pick for pick in picks if pick in existing_set]
    consensus_ratio = len(consensus) / len(picks) if picks else 0.0

    point_count = int(model.get("point_count") or len(picks))
    projected_roi = None
    try:
        if model.get("estimated_return_yen") is not None and float(model.get("stake_yen") or 0) > 0:
            projected_roi = float(model["estimated_return_yen"]) / float(model["stake_yen"])
    except (TypeError, ValueError, ZeroDivisionError):
        projected_roi = None

    score = 0
    grade = str(model.get("grade") or "")
    score += 30 if grade == "A" else 15 if grade == "B" else 0
    if head_agreement:
        score += 20
    if h_prob >= 0.50:
        score += 15
    elif h_prob >= 0.45:
        score += 10
    elif h_prob >= 0.40:
        score += 5
    if h_gap >= 0.25:
        score += 10
    elif h_gap >= 0.18:
        score += 7
    elif h_gap >= 0.12:
        score += 4
    if e_prob >= 0.45:
        score += 10
    elif e_prob >= 0.38:
        score += 6
    if consensus_ratio >= 0.45:
        score += 10
    elif consensus_ratio >= 0.30:
        score += 6
    elif consensus_ratio >= 0.20:
        score += 3
    if point_count <= 12:
        score += 8
    elif point_count <= 14:
        score += 4
    if projected_roi is not None:
        if projected_roi >= 1.10:
            score += 7
        elif projected_roi >= 1.02:
            score += 3

    selected = (
        score >= 75
        and grade in {"A", "B"}
        and head_agreement
        and h_prob >= 0.40
        and e_prob >= 0.34
        and point_count <= 14
    )
    reasons = []
    if head_agreement:
        reasons.append(f"日和×既存 頭{h_top}一致")
    if grade:
        reasons.append(f"Grade {grade}")
    if consensus:
        reasons.append(f"買い目合致{len(consensus)}点")
    if projected_roi is not None:
        reasons.append(f"期待回収{projected_roi*100:.0f}%")
    return {
        "selected": selected,
        "score": score,
        "grade": grade,
        "hiyori_top_head": h_top,
        "hiyori_top_probability": h_prob,
        "hiyori_head_gap": h_gap,
        "existing_top_head": e_top,
        "existing_top_probability": e_prob,
        "head_agreement": head_agreement,
        "consensus_count": len(consensus),
        "consensus_ratio": consensus_ratio,
        "point_count": point_count,
        "projected_roi": projected_roi,
        "reasons": reasons,
    }


def selected_message(record):
    model = record["model"]
    selected = record.get("selection") or {}
    main = " / ".join(model.get("main_picks") or [])
    cover = " / ".join(model.get("cover_picks") or [])
    reason = "・".join(selected.get("reasons") or []) or "複合条件クリア"
    return (
        f"🏅 **新人予想家 ゆうき｜厳選**\n"
        f"🏁 **{record['venue']} {record['rno']}R**｜締切 {record['deadline']}\n"
        f"✅ 厳選スコア **{selected.get('score', 0)}**｜{reason}\n"
        f"🎯 **本線（{len(model.get('main_picks') or [])}点）**\n"
        f"`{main}`\n"
        f"🔥 **抑え（{len(model.get('cover_picks') or [])}点）**\n"
        f"`{cover or 'なし'}`\n"
        f"📊 計{model['point_count']}点｜通常配信より厳しい条件を通過"
    )


def message(record):
    model = record["model"]
    main = " / ".join(model.get("main_picks") or [])
    cover = " / ".join(model.get("cover_picks") or [])
    return (
        f"🏆 **新人予想家 ゆうき｜日和本線＋中穴抑え**\n"
        f"🏁 **{record['venue']} {record['rno']}R**｜締切 {record['deadline']}\n"
        f"🎯 **本線・日和（{len(model.get('main_picks') or [])}点）**\n"
        f"`{main}`\n"
        f"🔥 **抑え・中穴くん＋日和（{len(model.get('cover_picks') or [])}点）**\n"
        f"`{cover or 'なし'}`\n"
        f"📊 計{model['point_count']}点｜Grade {model['grade']}｜本番配信"
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

    existing_copy = json.loads(json.dumps(official, ensure_ascii=False))
    native_existing_rows = cards.displayed_picks_variable(existing_copy, True)
    native_existing = [row["combination"] for row in native_existing_rows]
    selection = selection_info(official, model, native_existing)

    record = {
        "key": key_for(day, jcd, rno),
        "day": day,
        "jcd": str(jcd).zfill(2),
        "rno": int(rno),
        "venue": official["venue"],
        "deadline": deadline,
        "created_at": now_jst().isoformat(),
        "model": model,
        "selection": selection,
    }
    record["digest"] = sha256(
        json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return record, "ready"


def receipt_path(key):
    return ROOT / "deliveries" / f"{key}.json"


def prediction_path(key):
    return ROOT / "predictions" / f"{key}.json"


def selected_receipt_path(key):
    return ROOT / "selected_deliveries" / f"{key}.json"


def enrich_selection(record):
    """Backfill the selected gate for predictions saved before selection was introduced."""
    current = record.get("selection")
    if isinstance(current, dict) and "selected" in current:
        return record, False

    official = base.analyze_official(record["day"], record["jcd"], int(record["rno"]))
    if not official:
        return record, False

    existing_copy = json.loads(json.dumps(official, ensure_ascii=False))
    native_existing_rows = cards.displayed_picks_variable(existing_copy, True)
    native_existing = [row["combination"] for row in native_existing_rows]
    record["selection"] = selection_info(official, record["model"], native_existing)

    digest_source = dict(record)
    digest_source.pop("digest", None)
    record["digest"] = sha256(
        json.dumps(digest_source, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return record, True


def deliver(record):
    key = record["key"]
    receipt = receipt_path(key)
    selected_receipt = selected_receipt_path(key)
    if not trial.before_deadline(record["day"], record["deadline"], now_jst()):
        return

    url = os.getenv(WEBHOOK_ENV, "").strip() or os.getenv(LEGACY_WEBHOOK_ENV, "").strip()
    if not url:
        raise RuntimeError(f"{WEBHOOK_ENV} / {LEGACY_WEBHOOK_ENV} is not configured")
    selected_url = os.getenv(SELECTED_WEBHOOK_ENV, "").strip() or url
    is_selected = bool((record.get("selection") or {}).get("selected"))

    try:
        # If 厳選 uses the same channel, send one upgraded message instead of duplicating.
        if not receipt.exists():
            content = selected_message(record) if is_selected and selected_url == url else message(record)
            post_webhook(url, {"username": "新人予想家 ゆうき", "content": content})
            trial.write_json(receipt, {
                "key": key,
                "delivered_at": now_jst().isoformat(),
                "prediction_digest": record["digest"],
                "selected": is_selected,
            })
            if is_selected and selected_url == url:
                trial.write_json(selected_receipt, {
                    "key": key,
                    "delivered_at": now_jst().isoformat(),
                    "prediction_digest": record["digest"],
                    "selection_score": (record.get("selection") or {}).get("score"),
                })
            print(f"prototype3 delivery confirmed {key} selected={is_selected}", flush=True)

        if is_selected and selected_url != url and not selected_receipt.exists():
            post_webhook(selected_url, {"username": "新人予想家 ゆうき｜厳選", "content": selected_message(record)})
            trial.write_json(selected_receipt, {
                "key": key,
                "delivered_at": now_jst().isoformat(),
                "prediction_digest": record["digest"],
                "selection_score": (record.get("selection") or {}).get("score"),
            })
            print(f"yuuki selected delivery confirmed {key}", flush=True)
    except Exception as exc:
        print(f"prototype3 delivery retry pending {key}: {type(exc).__name__}", flush=True)


def process_race(day, jcd, rno, deadline):
    key = key_for(day, jcd, rno)
    path = prediction_path(key)

    if path.exists():
        record = read(path)
        record, changed = enrich_selection(record)
        if changed:
            trial.write_json(path, record)
            print(
                f"prototype3 selection backfilled {key} "
                f"selected={bool((record.get('selection') or {}).get('selected'))}",
                flush=True,
            )
        deliver(record)
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
        record, changed = enrich_selection(record)
        if changed:
            trial.write_json(path, record)
        # deliver() is receipt-aware for both normal and selected channels.
        # Always call it so an already-delivered race can still reach a
        # dedicated selected channel after selection is backfilled.
        deliver(record)


def run(watch_seconds=210):
    if not (os.getenv(WEBHOOK_ENV, "").strip() or os.getenv(LEGACY_WEBHOOK_ENV, "").strip()):
        raise RuntimeError(f"{WEBHOOK_ENV} / {LEGACY_WEBHOOK_ENV} is not configured")

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
