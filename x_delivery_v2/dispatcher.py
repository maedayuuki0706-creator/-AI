"""Short X production pass: existing forecasts -> durable claim -> X ID -> receipt."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
import uuid

import x_featured_selector as selector
import x_post_delivery as formatter
from x_delivery_policy import JST, validate_live_row
from x_delivery_v2.store import FIELDS, Store, key, receipt_key

RECOVERY = Path("data/x_delivery_v2_recovery")


def close_time(row):
    return datetime.strptime(row["day"]+" "+row["deadline"], "%Y%m%d %H:%M").replace(tzinfo=JST)


def candidate_row(item, now):
    """The existing selector and formatter retain ownership of prediction logic."""
    race = item["race"]
    stem = f'{race["day"]}_{race["jcd"]}_{race["rno"]:02d}'
    refs = []
    source_commit = os.getenv("X_DELIVERY_SOURCE_COMMIT", "local")
    if os.getenv("GITHUB_RUN_ID") and not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("Prediction source checkout commit is missing")
    for root in (selector.PT12_DIR, selector.PT3_DIR):
        path = root / (stem+".json")
        if not path.exists():
            continue
        source = selector._read(path)
        if (source.get("day"), str(source.get("jcd")).zfill(2), source.get("rno"), source.get("deadline")) != (
                race["day"], race["jcd"], race["rno"], race["deadline"]):
            raise ValueError("Prediction source identity/deadline mismatch")
        created = datetime.fromisoformat(source["created_at"])
        if created.tzinfo is None or not -60 <= (now-created).total_seconds() <= 900:
            raise ValueError("Prediction source is not fresh")
        refs.append({"path": str(path), "record_digest": source["digest"],
                     "record_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "created_at": created.isoformat(), "commit": source_commit})
    if not refs:
        raise ValueError("Prediction source record missing")
    record = {k:race[k] for k in ("day", "jcd", "rno", "venue", "deadline")}
    text, picks = formatter.build_featured_post(record, item["picks"], source=item["source"],
        note=item["note"], main_picks=item["main_picks"], cover_picks=item["cover_picks"])
    row = {**record, "source": item["source"], "post": text, "picks": picks,
           "sent_at": now.isoformat(), "format_version": formatter.FORMAT_VERSION,
           "prediction_records": refs, "selection_score": item["score"], "resend": False}
    validate_live_row(row, now, min_lead_seconds=selector.MIN_LEAD_SECONDS)
    return row


def render_send(phase, body):
    url = formatter.RENDER_SYNC_URL if phase == "prediction" else formatter.RENDER_RESULT_URL
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "boat-ai-x-delivery-v2"})
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read())
        except (ValueError, TypeError):
            return {"ok": False}


def deliver(row, phase, *, store, clock, transport=render_send):
    race = key(row)
    _, _, ids = FIELDS[phase]
    before = store.state(row["day"])
    post_id = str((before.get(ids) or {}).get(race) or "")
    if post_id.isdigit():
        return {"key": receipt_key(row, phase), "status": "already_sent", "post_id": post_id}
    if phase == "prediction":
        try:
            validate_live_row(row, clock(), min_lead_seconds=selector.MIN_LEAD_SECONDS)
        except ValueError:
            return {"key": receipt_key(row, phase), "status": "expired"}
    elif not str((before.get("x_post_ids") or {}).get(race, "")).isdigit() or clock() <= close_time(row):
        return {"key": receipt_key(row, phase), "status": "not_due"}
    owner = uuid.uuid4().hex
    state, commit = store.claim(row, phase, owner, clock())
    attempts, _, _ = FIELDS[phase]
    claim = (state.get(attempts) or {}).get(race) or {}
    if claim.get("id") != owner:
        receipt = (state.get("x_v2_receipts") or {}).get(receipt_key(row, phase)) or {}
        return {"key": receipt_key(row, phase), "status": receipt.get("status") or claim.get("status") or "quota_or_guard"}
    if phase == "prediction":
        try:
            validate_live_row(row, clock(), min_lead_seconds=selector.MIN_LEAD_SECONDS)
        except ValueError:
            result = {"status": "expired"}
            store.finish(row, phase, owner, result, clock())
            return {"key": receipt_key(row, phase), **result}
    body = {"day":row["day"], "jcd":row["jcd"], "rno":row["rno"],
            "archive_ref":commit, "attempt_id":owner}
    started = clock()
    try:
        response = transport(phase, body)
    except Exception as exc:
        response = {"ok":False, "error_type":type(exc).__name__}
    response = response if isinstance(response, dict) else {"ok": False}
    if response.get("ok") and str(response.get("post_id") or "").isdigit():
        result = {"status": "sent", "post_id": str(response["post_id"]),
                  "sent_at":clock().isoformat(), "request_started_at":started.isoformat(),
                  "response":{k:response[k] for k in ("winner", "odds", "hit", "text", "reply_to") if k in response}}
        try:
            RECOVERY.mkdir(parents=True, exist_ok=True)
            proof = RECOVERY / (receipt_key(row, phase).replace(":", "_")+".json")
            proof.write_text(json.dumps({"row":row, "phase":phase, "owner":owner, **result},
                                       ensure_ascii=False, sort_keys=True)+"\n", encoding="utf-8")
        except OSError:
            print("::warning::X local recovery unavailable; saving the durable receipt", flush=True)
    elif response.get("definitely_not_posted"):
        pending = phase == "result" and response.get("error") in {"official result pending", "official payout unavailable"}
        result = {"status": "waiting_result" if pending else "retry" if response.get("retryable") else "failed",
                  "error_type":response.get("error_type") or "DefiniteRejection"}
    else:
        result = {"status":"uncertain", "error_type":response.get("error_type") or "MissingAcknowledgement"}
    saved = store.finish(row, phase, owner, result, clock())
    persisted = saved["x_v2_receipts"][receipt_key(row, phase)]
    print("X V2 "+json.dumps({"key":persisted["key"], "status":persisted["status"],
                             "post_id":persisted.get("post_id")}, ensure_ascii=False), flush=True)
    return persisted


def verify(state, archive):
    verified = []
    for rkey, row in (state.get("x_v2_receipts") or {}).items():
        if row.get("status") != "sent":
            continue
        phase = row["phase"]
        original = row["row"]
        if rkey != receipt_key(original, phase):
            raise ValueError("Native X receipt has a different race identity")
        post_id = str(row.get("post_id") or "")
        race = key(original)
        _, _, ids = FIELDS[phase]
        if not post_id.isdigit() or post_id != str((state.get(ids) or {}).get(race)):
            raise ValueError("Native X receipt does not match the posted ID")
        stored = archive.get(race)
        if stored != original or row["content_sha256"] != hashlib.sha256(original["post"].encode()).hexdigest():
            raise ValueError("Native X receipt differs from the original durable payload")
        if phase == "prediction" and datetime.fromisoformat(row["sent_at"]) > close_time(original)-timedelta(minutes=10):
            raise ValueError("X acknowledgement was later than the ten-minute cutoff")
        if phase == "result" and row.get("parent_post_id") != str((state.get("x_post_ids") or {}).get(race)):
            raise ValueError("X result receipt has the wrong prediction parent")
        verified.append({"key":rkey, "post_id":post_id, "sent_at":row["sent_at"],
                         "content_sha256":row["content_sha256"], "verified":True})
    return verified


def run_once(*, store=None, clock=None, transport=render_send, mode="all", budget_seconds=90,
             monotonic=time.monotonic, ready=formatter.check_render_ready, candidates=None):
    clock = clock or (lambda:datetime.now(JST))
    now = clock()
    if now.tzinfo is None:
        raise ValueError("X dispatcher requires a timezone")
    day = now.astimezone(JST).strftime("%Y%m%d")
    store = store or Store()
    started = monotonic()
    audit, events, errors = {}, [], []
    state = store.state(day)
    items = []
    if mode != "results":
        items = candidates if candidates is not None else selector.collect_candidates(now, state, audit=audit)
    ready_checked = False
    def send(row, phase):
        nonlocal ready_checked
        if not ready_checked:
            ready()
            ready_checked = True
        return deliver(row, phase, store=store, clock=clock, transport=transport)
    for item in items:
        if monotonic()-started >= budget_seconds or clock().astimezone(JST).strftime("%Y%m%d") != day:
            audit["budget_exhausted"] = len(items)-len(events)
            break
        try:
            row = candidate_row(item, clock())
            row = store.publish(row)
            events.append(send(row, "prediction"))
        except Exception as exc:
            errors.append({"stage":"prediction", "key":item.get("key"), "error_type":type(exc).__name__})
    days = [day, (now.astimezone(JST)-timedelta(days=1)).strftime("%Y%m%d")]
    if mode != "predictions":
        for result_day in days:
            previous = store.state(result_day)
            for race, row in store.archive(result_day).items():
                if monotonic()-started >= budget_seconds:
                    break
                if not str((previous.get("x_post_ids") or {}).get(race, "")).isdigit() or race in (previous.get("x_result_races") or []):
                    continue
                if clock() <= close_time(row):
                    continue
                try:
                    events.append(send(row, "result"))
                except Exception as exc:
                    errors.append({"stage":"result", "key":race, "error_type":type(exc).__name__})
    native = []
    held = []
    for check_day in days:
        current = store.state(check_day)
        archive = store.archive(check_day)
        try:
            native += verify(current, archive)
        except (ValueError, KeyError, TypeError) as exc:
            errors.append({"stage":"verification", "day":check_day, "error_type":type(exc).__name__})
        for phase, (attempts, _, _) in FIELDS.items():
            for race, attempt in (current.get(attempts) or {}).items():
                if attempt.get("status") in {"reserved", "uncertain", "blocked"}:
                    held.append({"key":phase+":"+race, "status":attempt["status"]})
        for proof in [x for x in native if x["key"].split(":")[1] == check_day]:
            saved = current["x_v2_receipts"][proof["key"]]
            def forbidden(*args):
                raise AssertionError("Verified X prediction tried another POST")
            replay = deliver(saved["row"], saved["phase"], store=store, clock=clock, transport=forbidden)
            if replay["status"] != "already_sent" or replay["post_id"] != proof["post_id"]:
                raise ValueError("X restart duplicate guard did not hold")
            proof["restart_duplicate_guard_verified"] = True
    report = {"day":day, "checked_at":clock().isoformat(), "workflow_run_id":os.getenv("GITHUB_RUN_ID", "local"),
              "trigger_event":os.getenv("GITHUB_EVENT_NAME", ""), "mode":mode,
              "status":"degraded" if errors or held else "checked", "audit":audit,
              "counts":dict(Counter(row["status"] for row in events)), "events":[{k:row[k] for k in ("key","status","post_id") if k in row} for row in events],
              "errors":errors, "held":held, "production_verification":native}
    store.report(day, report)
    print("X dispatcher "+json.dumps({k:report[k] for k in ("day", "status", "audit", "counts", "errors", "held")}, ensure_ascii=False), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("all", "predictions", "results"), default="all")
    parser.add_argument("--budget-seconds", type=int, default=90)
    args = parser.parse_args()
    try:
        report = run_once(mode=args.mode, budget_seconds=args.budget_seconds)
        return 0 if report["status"] == "checked" else 1
    except Exception as exc:
        print(f"::error::X production dispatcher failed ({type(exc).__name__})", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
