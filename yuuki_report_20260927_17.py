from collections import defaultdict
from datetime import datetime
import json
import os
from pathlib import Path

from interim_report import require_report_channel
from prediction_recap import post_confirmed
from discord_notification_policy import SUPPRESS_NOTIFICATIONS

cutoff = datetime.fromisoformat("2026-09-27T17:00:00+09:00")
day = "20260927"
root = Path("data/yuuki_interim_reports")
marker = root / "20260927_17_receipt.json"

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

def before(value):
    try:
        t = datetime.fromisoformat(value)
        return t.tzinfo is not None and t <= cutoff
    except (ValueError, TypeError):
        return False

def main():
    if datetime.now(cutoff.tzinfo) < cutoff:
        raise RuntimeError("Cutoff has not been reached")
    require_report_channel()
    if marker.exists() and read(marker).get("message_id"):
        print("Already acknowledged")
        return
    counts = defaultdict(lambda: {"hits": 0, "judged": 0, "delivered": 0})
    deliveries = {}
    for path in Path("data/prototype3_delivery/deliveries").glob(day + "_*.json"):
        receipt = read(path)
        if before(receipt.get("delivered_at")) and receipt.get("key") == path.stem:
            deliveries[path.stem] = receipt
    from direct_discord_notify import VENUES
    for key in deliveries:
        counts[VENUES[key.split("_")[1]]]["delivered"] += 1
    races = []
    for path in Path("data/prototype_scoreboard") .joinpath(day, "results").glob("*.json"):
        row = read(path)
        key = row.get("key")
        receipt = deliveries.get(key)
        score = (row.get("models") or {}).get("prototype3") or {}
        official = row.get("official") or {}
        if (not receipt or row.get("day") != day or path.stem != key
                or official.get("status") != "settled"
                or not before(official.get("checked_at"))
                or not score.get("eligible")
                or receipt.get("prediction_digest") != (row.get("prediction_digests") or {}).get("prototype3")):
            continue
        counts[row["venue"]]["judged"] += 1
        counts[row["venue"]]["hits"] += int(bool(score.get("hit")))
        races.append({"key": key, "hit": bool(score.get("hit")), "checked_at": official["checked_at"]})
    def text(s):
        rate = f'{s["hits"] / s["judged"] * 100:.1f}%' if s["judged"] else "—"
        return f'{s["hits"]}/{s["judged"]}R（{rate}）'
    totals = {k: sum(s[k] for s in counts.values()) for k in ("hits", "judged", "delivered")}
    if not totals["delivered"]:
        raise RuntimeError("No delivered forecasts available")
    lines = ["🏆 **新人予想家 ゆうき｜09/27 17:00時点**", "",
             "**全場合計** " + text(totals),
             f'配信 {totals["delivered"]}R／判定済み {totals["judged"]}R',
             "", "**各場の的中率**"]
    lines += [f'・{v}：{text(s)}' for v, s in sorted(counts.items())]
    lines += ["", "17:00 JSTまでの予想配信記録と公式結果確認記録で集計。結果待ち・未集計は分母外。判定0件の的中率は—。"]
    payload = {"content": "\n".join(lines), "allowed_mentions": {"parse": []}, "flags": SUPPRESS_NOTIFICATIONS}
    root.mkdir(parents=True, exist_ok=True)
    snapshot = {"as_of": cutoff.isoformat(), "totals": totals, "venues": dict(counts), "races": races, "payload": payload}
    (root / "20260927_17.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = post_confirmed(payload)
    if not str(result.get("id", "")).isdigit():
        raise RuntimeError("No Discord acknowledgement")
    with marker.open("w", encoding="utf-8") as handle:
        json.dump({"request_id": "yuuki:20260927:17", "message_id": result["id"], "sent_at": datetime.now(cutoff.tzinfo).isoformat()}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    print("Yuuki report acknowledged", totals)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit("Yuuki interim report failed: " + type(exc).__name__) from None
