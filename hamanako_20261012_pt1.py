"""One-day, isolated Hamamatsu/Hamanako PT1 field guide.
Does not touch existing Discord channel feeds or modify prediction journals.
The only valid live day is 2026-10-12 JST, venue 06.
"""
from __future__ import annotations

import base64
from collections import Counter, defaultdict
from datetime import datetime
from hashlib import sha256
import json
import os
import re
import sys
import urllib.error
import urllib.request

import direct_discord_notify as base
import detailed_discord_notify as cards
import four_way_prototype as trial
import hiyori_model
import hiyori_source
import opportunity_alerts
import mid_value_selection
import pt2_sheet_db
from discord_ack import post as discord_post

DAY = "20261012"
JCD = "06"
RECEIPT_ROOT = "data/hamanako_pt1_20261012/receipts"
COMBO = re.compile(r"^[1-6]-[1-6]-[1-6]$")
MODEL_LABELS = {
    "existing": "既存", "hiyori": "日和",
    "prototype1": "PT1", "prototype2": "PT2", "prototype3": "PT3",
}


def now_jst():
    return datetime.now(base.JST)


def valid_combo(item):
    if not isinstance(item, str) or not COMBO.fullmatch(item):
        return False
    return len(set(item.split("-"))) == 3


def distinct(values):
    return list(dict.fromkeys(value for value in values if valid_combo(value)))


def github_request(method, path, payload):
    token = os.environ["GITHUB_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    blob_sha = payload.pop("_blob_sha", None)
    body = {
        "message": f"Record Oct 12 Hamanako PT1 special {path.rsplit('/', 1)[-1]}",
        "content": base64.b64encode(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).decode(),
        "branch": "main",
    }
    if blob_sha:
        body["sha"] = blob_sha
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method=method,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def reserve(rno, content):
    """Atomic create: if receipt already exists, never post a second message."""
    path = f"{RECEIPT_ROOT}/{DAY}_{JCD}_{rno:02}.json"
    payload = {
        "day": DAY, "venue": JCD, "race": rno,
        "state": "reserved", "reserved_at": now_jst().isoformat(),
        "digest": sha256(content.encode()).hexdigest(),
    }
    try:
        answer = github_request("PUT", path, dict(payload))
    except urllib.error.HTTPError as exc:
        if exc.code in (409, 422):
            print(f"receipt exists/conflict for {rno}R; do not repost", flush=True)
            return None, None
        raise
    return path, answer["content"]["sha"]


def mark_delivered(path, sha, rno, message_id):
    receipt = {
        "day": DAY, "venue": JCD, "race": rno,
        "state": "delivered", "delivered_at": now_jst().isoformat(),
        "message_id": str(message_id), "_blob_sha": sha,
    }
    return github_request("PUT", path, receipt)


def build_live(day, rno, deadline):
    captured = now_jst()
    official = base.analyze_official(day, JCD, rno)
    if not official or len(official.get("inputs") or []) != 6:
        return None, "公式出走情報不足"
    if (official.get("preview") or {}).get("exhibition_count") != 6:
        return None, "展示情報待機"
    odds = {
        row["combination"]: float(row["odds"])
        for row in official.get("trifecta") or []
        if valid_combo(row.get("combination")) and isinstance(row.get("odds"), (int, float))
        and float(row["odds"]) > 0
    }
    if len(odds) < 60:
        return None, "当日オッズ取得待機"

    # Use the same live official snapshot for every available model.
    request = {"day": day, "jcd": JCD, "rno": rno,
               "deadline": deadline, "captured_at": captured.isoformat(),
               "official": official}
    try:
        source = hiyori_source.fetch_race(day, JCD, rno)
        source["fetched_at"] = now_jst().isoformat()
        hiyori = hiyori_model.analyze(official, source, day, JCD, rno)
        if not any(f.get("used") for f in hiyori.get("features") or []):
            return None, "日和実測データ待機"
        bundle = trial.build_bundle(request, hiyori, source, now=now_jst())
    except Exception as exc:
        # Never invent an absent model's picks.
        print(f"model input waiting {rno}R: {type(exc).__name__}: {exc}", flush=True)
        return None, "日和・比較モデル待機"

    db = pt2_sheet_db.enhance_analysis(official, JCD)
    db_info = db.get("sheet_database") or {}
    db_picks = distinct([
        row["combination"]
        for row in cards.displayed_picks_variable(db, True)
    ])
    # The 中穴/穴 policies are selection layers, not additional independent engines.
    mid_value_selection.install(opportunity_alerts)
    selectors = {}
    for kind, label in (("mid", "中穴選別"), ("long", "穴選別")):
        candidates = opportunity_alerts._candidate_rows(official, kind)
        picked = opportunity_alerts._coherent_selection(candidates, kind, official)
        selectors[label] = distinct([row.get("combination") for row in picked])
    return {
        "official": official, "models": bundle["models"], "selectors": selectors,
        "db": db, "db_info": db_info, "db_picks": db_picks,
        "odds": odds, "deadline": deadline,
    }, "ready"


def format_conditions(preview):
    wind = preview.get("wind_speed")
    wave = preview.get("wave_cm")
    wind_label = f"{wind:g}m" if isinstance(wind, (int, float)) else "不明"
    wave_label = f"{wave:g}cm" if isinstance(wave, (int, float)) else "不明"
    if wind is None:
        wind_effect = "風速未取得。直前のスリット・旋回を優先"
    elif wind >= 5:
        wind_effect = "風が強い。起こし・旋回の乱れを警戒"
    elif wind >= 3:
        wind_effect = "風の影響に注意。2・3の壁と4の行き足を比較"
    else:
        wind_effect = "比較的弱風。風だけで穴扱いしない"
    # Official beforeinfo parser measures wind speed, not the exact wind direction.
    result = f"🌬️ 風{wind_label}・波{wave_label}｜{wind_effect}（風向は未判定）"
    tide = preview.get("tide") or {}
    if tide.get("available"):
        phase = {"rising": "上げ潮", "falling": "下げ潮"}.get(tide.get("phase"), "潮位変動")
        station = tide.get("station") or "舞阪"
        nearm = tide.get("nearest_turn_minutes")
        minutes = f"／満干の転換点から前後約{nearm}分" if isinstance(nearm, int) else ""
        result += f"\n🌊 {phase}{minutes}（{station}の参照潮汐。水面への影響は展示と照合）"
    else:
        result += "\n🌊 浜名湖は汽水で干満差あり。今回の潮位推定は未取得（補正なし）"
    return result


def explain(official):
    boats = {int(b["lane"]): b for b in official.get("inputs") or []}
    preview = official.get("preview") or {}
    b1 = boats[1]
    motor = b1.get("motor_top2_rate")
    motor_text = f"／1号艇のモーター2連率{motor:g}%" if isinstance(motor, (int, float)) else ""
    candidates = [
        (b.get("exhibition_st"), i) for i, b in boats.items()
        if i in (3, 4, 5) and isinstance(b.get("exhibition_st"), (int, float))
    ]
    attack = min(candidates)[1] if candidates else None
    st_2 = boats[2].get("exhibition_st")
    st_3 = boats[3].get("exhibition_st")
    st_4 = boats[4].get("exhibition_st")
    if all(isinstance(s, (int, float)) for s in (st_3, st_4)):
        wall = f"3号艇の展示ST {st_3:.2f}、4号艇 {st_4:.2f}。"
        wall += "4攻めの可能性あり。" if st_4 + .07 < st_3 else "壁が崩れるかは伸びも確認。"
    else:
        wall = "2・3号艇が壁になるか直前の展示で判断。"
    if attack:
        outside = f"{attack}号艇の展示STが3〜5号艇で先行。攻めた艇の外側にも展開余地。"
    else:
        outside = "外から仕掛ける艇は確定できず。"
    return f"1号艇 {b1.get('name', '')}（{b1.get('current_class', '級別不明')}）{motor_text}。\n{wall}\n{outside}"


def compress_exact(picks):
    """Compress only complete combinations; never add unintended tickets."""
    remaining = set(distinct(picks))
    out = []
    while remaining:
        head, second, third = min(remaining).split("-")
        seconds, thirds = {second}, {third}
        changed = True
        while changed:
            changed = False
            for b in "123456":
                if b != head and b not in seconds and b not in thirds and all(
                    f"{head}-{b}-{c}" in remaining for c in thirds
                ):
                    seconds.add(b)
                    changed = True
            for c in "123456":
                if c != head and c not in thirds and c not in seconds and all(
                    f"{head}-{b}-{c}" in remaining for b in seconds
                ):
                    thirds.add(c)
                    changed = True
        chosen = {f"{head}-{b}-{c}" for b in seconds for c in thirds}
        if not chosen <= remaining:
            raise AssertionError("formation changed the original picks")
        remaining -= chosen
        out.append(f"{head}-{''.join(sorted(seconds))}-{''.join(sorted(thirds))}")
    return out


def box_reason(pt1, box):
    """Display provenance and the live model's evidence for each BOX lane."""
    if len(box) != 3 or len(set(box)) != 3:
        return "対象3艇を確定できず（BOX提示なし）"
    notes = pt1.get("boat_reasons") or {}
    return "\n".join(
        f"{lane}号艇：{notes.get(str(lane)) or 'PT1の3着内確率・AI支持で選定'}"
        for lane in sorted(box)
    )


def format_message(day, rno, live):
    models = live["models"]
    sources = {}
    for key in MODEL_LABELS:
        model = models.get(key) or {}
        sources[MODEL_LABELS[key]] = distinct(model.get("picks") or [])
    sources.update(live["selectors"])
    votes = defaultdict(set)
    for source, picks in sources.items():
        for combo in picks:
            votes[combo].add(source)
    db_rank = {p: i for i, p in enumerate(live["db_picks"])}
    odds = live["odds"]
    # Agreement first, then DB ranking as a tie-breaker. Avoid duplicate tickets.
    ordered = sorted(votes, key=lambda p: (
        -len(votes[p]), db_rank.get(p, 999), -float(odds.get(p, 0)), p
    ))
    main = [p for p in ordered if len(votes[p]) >= 3]
    if not main:
        main = [p for p in ordered if len(votes[p]) >= 2]
    cover = [p for p in ordered if p not in set(main)]
    box = models.get("prototype1", {}).get("box_lanes") or []
    box_label = "".join(map(str, sorted(box))) if len(box) == 3 else "不明"
    db_picks = live["db_picks"]
    db_enabled = bool(live["db_info"].get("enabled"))
    if not db_enabled:
        db_picks = []
    # Show any exact ticket only once across main, cover, BOX and DB.
    from itertools import permutations
    main_set = set(main)
    cover_set = set(cover) - main_set
    box_set = {"-".join(map(str, p)) for p in permutations(box, 3)} if len(box) == 3 else set()
    # BOX is a standalone three-boat recommendation, intentionally independent.
    # Overlap with main/cover is permitted only in this separate BOX display.
    db_unique = set(db_picks) - main_set - cover_set - box_set
    if main_set & cover_set or db_unique & (main_set | cover_set | box_set):
        raise AssertionError("duplicate ticket across non-BOX sections")
    def lines(picks):
        return " / ".join(compress_exact(picks)) or "該当なし"
    agreement = Counter(len(votes[p]) for p in main)
    agreement_note = "・".join(f"{n}AI一致 {count}点" for n, count in sorted(agreement.items(), reverse=True))
    cover_long = [p for p in cover if odds.get(p, 0) >= 100]
    near = f"（現在100倍以上 {len(cover_long)}点含む）" if cover_long else ""
    snapshot = live["db_info"].get("snapshot_at") or "不明"
    preview = live["official"].get("preview") or {}
    model_names = "・".join(sources)
    body = (
        f"🚤 **10/12 浜名湖{rno}R｜PT1特別・全AI横断**\n"
        f"⏰ 締切 {live['deadline']}｜集計: {model_names}\n"
        f"🧠 **根拠・展開予想**\n{explain(live['official'])}\n"
        f"🎯 **本線（重複なし・{len(main)}点）**\n{lines(main)}\n一致状況：{agreement_note or '該当なし'}\n"
        f"🛟 **抑え（{len(cover)}点）** {near}\n{lines(cover)}\n"
        f"📦 **PT1 BOX｜根拠重視の3艇：{box_label} BOX（6点・本線との重複OK）**\n{box_reason(models.get('prototype1') or {}, box)}\n"
        f"🗃️ **DB総合予想｜未掲載分 {len(db_unique)}点**\n{lines(db_unique)}\n"
        f"（DB照合 {'有効' if db_enabled else '一致データ不足'}／スナップショット {snapshot}）\n"
        f"📡 **天候・潮の影響**\n{format_conditions(preview)}\n"
        f"※モデル予測であって的中保証ではありません。購入前に展示・最新オッズ確認。"
    )
    if len(set(main).intersection(cover)):
        raise AssertionError("Main and cover share picks")
    return body



def split_messages(message, limit=1850):
    """Split at line boundaries; never drop predicted combinations."""
    if len(message) <= limit:
        return [message]
    parts = []
    current = ""
    for line in message.splitlines():
        # Long ticket lines are separated at the existing slash boundary.
        pieces = [line] if len(line) <= limit - 80 else (
            [line[:line.find(" ")]] + line[line.find(" ") + 1:].split(" / ")
            if " / " in line else [line[i:i + limit - 80] for i in range(0, len(line), limit - 80)]
        )
        if len(pieces) > 1 and " / " in line:
            # Prefix the first fragment as its own line and preserve each ticket.
            pieces = [pieces[0]] + [(" / " if i else "") + p for i, p in enumerate(pieces[1:])]
        for piece in pieces:
            if len(piece) > limit:
                raise ValueError("Unsplit oversized Discord message")
            candidate = (current + "\n" + piece).strip()
            if len(candidate) > limit and current:
                parts.append(current)
                current = piece
            else:
                current = candidate
    if current:
        parts.append(current)
    return [f"**浜名湖特別配信 {i + 1}/{len(parts)}**\n{p}" if len(parts) > 1 else p
            for i, p in enumerate(parts)]


def process_one(day, rno, deadline, *, dry_run=False):
    live, status = build_live(day, rno, deadline)
    if not live:
        print(f"{rno}R {status}", flush=True)
        return False
    message = format_message(day, rno, live)
    if base.minutes_until(now_jst(), deadline) < 0.5:
        print(f"{rno}R closing; skip stale prediction", flush=True)
        return False
    chunks = split_messages(message)
    if dry_run:
        for chunk in chunks:
            print(chunk, flush=True)
        return True
    webhook = os.environ.get("PROTO1_DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        raise RuntimeError("PT1 webhook is missing; fail closed")
    if not os.getenv("GITHUB_TOKEN") or not os.getenv("GITHUB_REPOSITORY"):
        raise RuntimeError("durable receipt repository unavailable; fail closed")
    path, sha = reserve(rno, message)
    if not path:
        return False
    try:
        sent_ids = []
        for chunk in chunks:
            sent_ids.append(discord_post(webhook, {"username": "浜名湖12日限定・AI総合ガイド", "content": chunk}))
        msg_id = ",".join(sent_ids)
    except Exception as exc:
        # A network failure may be an acknowledged post with a lost response.
        # Do not blindly retry: keep the reservation for manual reconciliation.
        print(f"::error::Discord ack unknown {rno}R: {type(exc).__name__}: {exc}", flush=True)
        raise
    mark_delivered(path, sha, rno, msg_id)
    print(f"{rno}R posted PT1 message_id={msg_id}", flush=True)
    return True


def main():
    now = now_jst()
    if now.strftime("%Y%m%d") != DAY:
        print("One-day special inactive outside 2026-10-12 JST", flush=True)
        return 0
    # Do not disturb other channels or their delivery/scoreboard state.
    if not 10 <= now.hour <= 17:
        print("Outside Hamanako race window", flush=True)
        return 0
    if os.getenv("GITHUB_REPOSITORY") != "maedayuuki0706-creator/-AI":
        raise RuntimeError("unexpected repository")
    base.fetch.cache_clear()
    schedule = base.deadlines(DAY, JCD)
    if len(schedule) != 12:
        print(f"Official deadline data incomplete ({len(schedule)}/12); no messages", flush=True)
        return 0
    print(f"Hamanako PT1 check at {now.isoformat()} - next races: " +
          ", ".join(f"{rno}R={deadline}({base.minutes_until(now, deadline):.1f}m)"
                    for rno, deadline in enumerate(schedule, 1)
                    if base.minutes_until(now, deadline) > 0)[:240], flush=True)
    due = [
        (rno, deadline)
        for rno, deadline in enumerate(schedule, 1)
        if .5 <= base.minutes_until(now, deadline) <= 17
    ]
    if not due:
        print("No race in the 0.5–17 minute delivery window; no post attempted", flush=True)
    for rno, deadline in due:
        try:
            posted = process_one(DAY, rno, deadline, dry_run=os.getenv("HAMANAKO_SPECIAL_DRY_RUN") == "1")
            if not posted:
                print(f"::warning::{rno}R not delivered (check waiting reason above)", flush=True)
        except Exception as exc:
            print(f"::warning::{rno}R failed: {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
