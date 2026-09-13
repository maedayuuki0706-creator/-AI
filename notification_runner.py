"""Recheck scheduled notifications, or resend today's prediction log grouped by venue."""
from datetime import datetime
import json
import os
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

import detailed_discord_notify as app

VENUES = {
    "01":"桐生","02":"戸田","03":"江戸川","04":"平和島","05":"多摩川","06":"浜名湖",
    "07":"蒲郡","08":"常滑","09":"津","10":"三国","11":"びわこ","12":"住之江",
    "13":"尼崎","14":"鳴門","15":"丸亀","16":"児島","17":"宮島","18":"徳山",
    "19":"下関","20":"若松","21":"芦屋","22":"福岡","23":"唐津","24":"大村",
}
LOG_PATH = Path("data/prediction_log.jsonl")


def race_hours():
    return 8 <= datetime.now(app.base.JST).hour < 22


def run(watch_seconds=0, *, attempt=app.main, clock=time.monotonic, pause=time.sleep, is_open=race_hours):
    end = clock() + max(0, min(int(watch_seconds), 600))
    result = 0
    while is_open():
        try:
            result = attempt()
        except Exception as exc:
            print(f'Notification pass failed: {type(exc).__name__}', flush=True)
            result = 1
        if end - clock() < 210:
            break
        pause(60)
    return result


def send_webhook(content: str) -> None:
    url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is missing")
    payload = json.dumps({"content": content, "allowed_mentions": {"parse": []}}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as response:
        response.read()


def resend_prediction_summary(day: str = "20260913") -> int:
    """Send the latest logged prediction for every race, grouped one message per venue."""
    if not LOG_PATH.exists():
        raise RuntimeError(f"Prediction log not found: {LOG_PATH}")

    latest = {}
    with LOG_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(row.get("day")) != day:
                continue
            jcd = str(row.get("jcd", "")).zfill(2)
            rno = int(row.get("rno", 0) or 0)
            if jcd not in VENUES or not 1 <= rno <= 12:
                continue
            key = (jcd, rno)
            sent_at = str(row.get("sent_at", ""))
            if key not in latest or sent_at > str(latest[key].get("sent_at", "")):
                latest[key] = row

    grouped = defaultdict(list)
    for (jcd, rno), row in latest.items():
        grouped[jcd].append((rno, row))

    sent = 0
    for jcd in sorted(grouped, key=lambda x: int(x)):
        lines = [f"━━━━━━━━━━━━━━━━━━", f"【{VENUES[jcd]}】", f"━━━━━━━━━━━━━━━━━━", ""]
        for rno, row in sorted(grouped[jcd], key=lambda x: x[0]):
            main = row.get("main") or row.get("all_picks", [])[:3]
            cover = row.get("cover") or row.get("all_picks", [])[3:6]
            lines += [f"■ {rno}R", "【本線】"]
            lines += [str(p) for p in main]
            lines += ["", "【抑え】"]
            lines += [str(p) for p in cover]
            lines += ["", "━━━━━━━━━━━━━━━━━━", ""]

        content = "\n".join(lines).strip()
        # Discord allows 2000 chars per message. Split only at race boundaries.
        if len(content) <= 2000:
            send_webhook(content)
            sent += 1
            continue

        chunks = []
        current = [f"【{VENUES[jcd]}】"]
        for block in "\n".join(lines[3:]).split("━━━━━━━━━━━━━━━━━━\n"):
            block = block.strip()
            if not block:
                continue
            candidate = "\n━━━━━━━━━━━━━━━━━━\n".join(current + [block])
            if len(candidate) > 1950 and len(current) > 1:
                chunks.append("\n━━━━━━━━━━━━━━━━━━\n".join(current))
                current = [f"【{VENUES[jcd]}】", block]
            else:
                current.append(block)
        if len(current) > 1:
            chunks.append("\n━━━━━━━━━━━━━━━━━━\n".join(current))
        for chunk in chunks:
            send_webhook(chunk)
            sent += 1

    print(f"Resent {len(latest)} races in {sent} Discord message(s) for {day}", flush=True)
    return 0


if __name__ == '__main__':
    if os.getenv("SUMMARY_ONLY") == "1":
        raise SystemExit(resend_prediction_summary(os.getenv("SUMMARY_DAY", "20260913")))
    raise SystemExit(run(os.getenv('NOTIFY_WATCH_SECONDS', '0')))
