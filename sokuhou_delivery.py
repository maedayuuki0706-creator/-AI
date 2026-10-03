"""Durable, fail-closed delivery of Sokuhou alerts.

Reserve each AI/day/venue/race on a separate Git branch BEFORE calling Discord.
An interrupted or ambiguous POST is held for review, never blindly retried.
Only an explicit rate-limit rejection is safe to retry automatically.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from discord_notification_policy import message_payload

POLICY = Path("sokuhou_policy.json")
BRANCH = "sokuhou-delivery-state"
API = "https://api.github.com/repos/maedayuuki0706-creator/-AI"


def policy() -> dict:
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    if not isinstance(value.get("enabled"), bool):
        raise ValueError("Sokuhou policy must explicitly set enabled")
    cutoff = datetime.fromisoformat(value["resume_after"])
    if cutoff.tzinfo is None:
        raise ValueError("Sokuhou resume_after needs a timezone")
    return value


def paused() -> bool:
    return os.getenv("SOKUHOU_PAUSED", "").lower() in {"1", "true"} or not policy()["enabled"]


def eligible(row: dict) -> bool:
    """Do not replay old, possibly already posted hits after the incident."""
    cutoff = datetime.fromisoformat(policy()["resume_after"])
    close = datetime.strptime(row["day"] + " " + row["deadline"], "%Y%m%d %H:%M")
    from zoneinfo import ZoneInfo
    return close.replace(tzinfo=ZoneInfo("Asia/Tokyo")) >= cutoff


def _request(path, payload=None, *, method="GET"):
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Sokuhou durable receipts require GITHUB_TOKEN; no alert sent")
    request = urllib.request.Request(
        API + path, method=method,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "User-Agent": "boat-ai-sokuhou"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


class ReceiptStore:
    def __init__(self):
        self.ready = False

    def ensure(self):
        if self.ready:
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
        self.ready = True

    @staticmethod
    def path(key):
        if not re.fullmatch(r"(?:normal|mid_odds|longshot|yuuki):\d{8}:\d{2}:\d{1,2}", key):
            raise ValueError("Invalid Sokuhou delivery identity")
        stream, day, jcd, rno = key.split(":")
        if not 1 <= int(jcd) <= 24 or not 1 <= int(rno) <= 12:
            raise ValueError("Invalid venue or race")
        return f"data/sokuhou_receipts/{day}/{stream}_{jcd}_{int(rno):02d}.json"

    def read(self, key):
        self.ensure()
        try:
            value = _request(f"/contents/{self.path(key)}?ref={BRANCH}")
            return json.loads(base64.b64decode(value["content"])), value["sha"]
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None, None
            raise

    def write(self, key, value, sha):
        payload = {"message": f"Checkpoint Sokuhou {key} {value['status']}", "branch": BRANCH,
                   "content": base64.b64encode((json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()).decode()}
        if sha:
            payload["sha"] = sha
        for attempt in range(4):
            try:
                result = _request(f"/contents/{self.path(key)}", payload, method="PUT")
                return result["content"]["sha"]
            except urllib.error.HTTPError as exc:
                if exc.code not in (409, 422):
                    raise
                current, current_sha = self.read(key)
                if current == value:
                    return current_sha
                if current_sha != sha or attempt == 3:
                    raise
                # Another race advanced the branch, but this file is unchanged.
                time.sleep(.2 * (attempt + 1))


STORE = ReceiptStore()


def send_confirmed(content: str) -> dict:
    """Wait for Discord's message ID; never retry an ambiguous HTTP request."""
    url = os.getenv("DISCORD_HIT_WEBHOOK_URL", "").strip()
    if not url:
        raise RuntimeError("DISCORD_HIT_WEBHOOK_URL is missing")
    parts = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parts.query))
    query["wait"] = "true"
    url = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
    payload = message_payload(content, notify_everyone=True)
    payload["username"] = "速報くん"
    request = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(),
                                    headers={"Content-Type": "application/json", "User-Agent": "boat-ai-sokuhou"}, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        message = json.load(response)
    if not isinstance(message, dict) or not str(message.get("id", "")).isdigit():
        raise RuntimeError("Discord acknowledgement has no message ID")
    return {"id": str(message["id"])}


def deliver(key: str, content: str, record: dict, *, sender=None, store=None, now=None) -> dict:
    """Return durable state; sending/uncertain/failed requires operator review."""
    store = store or STORE
    now = now or datetime.now(timezone.utc)
    old, sha = store.read(key)
    if old:
        if old.get("key") != key:
            raise ValueError("Receipt identity mismatch")
        if old.get("status") != "retry":
            return old
        if int(old.get("attempt", 0)) >= 3 or now < datetime.fromisoformat(old["retry_at"]):
            return old
    claim = {"key": key, "status": "sending", "owner": uuid.uuid4().hex,
             "attempt": int((old or {}).get("attempt", 0)) + 1,
             "claimed_at": now.isoformat(), "run_id": os.getenv("GITHUB_RUN_ID", "local"),
             "content_sha256": hashlib.sha256(content.encode()).hexdigest(), "record": record}
    try:
        sha = store.write(key, claim, sha)
    except urllib.error.HTTPError as exc:
        if exc.code not in (409, 422):
            raise
        # Another process owns this race. No POST from this process.
        other, _ = store.read(key)
        if other is None:
            raise RuntimeError("Could not reserve Sokuhou receipt") from None
        return other
    try:
        message = (sender or send_confirmed)(content)
        if not isinstance(message, dict) or not str(message.get("id", "")).isdigit():
            raise RuntimeError("Discord acknowledgement has no message ID")
    except Exception as exc:
        code = exc.code if isinstance(exc, urllib.error.HTTPError) else None
        status = "retry" if code == 429 and claim["attempt"] < 3 else "failed" if code and 400 <= code < 500 else "uncertain"
        result = {**claim, "status": status, "error_type": type(exc).__name__, "http_status": code}
        if status == "retry":
            try:
                delay = float(json.loads(exc.read()).get("retry_after", 60))
            except (ValueError, TypeError):
                delay = 60
            result["retry_at"] = (now + timedelta(seconds=max(60, delay))).isoformat()
        # Do not log exception text: it may contain the secret webhook URL.
        store.write(key, result, sha)
        print(f"::error::Sokuhou {key} status={status} error={type(exc).__name__}", flush=True)
        return result
    result = {**claim, "status": "sent", "message_id": str(message["id"]),
              "sent_at": datetime.now(timezone.utc).isoformat()}
    # If this write fails, the persistent 'sending' claim still blocks reposts.
    try:
        store.write(key, result, sha)
    except Exception:
        recovery = Path("data/sokuhou_recovery") / (key.replace(":", "_") + ".json")
        recovery.parent.mkdir(parents=True, exist_ok=True)
        with recovery.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        raise
    return result
