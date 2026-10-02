"""Post exhibition-confirmed Omura revisions to X for 2026-10-02.

The pre-race base tweets already exist. This job waits for all six exhibition
times, rebuilds the card, then replies with a 10-point main section and up to
8 alternate-head covers. It never posts inside the ten-minute cutoff.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import urllib.request
import uuid

import direct_discord_notify as base
import x_delivery_store as outbox
from x_delivery_policy import weighted_length

DAY = "20261002"
JCD = "24"
RACES = range(6, 13)
MIN_LEAD_SECONDS = 11 * 60
MAX_LEAD_SECONDS = 45 * 60
MAIN_POINTS = 10
COVER_POINTS = 8
ALT_HEAD_THRESHOLD = 0.01
UPDATE_URL = "https://boat-ai-navi-public.onrender.com/api/x-exhibition"
LOCAL_DIR = Path("data/x_post_delivery")


def race_key(rno: int) -> str:
    return f"{DAY}:{JCD}:{int(rno)}"


def deadline_dt(deadline: str) -> datetime:
    return datetime.strptime(f"{DAY} {deadline}", "%Y%m%d %H:%M").replace(tzinfo=base.JST)


def unique(values):
    out, seen = [], set()
    for value in values:
        value = str(value or "")
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def row_rank(row: dict) -> tuple:
    return (
        float(row.get("probability") or 0),
        float(row.get("expected_value") or 0),
        float(row.get("odds") or 0),
    )


def cover_rank(row: dict) -> tuple:
    prob = float(row.get("probability") or 0)
    ev = max(0.25, min(float(row.get("expected_value") or 0), 3.0))
    return (prob * ev, prob, float(row.get("expected_value") or 0), float(row.get("odds") or 0))


def build_plan(analysis: dict) -> tuple[list[str], list[str]]:
    rows = [
        row for row in (analysis.get("trifecta") or [])
        if len(str(row.get("combination") or "").split("-")) == 3
    ]
    rows.sort(key=row_rank, reverse=True)
    main = unique(row.get("combination") for row in rows)[:MAIN_POINTS]
    used = set(main)

    heads = {str(k): float(v) for k, v in (analysis.get("heads") or {}).items()}
    eligible = [
        lane for lane, probability in sorted(
            ((lane, prob) for lane, prob in heads.items() if lane != "1"),
            key=lambda item: item[1],
            reverse=True,
        )
        if probability >= ALT_HEAD_THRESHOLD
    ]

    cover = []
    for lane in eligible:
        candidates = [
            row for row in rows
            if str(row.get("combination") or "").startswith(f"{lane}-")
            and str(row.get("combination") or "") not in used
        ]
        if not candidates:
            continue
        best = max(candidates, key=cover_rank)
        combo = str(best["combination"])
        cover.append(combo)
        used.add(combo)

    for row in sorted(rows, key=cover_rank, reverse=True):
        if len(cover) >= COVER_POINTS:
            break
        combo = str(row.get("combination") or "")
        if combo in used or combo.startswith("1-"):
            continue
        cover.append(combo)
        used.add(combo)

    if len(cover) < COVER_POINTS:
        for row in rows:
            if len(cover) >= COVER_POINTS:
                break
            combo = str(row.get("combination") or "")
            if combo in used:
                continue
            cover.append(combo)
            used.add(combo)

    return main, cover[:COVER_POINTS]


def compact_exact(picks: list[str]) -> list[str]:
    # Keep exact tickets visible. Ten + eight still fits comfortably on X.
    return picks


def rationale(analysis: dict) -> str:
    inputs = list(analysis.get("inputs") or [])
    heads = {str(k): float(v) for k, v in (analysis.get("heads") or {}).items()}
    alt = sorted(
        ((lane, p) for lane, p in heads.items() if lane != "1" and p >= ALT_HEAD_THRESHOLD),
        key=lambda item: item[1],
        reverse=True,
    )
    alt_text = " ".join(f"{lane}={p*100:.1f}%" for lane, p in alt[:3])

    exhibition = [b for b in inputs if b.get("exhibition_time") is not None]
    fastest = min(exhibition, key=lambda b: float(b["exhibition_time"])) if exhibition else None
    st_rows = [b for b in inputs if b.get("exhibition_st") is not None]
    best_st = min(st_rows, key=lambda b: float(b["exhibition_st"])) if st_rows else None
    motors = [b for b in inputs if b.get("motor_top2_rate") is not None]
    best_motor = max(motors, key=lambda b: float(b["motor_top2_rate"])) if motors else None

    signals = []
    if fastest:
        signals.append(f"T①{fastest['lane']}")
    if best_st:
        signals.append(f"ST①{best_st['lane']}")
    if best_motor:
        signals.append(f"M①{best_motor['lane']}")
    return f"逆転頭 {alt_text}｜{'・'.join(signals)}".strip("｜")


def make_post(rno: int, deadline: str, main: list[str], cover: list[str], analysis: dict) -> str:
    lines = [
        f"🚤大村 {rno}R｜展示反映版｜締切 {deadline}",
        f"🎯本線 {len(main)}点",
        " ".join(compact_exact(main)),
        f"🛡️抑え・逆転候補 {len(cover)}点",
        " ".join(compact_exact(cover)),
        f"👀{rationale(analysis)}",
    ]
    text = "\n".join(lines)
    if weighted_length(text) <= 280:
        return text

    # If the exact list is too long, compact only the rationale, never the tickets.
    lines[-1] = "👀展示・ST・モーター・頭確率を反映"
    text = "\n".join(lines)
    if weighted_length(text) > 280:
        raise ValueError("exhibition update exceeds X limit")
    return text


def write_local(day: str, row: dict, state: dict) -> None:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    update_path = LOCAL_DIR / f"{day}_updates.jsonl"
    existing = []
    if update_path.exists():
        existing = [line for line in update_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    key = (row["day"], row["jcd"], row["rno"])
    found = False
    out = []
    for line in existing:
        old = json.loads(line)
        old_key = (str(old.get("day")), str(old.get("jcd")).zfill(2), int(old.get("rno") or 0))
        if old_key == key:
            if not found:
                out.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
                found = True
        else:
            out.append(json.dumps(old, ensure_ascii=False, sort_keys=True))
    if not found:
        out.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
    update_path.write_text("\n".join(out) + "\n", encoding="utf-8")

    state_path = LOCAL_DIR / f"{day}.json"
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def post_update(rno: int, deadline: str, analysis: dict) -> bool:
    key = race_key(rno)
    state = outbox.load_state(DAY)
    if key in set(map(str, state.get("x_exhibition_update_races") or [])):
        return False
    if key not in set(map(str, state.get("x_posted_races") or [])):
        print(f"skip {key}: base X post missing", flush=True)
        return False

    main, cover = build_plan(analysis)
    if len(main) < MAIN_POINTS:
        print(f"skip {key}: insufficient main picks", flush=True)
        return False
    post = make_post(rno, deadline, main, cover, analysis)
    row = {
        "day": DAY,
        "jcd": JCD,
        "rno": int(rno),
        "venue": "大村",
        "deadline": deadline,
        "source": "配当期待本線",
        "post": post,
        "picks": main + cover,
        "main": main,
        "cover": cover,
        "sent_at": datetime.now(base.JST).isoformat(),
        "exhibition": True,
    }

    local_archive = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
    outbox.publish_update_archive(DAY, local_archive)

    attempt_id = uuid.uuid4().hex
    state = outbox.load_state(DAY)
    state.setdefault("x_exhibition_attempts", {})[key] = {
        "id": attempt_id,
        "status": "reserved",
        "at": datetime.now(base.JST).isoformat(),
    }
    state, ref = outbox.publish_state(DAY, state)

    payload = json.dumps({
        "day": DAY,
        "jcd": JCD,
        "rno": int(rno),
        "archive_ref": ref,
        "attempt_id": attempt_id,
    }).encode("utf-8")
    req = urllib.request.Request(
        UPDATE_URL,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "boat-ai-omura-exhibition/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"update failed {key}: {type(exc).__name__}: {exc}", flush=True)
        return False

    post_id = str(result.get("post_id") or "")
    if not result.get("ok") or not post_id.isdigit():
        print(f"update rejected {key}: {result}", flush=True)
        return False

    state = outbox.load_state(DAY)
    state.setdefault("x_exhibition_update_races", [])
    state["x_exhibition_update_races"] = sorted(set(map(str, state["x_exhibition_update_races"])) | {key})
    state.setdefault("x_exhibition_update_ids", {})[key] = post_id
    state.setdefault("x_exhibition_attempts", {}).pop(key, None)
    state, _ = outbox.publish_state(DAY, state)
    write_local(DAY, row, state)
    print(f"posted exhibition update {key} post_id={post_id} main={len(main)} cover={len(cover)}", flush=True)
    return True


def run() -> int:
    now = datetime.now(base.JST)
    if now.strftime("%Y%m%d") != DAY:
        return 0
    deadlines = base.deadlines(DAY, JCD)
    sent = 0
    for rno in RACES:
        if len(deadlines) < rno:
            continue
        deadline = deadlines[rno - 1]
        lead = (deadline_dt(deadline) - now).total_seconds()
        if lead < MIN_LEAD_SECONDS:
            print(f"skip {rno}R: inside 11-minute safety cutoff", flush=True)
            continue
        if lead > MAX_LEAD_SECONDS:
            continue
        try:
            preview_raw = base.fetch(base.official_url("beforeinfo", DAY, JCD, rno))
            preview = base.parse_beforeinfo(preview_raw)
        except Exception as exc:
            print(f"skip {rno}R: beforeinfo {type(exc).__name__}", flush=True)
            continue
        if int(preview.get("exhibition_count") or 0) != 6:
            print(f"wait {rno}R: exhibition {preview.get('exhibition_count', 0)}/6", flush=True)
            continue
        try:
            analysis = base.analyze_official(DAY, JCD, rno)
        except Exception as exc:
            print(f"skip {rno}R: analysis {type(exc).__name__}", flush=True)
            continue
        if not analysis or int((analysis.get("preview") or {}).get("exhibition_count") or 0) != 6:
            continue
        try:
            sent += int(post_update(rno, deadline, analysis))
        except Exception as exc:
            print(f"skip {rno}R: delivery {type(exc).__name__}: {exc}", flush=True)
    return sent


if __name__ == "__main__":
    print(f"Omura exhibition X updates complete: {run()}", flush=True)
