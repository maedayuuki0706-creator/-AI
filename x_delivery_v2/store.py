"""Atomic claims and acknowledgement receipts on the existing X state branch."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import re

import x_delivery_store as outbox

MAX_ATTEMPTS = 3
FIELDS = {"prediction": ("x_attempts", "x_posted_races", "x_post_ids"),
          "result": ("x_result_attempts", "x_result_races", "x_result_post_ids")}


def key(row):
    day, jcd, rno = str(row["day"]), str(row["jcd"]).zfill(2), int(row["rno"])
    if not re.fullmatch(r"20\d{6}", day) or not re.fullmatch(r"\d{2}", jcd) or not 1 <= int(jcd) <= 24 or not 1 <= rno <= 12:
        raise ValueError("Invalid X race identity")
    datetime.strptime(day, "%Y%m%d")
    return f'{day}:{jcd}:{rno}'


def receipt_key(row, phase):
    return phase+":"+key(row)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+"\n"


class Store:
    def state(self, day):
        return outbox.load_state(day)

    def archive(self, day):
        raw = outbox.load_archive(day)
        rows = {}
        for line in raw.splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("day") != day:
                    raise ValueError("X archive day mismatch")
                rows.setdefault(key(row), row)
        return rows

    def publish(self, row):
        outbox.publish_archive(row["day"], json.dumps(row, ensure_ascii=False)+"\n")
        # The first durable payload wins, including during legacy coexistence.
        return self.archive(row["day"])[key(row)]

    def update(self, day, change):
        raw, commit = outbox._update(f'data/x_post_delivery/{day}.json',
                                    lambda old: encode(change(json.loads(old) if old else {})))
        return json.loads(raw), commit

    def claim(self, row, phase, owner, now, *, quota=10):
        attempts, sent, ids = FIELDS[phase]
        race = key(row)
        rkey = receipt_key(row, phase)
        def change(state):
            if str((state.get(ids) or {}).get(race, "")).isdigit():
                return state
            if phase == "result" and not str((state.get("x_post_ids") or {}).get(race, "")).isdigit():
                return state
            old = (state.get(attempts) or {}).get(race) or {}
            if old.get("status") in {"reserved", "uncertain", "blocked"}:
                return state
            if old.get("retry_at") and now < datetime.fromisoformat(old["retry_at"]):
                return state
            if int(old.get("attempt", 0)) >= MAX_ATTEMPTS:
                return state
            if phase == "prediction":
                committed = set(state.get("x_featured_races") or [])
                for k, value in (state.get("x_v2_receipts") or {}).items():
                    if k.startswith("prediction:") and value.get("status") in {"sending", "sent", "uncertain"}:
                        committed.add(k.removeprefix("prediction:"))
                if race not in committed and len(committed) >= quota:
                    return state
            attempt = int(old.get("attempt", 0))+1
            state.setdefault(attempts, {})[race] = {
                "id": owner, "status": "reserved", "at": now.isoformat(), "attempt": attempt}
            state.setdefault("x_v2_receipts", {})[rkey] = {
                "key": rkey, "status": "sending", "phase": phase, "owner": owner,
                "attempt": attempt, "claimed_at": now.isoformat(), "row": row,
                "content_sha256": hashlib.sha256(row["post"].encode()).hexdigest(),
                "parent_post_id": str((state.get("x_post_ids") or {}).get(race, "")) if phase == "result" else None}
            return state
        return self.update(row["day"], change)

    def finish(self, row, phase, owner, outcome, now):
        attempts, sent, ids = FIELDS[phase]
        race, rkey = key(row), receipt_key(row, phase)
        def change(state):
            receipt = (state.get("x_v2_receipts") or {}).get(rkey) or {}
            current = (state.get(attempts) or {}).get(race) or {}
            if current.get("id") != owner:
                raise RuntimeError("X claim changed before acknowledgement persistence")
            final_outcome = dict(outcome)
            status = final_outcome["status"]
            if status == "retry" and current.get("attempt", 1) >= MAX_ATTEMPTS:
                status = "failed"
                final_outcome["status"] = status
            receipt = {**receipt, **final_outcome, "updated_at": now.isoformat()}
            state.setdefault("x_v2_receipts", {})[rkey] = receipt
            if status == "sent":
                post_id = str(final_outcome.get("post_id") or "")
                if not post_id.isdigit():
                    raise ValueError("X acknowledgement requires a numeric post id")
                state[sent] = sorted(set(state.get(sent) or []) | {race})
                state.setdefault(ids, {})[race] = post_id
                state[attempts].pop(race, None)
                if phase == "prediction":
                    state["x_featured_races"] = sorted(set(state.get("x_featured_races") or []) | {race})
                    state.setdefault("x_featured_modes", {})[race] = row["source"]
            elif status == "waiting_result":
                # No X POST was attempted. Result availability can be checked
                # repeatedly without consuming the network-error retry budget.
                state[attempts][race] = {**current, "status": "retryable", "attempt": max(0, current.get("attempt", 1)-1),
                                        "retry_at": (now+timedelta(seconds=30)).isoformat()}
            else:
                legacy_status = "retryable" if status == "retry" else "blocked" if status in {"failed", "expired"} else "uncertain"
                state[attempts][race] = {**current, "status": legacy_status,
                                        "retry_at": (now+timedelta(seconds=60)).isoformat()}
            return state
        return self.update(row["day"], change)[0]

    def report(self, day, value):
        outbox._update(f'data/x_delivery_v2/{day}/dispatcher.json', lambda old: encode(value))
