"""Cutoff-based Discord interim report for 新人予想家 ゆうき (PT3)."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import json
import os
from pathlib import Path

from direct_discord_notify import JST, VENUES
from discord_notification_policy import SUPPRESS_NOTIFICATIONS
from interim_report import require_report_channel
from prediction_recap import post_confirmed

DELIVERIES = Path("data/prototype3_delivery/deliveries")
RESULTS_ROOT = Path("data/prototype_scoreboard")
OUT = Path("data/yuuki_interim_reports")
REQUEST = Path("yuuki_interim_report_request.json")


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def ts(value):
    try:
        value = datetime.fromisoformat(str(value))
        return value.astimezone(JST) if value.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def build(day: str, hour: int) -> dict:
    cutoff = datetime.strptime(f"{day} {hour:02d}:00", "%Y%m%d %H:%M").replace(tzinfo=JST)
    if datetime.now(JST) < cutoff:
        raise RuntimeError("Cutoff has not been reached")

    deliveries = {}
    counts = defaultdict(lambda: {"hits": 0, "judged": 0, "delivered": 0})

    for path in DELIVERIES.glob(day + "_*.json"):
        try:
            receipt = read(path)
        except Exception:
            continue
        delivered_at = ts(receipt.get("delivered_at"))
        if delivered_at and delivered_at <= cutoff and receipt.get("key") == path.stem:
            deliveries[path.stem] = receipt
            parts = path.stem.split("_")
            if len(parts) >= 4 and parts[1] in VENUES:
                counts[VENUES[parts[1]]]["delivered"] += 1

    races = []
    for path in (RESULTS_ROOT / day / "results").glob("*.json"):
        try:
            row = read(path)
        except Exception:
            continue
        key = row.get("key")
        receipt = deliveries.get(key)
        score = (row.get("models") or {}).get("prototype3") or {}
        official = row.get("official") or {}
        checked_at = ts(official.get("checked_at"))
        if (
            not receipt
            or row.get("day") != day
            or path.stem != key
            or official.get("status") != "settled"
            or checked_at is None
            or checked_at > cutoff
            or not score.get("eligible")
            or receipt.get("prediction_digest") != (row.get("prediction_digests") or {}).get("prototype3")
        ):
            continue
        venue = row.get("venue") or VENUES.get(str(row.get("jcd") or "").zfill(2), "不明")
        counts[venue]["judged"] += 1
        hit = bool(score.get("hit"))
        counts[venue]["hits"] += int(hit)
        races.append({"key": key, "venue": venue, "hit": hit, "checked_at": official.get("checked_at")})

    def rate(s):
        return f'{s["hits"]}/{s["judged"]}R（{s["hits"] / s["judged"] * 100:.1f}%）' if s["judged"] else "—"

    totals = {k: sum(v[k] for v in counts.values()) for k in ("hits", "judged", "delivered")}
    lines = [
        f"🏆 **新人予想家 ゆうき｜{day[4:6]}/{day[6:8]} {hour:02d}:00時点**",
        "",
        f"**全場合計** {rate(totals)}",
        f'配信 {totals["delivered"]}R／判定済み {totals["judged"]}R',
        "",
        "**各場の的中率**",
    ]
    for venue, s in sorted(counts.items()):
        lines.append(f"・{venue}：{rate(s)}")
    lines += [
        "",
        f"{hour:02d}:00 JSTまでの予想配信記録と公式結果確認記録で集計。結果待ち・未集計は分母外。",
    ]
    payload = {"content": "\n".join(lines), "allowed_mentions": {"parse": []}, "flags": SUPPRESS_NOTIFICATIONS}
    return {
        "day": day,
        "hour": hour,
        "as_of": cutoff.isoformat(),
        "totals": totals,
        "venues": dict(counts),
        "races": races,
        "payload": payload,
    }


def send(day: str, hour: int) -> dict:
    require_report_channel()
    OUT.mkdir(parents=True, exist_ok=True)
    snapshot_path = OUT / f"{day}_{hour:02d}.json"
    receipt_path = OUT / f"{day}_{hour:02d}_receipt.json"

    if receipt_path.exists():
        saved = read(receipt_path)
        if str(saved.get("message_id") or "").isdigit():
            return {"sent": False, "reason": "already_sent", "message_id": saved["message_id"]}

    snapshot = build(day, hour)
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = post_confirmed(snapshot["payload"])
    if not str(result.get("id") or "").isdigit():
        raise RuntimeError("No Discord acknowledgement")
    receipt = {
        "request_id": f"yuuki:{day}:{hour:02d}",
        "message_id": result["id"],
        "sent_at": datetime.now(JST).isoformat(),
    }
    with receipt_path.open("w", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return {"sent": True, **receipt, "totals": snapshot["totals"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--day")
    parser.add_argument("--hour", type=int, choices=(13, 15, 17))
    parser.add_argument("--request", type=Path)
    args = parser.parse_args()

    if args.request:
        req = read(args.request)
        day = str(req["day"])
        hour = int(req["hour"])
    else:
        now = datetime.now(JST)
        day = args.day or now.strftime("%Y%m%d")
        hour = args.hour or max(h for h in (13, 15, 17) if h <= now.hour)

    print(json.dumps(send(day, hour), ensure_ascii=False))


if __name__ == "__main__":
    main()
