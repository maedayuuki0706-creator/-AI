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
BASE_HASHTAGS = "#競艇 #ボートレース #競艇予想 #無料予想"

def _hashtags(venue: str = "") -> str:
    venue = str(venue or "").strip()
    local = f" #{venue} #ボートレース{venue}" if venue else ""
    return BASE_HASHTAGS + local


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


def _compact_picks(values) -> list[str]:
    """Compact exact trifectas without inventing unselected combinations.

    Example:
      1-2-3, 1-2-4, 1-3-2, 1-3-4, 1-4-2, 1-4-3
      -> 1-234-234

    Remaining same-prefix rows become forms such as 2-1-34 or 1-5-23.
    Already-compact formations are preserved.
    """
    picks = _unique_picks(values)
    exact = []
    preformatted = []
    for index, pick in enumerate(picks):
        if re.fullmatch(r"[1-6]-[1-6]-[1-6]", pick):
            a, b, d = map(int, pick.split("-"))
            if len({a, b, d}) == 3:
                exact.append((index, a, b, d, pick))
        else:
            preformatted.append((index, pick))

    remaining = {(a, b, d): index for index, a, b, d, _ in exact}
    compacted = []

    # First collapse complete symmetric second/third sets for a fixed head.
    # This is what safely turns the six 1-234-234 permutations into one line.
    for head in range(1, 7):
        head_pairs = {(b, d) for (a, b, d) in remaining if a == head}
        lanes = sorted({lane for pair in head_pairs for lane in pair if lane != head})
        best = None
        # At six boats the powerset is tiny; prefer the largest complete set.
        from itertools import combinations
        for size in range(len(lanes), 1, -1):
            for subset in combinations(lanes, size):
                required = {(b, d) for b in subset for d in subset if b != d}
                if required and required.issubset(head_pairs):
                    first_index = min(remaining[(head, b, d)] for b, d in required)
                    best = (first_index, tuple(subset), required)
                    break
            if best:
                break
        if best:
            first_index, subset, required = best
            digits = "".join(map(str, subset))
            compacted.append((first_index, f"{head}-{digits}-{digits}"))
            for b, d in required:
                remaining.pop((head, b, d), None)

    # Then collapse remaining tickets by exact first-second prefix.
    by_prefix = {}
    for (a, b, d), index in remaining.items():
        by_prefix.setdefault((a, b), []).append((index, d))
    consumed = set()
    for (a, b), rows in by_prefix.items():
        rows = sorted(rows)
        thirds = []
        for _, d in rows:
            if d not in thirds:
                thirds.append(d)
        if len(thirds) >= 2:
            compacted.append((rows[0][0], f"{a}-{b}-{''.join(map(str, thirds))}"))
            consumed.update((a, b, d) for _, d in rows)

    for key, index in remaining.items():
        if key in consumed:
            continue
        a, b, d = key
        compacted.append((index, f"{a}-{b}-{d}"))

    compacted.extend(preformatted)
    compacted.sort(key=lambda item: item[0])

    out = []
    seen = set()
    for _, pick in compacted:
        if pick not in seen:
            seen.add(pick)
            out.append(pick)
    return out


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
    picks = _compact_picks(_record_picks(record))
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
        "🎯 買い目",
        *picks,
        "",
        "📊 展示・気象・モーター反映済",
        _hashtags(venue),
    ])
    return _send_once(record, "厳選くん", post)


def send_selected_mid(record: dict, payload: dict) -> bool:
    picks = _compact_picks(payload.get("picks") or [])
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
        "🎯 買い目",
        *picks,
        "",
        "📊 展示・気象・モーター反映済",
        _hashtags(venue),
    ])
    return _send_once(record, "厳選中穴", post)


def smoke_test() -> None:
    now = datetime.now(JST)
    sample = _compact_picks([
        "1-2-3", "1-2-4", "1-3-2", "1-3-4", "1-4-2", "1-4-3",
        "2-1-3", "2-1-4", "1-5-2", "1-5-3",
    ])
    post = _fit_post([
        "🚤無料予想｜常滑 8R",
        "⏰締切 14:32",
        "",
        "🔥 AI厳選",
        "🎯 買い目",
        *sample,
        "",
        "📊 展示・気象・モーター反映済",
        _hashtags("常滑"),
    ])
    _send_discord(_wrap_for_discord(post, "新フォーマットテスト"))
    print(f"X post Discord smoke test sent at {now.isoformat()}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    if args.smoke_test:
        smoke_test()
