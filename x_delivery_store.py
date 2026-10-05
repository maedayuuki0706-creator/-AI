"""Durable X outbox on its own Git branch, independent of the long watcher.

Only the existing Actions job writes this branch using its repository token.
Render reads immutable commits, so neither raw-file caching nor main-branch
deployment delays hold up a live prediction. No X credentials leave Render.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = "maedayuuki0706-creator/-AI"
BRANCH = "x-delivery-state"
API = f"https://api.github.com/repos/{REPOSITORY}"
_ready = False


def configured() -> bool:
    return bool(os.getenv("GITHUB_TOKEN", "").strip())


def _request(path: str, payload: dict | None = None, *, method="GET") -> dict:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("X outbox requires the Actions repository token")
    request = urllib.request.Request(
        API + path,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "User-Agent": "boat-ai-x-outbox"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _ensure_branch() -> None:
    global _ready
    if _ready:
        return
    try:
        _request(f"/git/ref/heads/{BRANCH}")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        head = _request("/git/ref/heads/main")["object"]["sha"]
        try:
            _request("/git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": head}, method="POST")
        except urllib.error.HTTPError as race:
            if race.code != 422:
                raise
            _request(f"/git/ref/heads/{BRANCH}")
    _ready = True


def _read(path: str) -> tuple[str, str | None]:
    try:
        value = _request(f"/contents/{path}?ref={BRANCH}")
        return base64.b64decode(value["content"]).decode("utf-8"), value["sha"]
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return "", None
        raise


def _update(path: str, merge) -> tuple[str, str]:
    _ensure_branch()
    for attempt in range(8):
        old, sha = _read(path)
        content = merge(old)
        if content == old:
            head = _request(f"/git/ref/heads/{BRANCH}")["object"]["sha"]
            return content, head
        payload = {"message": "Checkpoint live X delivery", "branch": BRANCH,
                   "content": base64.b64encode(content.encode("utf-8")).decode("ascii")}
        if sha:
            payload["sha"] = sha
        try:
            value = _request(f"/contents/{path}", payload, method="PUT")
            return content, value["commit"]["sha"]
        except urllib.error.HTTPError as exc:
            # Multiple workflows can legitimately checkpoint the same durable
            # outbox. Re-read the newest blob and retry instead of failing the run.
            if exc.code not in (409, 422):
                raise
            time.sleep(min(0.25 * (attempt + 1), 2.0))
    raise RuntimeError("X outbox remained busy after concurrent update retries")


def load_archive(day: str) -> str:
    _ensure_branch()
    raw, _ = _read(f"data/x_post_delivery/{day}_posts.jsonl")
    return raw


def publish_archive(day: str, local: str) -> str:
    def merge(old):
        rows, seen = [], set()
        for line in (old + "\n" + local).splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            # First selected card wins, matching the one-post-per-race policy.
            key = (row.get("day"), str(row.get("jcd")).zfill(2), int(row.get("rno") or 0), bool(row.get("resend")))
            if key not in seen:
                seen.add(key)
                rows.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
        return "\n".join(rows) + "\n"
    _, commit = _update(f"data/x_post_delivery/{day}_posts.jsonl", merge)
    return commit


def load_update_archive(day: str) -> str:
    _ensure_branch()
    raw, _ = _read(f"data/x_post_delivery/{day}_updates.jsonl")
    return raw


def publish_update_archive(day: str, local: str) -> str:
    """Publish one exhibition revision per race to the durable outbox branch."""
    def merge(old):
        rows, seen = [], set()
        for line in (old + "\n" + local).splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            key = (row.get("day"), str(row.get("jcd")).zfill(2), int(row.get("rno") or 0))
            if key not in seen:
                seen.add(key)
                rows.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
        return "\n".join(rows) + "\n"
    _, commit = _update(f"data/x_post_delivery/{day}_updates.jsonl", merge)
    return commit


def merge_state(remote: dict, local: dict) -> dict:
    result = {**remote, **local}
    for field in ("sent_races", "x_posted_races", "x_result_races", "x_featured_races", "x_exhibition_update_races"):
        result[field] = sorted(set(remote.get(field) or []) | set(local.get(field) or []))
    result["x_post_ids"] = {**(remote.get("x_post_ids") or {}), **(local.get("x_post_ids") or {})}
    result["x_result_post_ids"] = {**(remote.get("x_result_post_ids") or {}), **(local.get("x_result_post_ids") or {})}
    result["x_featured_modes"] = {**(remote.get("x_featured_modes") or {}), **(local.get("x_featured_modes") or {})}
    result["x_exhibition_update_ids"] = {**(remote.get("x_exhibition_update_ids") or {}), **(local.get("x_exhibition_update_ids") or {})}
    # An older legacy checkout must not replace newer native acknowledgement
    # receipts or change their immutable post IDs during a main checkpoint.
    native = dict(remote.get("x_v2_receipts") or {})
    for key, row in (local.get("x_v2_receipts") or {}).items():
        prior = native.get(key) or {}
        if prior.get("status") == "sent":
            continue
        if row.get("status") == "sent" or row.get("updated_at", row.get("claimed_at", "")) >= prior.get("updated_at", prior.get("claimed_at", "")):
            native[key] = row
    if native:
        result["x_v2_receipts"] = native
        for row in native.values():
            if row.get("status") != "sent" or not str(row.get("post_id", "")).isdigit():
                continue
            original = row["row"]
            race = f'{original["day"]}:{str(original["jcd"]).zfill(2)}:{int(original["rno"])}'
            field = "x_post_ids" if row["phase"] == "prediction" else "x_result_post_ids"
            result[field][race] = row["post_id"]
    # A confirmed receipt always wins over an interrupted attempt.
    attempts = {**(remote.get("x_attempts") or {}), **(local.get("x_attempts") or {})}
    for key in result["x_posted_races"]:
        attempts.pop(key, None)
    result["x_attempts"] = attempts
    exhibition_attempts = {**(remote.get("x_exhibition_attempts") or {}), **(local.get("x_exhibition_attempts") or {})}
    for key in result["x_exhibition_update_races"]:
        exhibition_attempts.pop(key, None)
    result["x_exhibition_attempts"] = exhibition_attempts
    result_attempts = {**(remote.get("x_result_attempts") or {}), **(local.get("x_result_attempts") or {})}
    for key in result["x_result_races"]:
        result_attempts.pop(key, None)
    result["x_result_attempts"] = result_attempts
    # A stale runtime checkout can still contain an older retryable attempt.
    # The native receipt's owner remains authoritative until it is resolved.
    for row in native.values():
        original = row["row"]
        race = f'{original["day"]}:{str(original["jcd"]).zfill(2)}:{int(original["rno"])}'
        field = "x_attempts" if row["phase"] == "prediction" else "x_result_attempts"
        if row.get("status") == "sent":
            result[field].pop(race, None)
            continue
        matching = [state.get(field, {}).get(race) for state in (remote, local)]
        matching = [attempt for attempt in matching if attempt and attempt.get("id") == row.get("owner")]
        if matching:
            result[field][race] = max(matching, key=lambda attempt:attempt.get("retry_at", attempt.get("at", "")))
        else:
            result[field][race] = {"id":row["owner"], "status":"blocked", "attempt":row["attempt"]}
    return result


def load_state(day: str) -> dict:
    _ensure_branch()
    raw, _ = _read(f"data/x_post_delivery/{day}.json")
    return json.loads(raw) if raw else {}


def publish_state(day: str, state: dict) -> tuple[dict, str]:
    def merge(old):
        value = merge_state(json.loads(old) if old else {}, state)
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    content, commit = _update(f"data/x_post_delivery/{day}.json", merge)
    return json.loads(content), commit
