"""Send one daily Discord summary each for 厳選くん and 中穴厳選くん."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path

import direct_discord_notify as base
from prediction_recap import post_confirmed, report_destination_key

LOG_PATH = Path("data/opportunity_alert_deliveries.jsonl")
RESULT_DIR = Path("data/official_results")
DELIVERY_PATH = Path("data/selected_daily_report_deliveries.jsonl")


def read_jsonl(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def append_jsonl(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def latest_rows(day):
    latest = {}
    for row in read_jsonl(LOG_PATH):
        if str(row.get("day") or "") != day:
            continue
        stream = str(row.get("stream") or "")
        if stream not in {"mid_odds", "longshot"}:
            continue
        try:
            rno = int(row.get("rno") or 0)
        except (TypeError, ValueError):
            continue
        jcd = str(row.get("jcd") or "").zfill(2)
        if not jcd.isdigit() or not 1 <= rno <= 12:
            continue
        key = (stream, jcd, rno)
        if key not in latest or str(row.get("sent_at") or "") >= str(latest[key].get("sent_at") or ""):
            latest[key] = row
    return latest


def is_selected(row, stream):
    if stream == "mid_odds":
        return bool(row.get("selected")) or row.get("delivery_env") == "DISCORD_WEBHOOK_MID_ODDS_SELECTED"
    # Longshot sniper skips are journaled; actual sniper deliveries have a webhook target.
    return row.get("status") != "sniper_skip" and row.get("delivery_env") == "DISCORD_WEBHOOK_LONGSHOT"


def pick_set(row):
    return {
        str(x.get("combination") or "").strip()
        for x in (row.get("picks") or [])
        if isinstance(x, dict) and x.get("combination")
    }


def summarize(day, stream, results):
    rows = [
        row for (s, _, _), row in latest_rows(day).items()
        if s == stream and is_selected(row, stream)
    ]
    rows.sort(key=lambda r: (str(r.get("jcd") or "").zfill(2), int(r.get("rno") or 0)))
    settled = hits = points = stake = returned = 0
    hit_lines = []
    best = None
    for row in rows:
        jcd = str(row.get("jcd") or "").zfill(2)
        rno = int(row.get("rno") or 0)
        picks = pick_set(row)
        result = results.get(f"{jcd}:{rno}") or {}
        if result.get("status") != "settled":
            continue
        payouts = result.get("payouts") or {}
        settled += 1
        points += len(picks)
        stake += len(picks) * 100
        matched = [(combo, int(yen)) for combo, yen in payouts.items() if combo in picks]
        race_return = sum(yen for _, yen in matched)
        returned += race_return
        if matched:
            hits += 1
            combo, payout = max(matched, key=lambda x: x[1])
            venue = str(row.get("venue") or jcd)
            hit_lines.append(f"🎯 {venue} {rno}R　{combo}　{payout:,}円")
            if best is None or payout > best[0]:
                best = (payout, venue, rno, combo)
    return {
        "rows": rows, "selected": len(rows), "settled": settled, "hits": hits,
        "points": points, "stake": stake, "return": returned, "profit": returned - stake,
        "hit_rate": (hits / settled * 100) if settled else None,
        "roi": (returned / stake * 100) if stake else None,
        "hit_lines": hit_lines, "best": best,
    }


def pct(v):
    return "—" if v is None else f"{v:.1f}%"


def payload(day, stream, stats):
    date = f"{day[:4]}/{day[4:6]}/{day[6:8]}"
    if stream == "longshot":
        title, icon, desc = "厳選くん", "🎯", "穴スナイパーの厳選配信だけを集計"
    else:
        title, icon, desc = "中穴厳選くん", "🟡", "厳選中穴として実際に選ばれた配信だけを集計"
    best = stats["best"]
    best_text = "なし" if best is None else f"{best[1]} {best[2]}R　{best[3]}／{best[0]:,}円"
    hits = "\n".join(stats["hit_lines"]) or "的中なし"
    fields = [
        {"name": "📊 今日の成績", "value":
            f"厳選 {stats['selected']}R／結果確定 {stats['settled']}R\n"
            f"的中 **{stats['hits']}/{stats['settled']}R＝{pct(stats['hit_rate'])}**\n"
            f"買い目 {stats['points']}点（各100円）\n"
            f"投資 {stats['stake']:,}円 → 払戻 {stats['return']:,}円\n"
            f"**収支 {stats['profit']:+,}円／回収率 {pct(stats['roi'])}**", "inline": False},
        {"name": "🎯 的中レース", "value": hits[:1024], "inline": False},
        {"name": "💰 最高配当", "value": best_text, "inline": False},
    ]
    embed = {
        "title": f"{icon} {title}｜{date} 日報",
        "description": desc + "。見送りは不的中に数えません。",
        "color": 0xD4A017 if stream == "mid_odds" else 0xC0392B,
        "fields": fields,
        "footer": {"text": "回収率・収支は配信買い目を各点100円で購入した比較値。"},
    }
    return {"embeds": [embed], "allowed_mentions": {"parse": []}}


def send(day):
    result_path = RESULT_DIR / f"{day}.json"
    if not result_path.exists():
        raise FileNotFoundError(result_path)
    results = json.loads(result_path.read_text(encoding="utf-8"))
    destination = report_destination_key()
    delivered = {
        (r.get("day"), r.get("stream"), r.get("digest"), r.get("destination"))
        for r in read_jsonl(DELIVERY_PATH)
    }
    sent = 0
    # User requested one message each: 厳選くん first, then 中穴厳選くん.
    for stream in ("longshot", "mid_odds"):
        stats = summarize(day, stream, results)
        body = payload(day, stream, stats)
        digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        key = (day, stream, digest, destination)
        if key in delivered:
            continue
        message = post_confirmed(body)
        append_jsonl(DELIVERY_PATH, {
            "day": day, "stream": stream, "digest": digest, "destination": destination,
            "message_id": message["id"], "sent_at": datetime.now(base.JST).isoformat(),
        })
        sent += 1
    print(f"selected daily report {day}: sent={sent}")
    return sent


def default_day():
    now = datetime.now(base.JST)
    if now.hour < 6:
        now -= timedelta(days=1)
    return now.strftime("%Y%m%d")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", default=default_day())
    args = parser.parse_args()
    send(args.day)
