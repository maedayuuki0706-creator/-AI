"""Send copy-ready X prediction drafts to the dedicated Discord channel.

This does NOT post to X directly. It mirrors only genuinely selected live
predictions to Discord so the operator can copy/paste them to X.
"""
from __future__ import annotations

from datetime import datetime
import argparse
import json
import os
from pathlib import Path
import re
import urllib.request

from direct_discord_notify import JST

STATE_DIR = Path("data/x_post_delivery")
WEBHOOK_ENV = "X_POST_DISCORD_WEBHOOK_URL"
BASE_HASHTAGS = "#競艇 #ボートレース #競艇予想 #無料予想"\n\ndef _hashtags(venue: str = "") -> str:\n    venue = str(venue or "").strip()\n    local = f" #{venue} #ボートレース{venue}" if venue else ""\n    return BASE_HASHTAGS + local


def _state_path(day: str) -> Path:
    return STATE_DIR / f"{day}.json"


def _load(day: str) -> dict:
    path = _state_path(day)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            value.setdefault("sent_races", [])
            return value
    except (OSError, ValueError):
        pass
    return {"day": day, "sent_races": [], "updated_at": None}


def _save(day: str, state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(JST).isoformat()
    path = _state_path(day)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _race_key(record: dict) -> str:
    day = str(record.get("day") or "")
    jcd = str(record.get("jcd") or "").zfill(2)
    rno = int(record.get("rno") or 0)
    return f"{day}:{jcd}:{rno}"


def _send_discord(content: str) -> None:
    url = os.getenv(WEBHOOK_ENV, "").strip()
    if not url:
        raise RuntimeError(f"{WEBHOOK_ENV} is missing")
    data = json.dumps(
        {"content": content, "allowed_mentions": {"parse": []}},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Boat-AI-Navi/x-draft-v1",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status not in (200, 204):
            raise RuntimeError(f"Discord HTTP {response.status}")


def _unique_picks(values) -> list[str]:
    out = []
    seen = set()
    for value in values or []:
        if isinstance(value, dict):
            value = value.get("combination")
        text = str(value or "").strip().replace(chr(96), "")
        if not text or text in seen:
            continue
        if re.fullmatch(r"[1-6]-[1-6]-[1-6]", text) or re.fullmatch(r"[1-6]{1,3}-[1-6]{1,5}(?:=|-)[1-6]{1,5}", text):
            seen.add(text)
            out.append(text)
    return out


def _record_picks(record: dict) -> list[str]:
    picks = _unique_picks((record.get("main") or []) + (record.get("cover") or []))
    if picks:
        return picks
    return _unique_picks(record.get("virtual_bets") or [])


def _fit_post(lines: list[str]) -> str:
    text = "\n".join(lines).strip()
    if len(text) <= 280:
        return text

    trimmed = [line for line in lines if not line.startswith("展示・気象")]
    text = "\n".join(trimmed).strip()
    if len(text) <= 280:
        return text
    trimmed = [line for line in trimmed if not line.startswith("#")]
    text = "\n".join(trimmed).strip()
    if len(text) <= 280:
        return text

    header = trimmed[:4]
    tokens = []
    for line in trimmed[4:]:
        if line.startswith("#"):
            continue
        tokens.extend(line.split())
    body = []
    for token in tokens:
        candidate = "\n".join(header + [" ".join(body + [token])]).strip()
        if len(candidate) > 276:
            break
        body.append(token)
    return "\n".join(header + ([" ".join(body)] if body else [])).strip()


def _wrap_for_discord(post: str, source: str) -> str:
    fence = chr(96) * 3
    return f"📱 **X投稿用｜{source}**\nコピーしてそのまま投稿👇\n{fence}text\n{post}\n{fence}"


def _send_once(record: dict, source: str, post: str) -> bool:
    day = str(record.get("day") or "")
    key = _race_key(record)
    if not day or key.endswith(":0"):
        return False

    state = _load(day)
    sent = set(map(str, state.get("sent_races") or []))
    if key in sent:
        return False

    _send_discord(_wrap_for_discord(post, source))
    sent.add(key)
    state["sent_races"] = sorted(sent)
    _save(day, state)
    print(f"X draft sent: {source} {key}", flush=True)
    return True


def send_selected_record(record: dict) -> bool:
    picks = _record_picks(record)
    if not picks:
        return False
    venue = record.get("venue") or str(record.get("jcd") or "")
    rno = int(record.get("rno") or 0)
    deadline = str(record.get("deadline") or "--:--")
    post = _fit_post([
        f"🚤無料予想｜{venue} {rno}R",
        f"⏰締切 {deadline}",
        "",
        "🔥 AI厳選",
        "買い目 " + " ".join(picks),
        "",
        "展示・気象・モーター等を反映した直前予想。",
        HASHTAGS,
    ])
    return _send_once(record, "厳選くん", post)


def send_selected_mid(record: dict, payload: dict) -> bool:
    picks = _unique_picks(payload.get("picks") or [])
    if not picks:
        return False
    venue = record.get("venue") or str(record.get("jcd") or "")
    rno = int(record.get("rno") or 0)
    deadline = str(record.get("deadline") or "--:--")
    score = int(payload.get("score") or 0)
    post = _fit_post([
        f"🚤無料予想｜{venue} {rno}R",
        f"⏰締切 {deadline}",
        "",
        f"🟡 厳選中穴｜期待度 {score}/100",
        "買い目 " + " ".join(picks),
        "",
        "展示・気象・モーター等を反映した直前予想。",
        HASHTAGS,
    ])
    return _send_once(record, "厳選中穴", post)


def smoke_test() -> None:
    now = datetime.now(JST)
    post = _fit_post([
        "🚤無料予想｜X投稿用 接続テスト",
        "",
        "✅ 厳選くん＋厳選中穴の投稿文連携OK",
        "実運用は直前予想が厳選条件を通った時だけ自動でここに届きます。",
        "",
        HASHTAGS,
    ])
    _send_discord(_wrap_for_discord(post, "接続テスト"))
    print(f"X post Discord smoke test sent at {now.isoformat()}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    if args.smoke_test:
        smoke_test()
