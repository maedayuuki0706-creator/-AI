"""Report confirmed 新人予想家 ゆうき hits to the existing 速報くん channel.

Only the PT3 scoreboard's settled, delivered predictions are eligible. A
per-race receipt prevents a second alert when the scheduled workflow reruns.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import urllib.request
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
P3_ROOT = Path("data/prototype3_delivery")
SCORE_ROOT = Path("data/prototype_scoreboard")
START_DAY = "20260927"


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def message(row: dict, score: dict, payout: int, selected: bool) -> str:
    winning = " / ".join(score["winning_picks"])
    section = "本線" if score.get("main_hit") else "抑え"
    badge = "🏅 **厳選予想も的中！**\n" if selected else ""
    title = "🚨💰 万舟的中" if payout >= 10000 else "🎯 的中"
    return (
        f"🔥 **新人予想家ゆうきが持ってきた！**\n"
        f"{title}｜**{row['venue']} {row['rno']}R**\n"
        f"{badge}結果：**{winning}　{payout:,}円**（3連単100円あたり）\n"
        f"的中箇所：**{section}**｜予想 **{score['point_count']}点**"
    )


def send_discord(content: str) -> None:
    url = os.getenv("DISCORD_HIT_WEBHOOK_URL", "").strip()
    if not url:
        raise RuntimeError("DISCORD_HIT_WEBHOOK_URL is missing")
    payload = json.dumps({
        "username": "速報くん",
        "content": "@everyone\n" + content,
        "allowed_mentions": {"parse": ["everyone"]},
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "User-Agent": "Boat-AI-Navi/3.2 (+yuuki-hit-alerts)",
    }, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status not in (200, 204):
            raise RuntimeError(f"Discord HTTP {response.status}")


def run(day: str, *, sender=send_discord) -> int:
    if day < START_DAY:
        return 0
    count = 0
    folder = SCORE_ROOT / day / "results"
    for path in sorted(folder.glob("*.json")):
        row = read_json(path)
        if not isinstance(row, dict) or row.get("day") != day:
            continue
        key = row.get("key")
        if not isinstance(key, str) or path.stem != key:
            continue
        alert_receipt = P3_ROOT / "hit_alerts" / f"{key}.json"
        if alert_receipt.exists():
            continue
        score = (row.get("models") or {}).get("prototype3")
        official = row.get("official") or {}
        if not isinstance(score, dict) or official.get("status") != "settled" or not score.get("hit"):
            continue
        receipt = read_json(P3_ROOT / "deliveries" / f"{key}.json")
        if not isinstance(receipt, dict) or receipt.get("key") != key:
            continue
        if receipt.get("prediction_digest") != (row.get("prediction_digests") or {}).get("prototype3"):
            continue
        winners = score.get("winning_picks") or []
        payouts = official.get("payouts") or {}
        payout = max((int(payouts.get(pick) or 0) for pick in winners), default=0)
        if payout <= 0:
            continue
        selected_receipt = read_json(P3_ROOT / "selected_deliveries" / f"{key}.json")
        selected = isinstance(selected_receipt, dict) and selected_receipt.get("key") == key
        try:
            sender(message(row, score, payout, selected))
        except Exception as exc:
            print(f"yuuki hit alert retry pending {key}: {type(exc).__name__}", flush=True)
            continue
        alert_receipt.parent.mkdir(parents=True, exist_ok=True)
        temporary = alert_receipt.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "key": key, "day": day, "status": "sent", "selected": selected,
            "winning_picks": winners, "payout_per_100": payout,
            "sent_at": datetime.now(JST).isoformat(),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(alert_receipt)
        count += 1
        print(f"yuuki hit alert sent {key} selected={selected}", flush=True)
    return count


if __name__ == "__main__":
    now = datetime.now(JST)
    day = (now - timedelta(days=1)).strftime("%Y%m%d") if now.hour < 6 else now.strftime("%Y%m%d")
    run(day)
