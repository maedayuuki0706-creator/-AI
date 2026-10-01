"""Durable X outbox on its own Git branch, independent of the long watcher.

Only the existing Actions job writes this branch using its repository token.
Render reads immutable commits, so neither raw-file caching nor main-branch
deployment delays hold up a live prediction. No X credentials leave Render.
"""
from __future__ import annotations

import base64
import json
import os
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
    for _ in range(3):
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
            if exc.code != 409:
                raise
    raise RuntimeError("X outbox changed concurrently; retry next pass")


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


def merge_state(remote: dict, local: dict) -> dict:
    result = {**remote, **local}
    for field in ("sent_races", "x_posted_races"):
        result[field] = sorted(set(remote.get(field) or []) | set(local.get(field) or []))
    result["x_post_ids"] = {**(remote.get("x_post_ids") or {}), **(local.get("x_post_ids") or {})}
    # A confirmed receipt always wins over an interrupted attempt.
    attempts = {**(remote.get("x_attempts") or {}), **(local.get("x_attempts") or {})}
    for key in result["x_posted_races"]:
        attempts.pop(key, None)
    result["x_attempts"] = attempts
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
