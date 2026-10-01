"""Publish selected live prediction posts to X and mirror them to Discord.

Only genuinely selected live predictions are eligible. Discord remains the
copy-ready mirror and fallback while X posting is handled automatically.
"""
from __future__ import annotations

from datetime import datetime
import argparse
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid
import urllib.error
import urllib.request

from direct_discord_notify import JST
from x_api_client import credentials_configured, post_text as post_to_x
from x_delivery_policy import SOURCE_SAFETY_LEAD_SECONDS, validate_live_row, weighted_length
import x_delivery_store as outbox

STATE_DIR = Path("data/x_post_delivery")
WEBHOOK_ENV = "X_POST_DISCORD_WEBHOOK_URL"
BASE_HASHTAGS = "#競艇 #ボートレース #競艇予想 #無料予想"
FORMAT_VERSION = "v2-formation"
RENDER_SYNC_URL = "https://boat-ai-navi-public.onrender.com/api/x-sync"
RENDER_RESULT_URL = "https://boat-ai-navi-public.onrender.com/api/x-result"
# Settled results are published as replies to the original X prediction.
_RECEIPTS_DIRTY: set[str] = set()
_REPORTED_BLOCKS: set[str] = set()
_STATE_LOCK = threading.RLock()
_WORKER_LOCK = threading.Lock()
_WORKER: threading.Thread | None = None
_PENDING_DAYS: set[str] = set()
_LAST_WARM = 0.0

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
            value.setdefault("x_posted_races", [])
            value.setdefault("x_post_ids", {})
            value.setdefault("x_result_races", [])
            value.setdefault("x_result_post_ids", {})
            value.setdefault("x_result_attempts", {})
            return value
    except (OSError, ValueError):
        pass
    return {"day": day, "sent_races": [], "x_posted_races": [], "x_post_ids": {},
            "x_result_races": [], "x_result_post_ids": {}, "x_result_attempts": {},
            "updated_at": None}


def _save(day: str, state: dict) -> None:
    with _STATE_LOCK:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state = outbox.merge_state(_load(day), state)
        state["updated_at"] = datetime.now(JST).isoformat()
        path = _state_path(day)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)


def request_sync(day: str | None = None) -> None:
    """Wake one background sender, keeping X/API latency off Discord's path."""
    global _WORKER
    day = str(day or datetime.now(JST).strftime("%Y%m%d"))
    if os.getenv("X_ASYNC_DELIVERY") != "1":
        sync_archived_via_render(day)
        sync_results_via_render(day)
        return
    with _WORKER_LOCK:
        _PENDING_DAYS.add(day)
        if _WORKER is not None and _WORKER.is_alive():
            return
        def work():
            global _WORKER, _LAST_WARM
            while True:
                with _WORKER_LOCK:
                    if not _PENDING_DAYS:
                        _WORKER = None
                        return
                    pending = sorted(_PENDING_DAYS)
                    _PENDING_DAYS.clear()
                for pending_day in pending:
                    try:
                        if outbox.configured() and time.monotonic() - _LAST_WARM >= 240:
                            check_render_ready()
                            _LAST_WARM = time.monotonic()
                        sync_archived_via_render(pending_day)
                        sync_results_via_render(pending_day)
                    except Exception as exc:
                        print(f"::error::X outbox worker failed: {type(exc).__name__}", flush=True)
        _WORKER = threading.Thread(target=work, name="x-live-outbox", daemon=True)
        _WORKER.start()


def flush_pending(timeout: int = 180) -> None:
    worker = _WORKER
    if worker is not None:
        worker.join(timeout)
        if worker.is_alive():
            raise RuntimeError("X sender did not drain before the watcher checkpoint")


def _archive_post(record: dict, source: str, post: str, *, resend: bool = False) -> None:
    day = str(record.get("day") or "")
    if not day:
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / f"{day}_posts.jsonl"
    row = {
        "day": day,
        "jcd": str(record.get("jcd") or "").zfill(2),
        "rno": int(record.get("rno") or 0),
        "venue": record.get("venue"),
        "deadline": record.get("deadline"),
        "source": source,
        "format_version": FORMAT_VERSION,
        "resend": bool(resend),
        "post": post,
        "picks": _record_picks(record) or _unique_picks(record.get("x_picks") or []),
        "sent_at": datetime.now(JST).isoformat(),
    }
    if path.exists() and not resend:
        for line in path.read_text(encoding="utf-8").splitlines():
            old = json.loads(line)
            if _race_key(old) == _race_key(record) and not old.get("resend"):
                return
    previous = path.read_text(encoding="utf-8") if path.exists() else ""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(previous + json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


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
    if weighted_length(text) <= 280:
        return text
    trimmed = [line for line in lines if "展示・気象" not in line and not line.startswith("#")]
    text = "\n".join(trimmed).strip()
    if weighted_length(text) <= 280:
        return text
    trimmed = [line for line in trimmed if line and not line.startswith("🔔")]
    text = "\n".join(trimmed).strip()
    if weighted_length(text) <= 280:
        return text
    # Never silently remove tickets or the requested follow invitation.
    raise ValueError("X prediction exceeds 280 weighted characters")


def _wrap_for_discord(post: str, source: str) -> str:
    fence = chr(96) * 3
    return f"📱 **X投稿用 v2｜{source}**\nコピーしてそのまま投稿👇\n{fence}text\n{post}\n{fence}"


def _send_once(record: dict, source: str, post: str) -> bool:
    day = str(record.get("day") or "")
    key = _race_key(record)
    if not day or key.endswith(":0"):
        return False
    validate_live_row(
        {**record, "source": source, "sent_at": datetime.now(JST).isoformat()},
        min_lead_seconds=SOURCE_SAFETY_LEAD_SECONDS,
    )
    if not post or weighted_length(post) > 280:
        raise ValueError("invalid X prediction text")

    state = _load(day)
    sent = set(map(str, state.get("sent_races") or []))
    x_posted = set(map(str, state.get("x_posted_races") or []))
    if key in sent and key in x_posted:
        return False

    did_work = False

    # Write the outbox before any external send; a Discord outage must not
    # erase the X prediction or make it depend on the 23-minute watcher exit.
    _archive_post(record, source, post)

    if key not in x_posted:
        if outbox.configured():
            try:
                request_sync(day)
                did_work = True
            except Exception as exc:
                print(f"::error::X live checkpoint failed: {key} {type(exc).__name__}", flush=True)
            state = _load(day)
        elif credentials_configured():
            try:
                post_id = post_to_x(post)
                x_posted.add(key)
                state["x_posted_races"] = sorted(x_posted)
                state.setdefault("x_post_ids", {})[key] = post_id
                _save(day, state)
                print(f"X auto post sent: {source} {key} post_id={post_id}", flush=True)
                did_work = True
            except Exception as exc:
                print(
                    f"X auto post failed: {source} {key}: {type(exc).__name__}: {exc}",
                    flush=True,
                )
        else:
            print(f"X auto post skipped: credentials missing for {source} {key}", flush=True)

    if key not in sent:
        _send_discord(_wrap_for_discord(post, source))
        sent.add(key)
        state["sent_races"] = sorted(sent)
        _save(day, state)
        print(f"X Discord mirror sent: {source} {key}", flush=True)
        did_work = True

    return did_work


def _build_post(venue: str, rno: int, deadline: str, picks, *, label: str, score: int | None = None) -> str:
    compact = _compact_picks(picks)
    if not compact:
        return ""
    title = f"🟡 厳選中穴｜期待度 {int(score or 0)}/100" if score is not None else "🔥 AI厳選"
    return _fit_post([
        f"🚤無料予想｜{venue} {rno}R",
        f"⏰締切 {deadline}",
        "",
        title,
        "🎯 買い目",
        *compact,
        "",
        "📊 展示・気象・モーター反映済",
        "",
        "🔔 次の無料予想も配信します",
        "ぜひフォローお願いします！",
    ])


def send_selected_record(record: dict) -> bool:
    raw_picks = _record_picks(record)
    if not raw_picks:
        return False
    venue = record.get("venue") or str(record.get("jcd") or "")
    rno = int(record.get("rno") or 0)
    deadline = str(record.get("deadline") or "--:--")
    post = _build_post(venue, rno, deadline, raw_picks, label="厳選くん")
    return _send_once(record, "厳選くん", post)


def send_selected_mid(record: dict, payload: dict) -> bool:
    raw_picks = payload.get("picks") or []
    if not raw_picks:
        return False
    venue = record.get("venue") or str(record.get("jcd") or "")
    rno = int(record.get("rno") or 0)
    deadline = str(record.get("deadline") or "--:--")
    score = int(payload.get("score") or 0)
    post = _build_post(venue, rno, deadline, raw_picks, label="厳選中穴", score=score)
    enriched = dict(record)
    enriched["x_picks"] = raw_picks
    return _send_once(enriched, "厳選中穴", post)


def resend_live_race(day: str, jcd: str, rno: int) -> None:
    """Rebuild one live existing-main card and resend it in X v2 format."""
    import direct_discord_notify as base
    import detailed_discord_notify as cards

    jcd = str(jcd).zfill(2)
    rno = int(rno)
    analysis = base.analyze_official(day, jcd, rno)
    if not analysis:
        raise RuntimeError("live analysis unavailable")
    if int((analysis.get("preview") or {}).get("exhibition_count") or 0) < 6:
        raise RuntimeError("exhibition is not complete")

    times = base.deadlines(day, jcd)
    deadline = times[rno - 1] if len(times) >= rno else "--:--"
    selected = cards.displayed_picks_variable(analysis, True)
    picks = [row.get("combination") for row in selected if row.get("combination")]
    venue = base.VENUES.get(jcd, jcd)
    post = _build_post(venue, rno, deadline, picks, label="厳選くん")
    if not post:
        raise RuntimeError("no X picks generated")

    record = {
        "day": day,
        "jcd": jcd,
        "rno": rno,
        "venue": venue,
        "deadline": deadline,
    }
    _send_discord(_wrap_for_discord(post, "厳選くん｜再送"))
    _archive_post(record, "厳選くん", post, resend=True)
    print(f"X post {FORMAT_VERSION} resent {day} {jcd} {rno}R", flush=True)



def check_render_ready() -> dict:
    request = urllib.request.Request(
        RENDER_SYNC_URL.rsplit("/", 1)[0] + "/x-status",
        headers={"User-Agent": "boat-ai-x-preflight"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    if result.get("delivery_version") != 2 or not result.get("credentials_configured"):
        raise RuntimeError("Render X delivery v2 is not ready")
    return result


def _checkpoint(day: str, state: dict) -> tuple[dict, str]:
    _save(day, state)
    state = _load(day)
    _RECEIPTS_DIRTY.add(day)
    merged, commit = outbox.publish_state(day, state)
    _save(day, merged)
    _RECEIPTS_DIRTY.discard(day)
    return merged, commit


def sync_archived_via_render(day: str | None = None) -> int:
    """Deliver the durable outbox immediately and retry only definite failures.

    An interrupted/ambiguous attempt is held for reconciliation, rather than
    blindly reposted after a server or runner restart.
    """
    day = str(day or datetime.now(JST).strftime("%Y%m%d"))
    posts_path = STATE_DIR / f"{day}_posts.jsonl"
    state = _load(day)
    if day in _RECEIPTS_DIRTY:
        state, _ = _checkpoint(day, state)
    if not posts_path.exists():
        return 0

    candidates = {}
    for line in posts_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            validate_live_row(row)
            jcd = str(row.get("jcd") or "").zfill(2)
            rno = int(row.get("rno") or 0)
            if not re.fullmatch(r"(?:0[1-9]|1[0-9]|2[0-4])", jcd) or not 1 <= rno <= 12:
                continue
            key = _race_key(row)
            if key not in set(state.get("x_posted_races") or []):
                candidates.setdefault(key, row)
        except (ValueError, TypeError, AttributeError):
            continue
    if not candidates:
        return 0
    if not outbox.configured():
        raise RuntimeError("X delivery requires GITHUB_TOKEN for durable live checkpoints")

    check_render_ready()
    state = outbox.merge_state(outbox.load_state(day), state)
    _save(day, state)
    outbox.publish_archive(day, posts_path.read_text(encoding="utf-8"))
    sent_count = 0
    for key, row in candidates.items():
        if key in set(state.get("x_posted_races") or []):
            continue
        previous = (state.get("x_attempts") or {}).get(key) or {}
        if previous.get("status") in {"reserved", "uncertain", "blocked"}:
            if key not in _REPORTED_BLOCKS:
                print(f"::error::X delivery needs reconciliation: {key} status={previous['status']}", flush=True)
                _REPORTED_BLOCKS.add(key)
            continue
        if previous.get("status") == "retryable":
            elapsed = (datetime.now(JST) - datetime.fromisoformat(previous["at"])).total_seconds()
            if elapsed < 60:
                continue
        try:
            validate_live_row(row)
        except ValueError:
            continue
        attempt_id = uuid.uuid4().hex
        state.setdefault("x_attempts", {})[key] = {
            "id": attempt_id, "status": "reserved", "at": datetime.now(JST).isoformat(),
        }
        try:
            state, archive_ref = _checkpoint(day, state)
        except Exception:
            # No Render request has been made, so a later retry is safe even
            # if the GitHub checkpoint response itself was interrupted.
            state["x_attempts"][key]["status"] = "retryable"
            _save(day, state)
            raise
        body = json.dumps({"day": day, "jcd": row["jcd"], "rno": row["rno"],
                           "archive_ref": archive_ref, "attempt_id": attempt_id}).encode("utf-8")
        req = urllib.request.Request(
            RENDER_SYNC_URL, data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "User-Agent": "Boat-AI-Navi/github-x-sync-v2"}, method="POST",
        )
        result = None
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                result = json.loads(exc.read().decode("utf-8"))
            except Exception:
                pass
        except Exception as exc:
            print(f"::error::X sync response uncertain: {key} {type(exc).__name__}", flush=True)

        if isinstance(result, dict) and result.get("ok") and result.get("post_id"):
            state["x_posted_races"] = sorted(set(state.get("x_posted_races") or []) | {key})
            state.setdefault("x_post_ids", {})[key] = str(result["post_id"])
            state["x_attempts"].pop(key, None)
            sent_count += int(not result.get("already"))
            print(f"X sync ok: {key} post_id={result['post_id']}", flush=True)
        else:
            status = "uncertain"
            if isinstance(result, dict) and result.get("definitely_not_posted"):
                status = "retryable" if result.get("retryable") else "blocked"
            state["x_attempts"][key]["status"] = status
            print(f"::error::X sync failed: {key} status={status}", flush=True)
        # Persist each receipt immediately; do not wait for all races or exit.
        state, _ = _checkpoint(day, state)
    return sent_count



def _result_due(row: dict) -> bool:
    day = str(row.get("day") or "")
    deadline = str(row.get("deadline") or "")
    try:
        close = datetime.strptime(day + " " + deadline, "%Y%m%d %H:%M").replace(tzinfo=JST)
    except (TypeError, ValueError):
        return False
    return datetime.now(JST) > close


def sync_results_via_render(day: str | None = None) -> int:
    """Publish settled X prediction results as replies to the original post."""
    day = str(day or datetime.now(JST).strftime("%Y%m%d"))
    posts_path = STATE_DIR / f"{day}_posts.jsonl"
    if not posts_path.exists() or not outbox.configured():
        return 0

    state = outbox.merge_state(outbox.load_state(day), _load(day))
    _save(day, state)
    x_posted = set(map(str, state.get("x_posted_races") or []))
    x_result = set(map(str, state.get("x_result_races") or []))
    if not x_posted - x_result:
        return 0

    rows = {}
    raw_archive = posts_path.read_text(encoding="utf-8")
    for line in raw_archive.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        key = _race_key(row)
        if (
            key in x_posted
            and key not in x_result
            and not bool(row.get("resend"))
            and str(row.get("source") or "") in {"厳選くん", "厳選中穴"}
            and _result_due(row)
        ):
            rows.setdefault(key, row)
    if not rows:
        return 0

    outbox.publish_archive(day, raw_archive)
    sent_count = 0
    for key, row in rows.items():
        previous = (state.get("x_result_attempts") or {}).get(key) or {}
        if previous.get("status") in {"reserved", "uncertain", "blocked"}:
            continue
        if previous.get("status") == "retryable":
            try:
                elapsed = (datetime.now(JST) - datetime.fromisoformat(previous["at"])).total_seconds()
            except Exception:
                elapsed = 999
            if elapsed < 30:
                continue

        attempt_id = uuid.uuid4().hex
        state.setdefault("x_result_attempts", {})[key] = {
            "id": attempt_id, "status": "reserved", "at": datetime.now(JST).isoformat(),
        }
        state, archive_ref = _checkpoint(day, state)
        body = json.dumps({
            "day": day,
            "jcd": row.get("jcd"),
            "rno": row.get("rno"),
            "archive_ref": archive_ref,
            "attempt_id": attempt_id,
        }).encode("utf-8")
        req = urllib.request.Request(
            RENDER_RESULT_URL,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "User-Agent": "Boat-AI-Navi/github-x-result-v1"},
            method="POST",
        )
        result = None
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                result = json.loads(exc.read().decode("utf-8"))
            except Exception:
                pass
        except Exception as exc:
            print(f"::error::X result response uncertain: {key} {type(exc).__name__}", flush=True)

        if isinstance(result, dict) and result.get("ok") and result.get("post_id"):
            state["x_result_races"] = sorted(set(state.get("x_result_races") or []) | {key})
            state.setdefault("x_result_post_ids", {})[key] = str(result["post_id"])
            state.setdefault("x_result_attempts", {}).pop(key, None)
            sent_count += int(not result.get("already"))
            print(f"X result sync ok: {key} post_id={result['post_id']}", flush=True)
        else:
            status = "uncertain"
            if isinstance(result, dict) and result.get("definitely_not_posted"):
                status = "retryable" if result.get("retryable") else "blocked"
            state.setdefault("x_result_attempts", {}).setdefault(key, {
                "id": attempt_id, "at": datetime.now(JST).isoformat(),
            })["status"] = status
            print(f"X result sync pending/failed: {key} status={status}", flush=True)
        state, _ = _checkpoint(day, state)
    return sent_count


def smoke_test() -> None:
    now = datetime.now(JST)
    sample = [
        "1-2-3", "1-2-4", "1-3-2", "1-3-4", "1-4-2", "1-4-3",
        "2-1-3", "2-1-4", "1-5-2", "1-5-3",
    ]
    post = _build_post("常滑", 8, "14:32", sample, label="厳選くん")
    expected = ["1-234-234", "2-1-34", "1-5-23"]
    for line in expected:
        if line not in post:
            raise RuntimeError(f"X v2 formation missing: {line}")
    _send_discord(_wrap_for_discord(post, "新フォーマット確認"))
    print(f"X post Discord {FORMAT_VERSION} smoke test sent at {now.isoformat()}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--sync-render", action="store_true")
    parser.add_argument("--check-render", action="store_true")
    parser.add_argument("--resend-race", action="store_true")
    parser.add_argument("--day")
    parser.add_argument("--jcd")
    parser.add_argument("--rno", type=int)
    args = parser.parse_args()
    if args.resend_race:
        if not (args.day and args.jcd and args.rno):
            parser.error("--resend-race requires --day --jcd --rno")
        resend_live_race(args.day, args.jcd, args.rno)
    elif args.check_render:
        print(json.dumps(check_render_ready(), sort_keys=True))
        outbox._ensure_branch()
        outbox._update("data/x_post_delivery/preflight.json", lambda old: json.dumps({
            "checked_at": datetime.now(JST).isoformat(), "delivery_version": 2,
            "workflow_run": os.getenv("GITHUB_RUN_ID", ""),
        }, sort_keys=True) + "\n")
        print("X durable outbox write access: ready")
    elif args.sync_render:
        count = sync_archived_via_render(args.day)
        results = sync_results_via_render(args.day)
        print(f"X Render sync complete: posted={count} results={results}", flush=True)
    elif args.smoke_test:
        smoke_test()
