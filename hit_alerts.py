"""Send Discord hit alerts after official BOAT RACE results are settled.

Only the latest valid pre-deadline prediction for each race is judged. Misses
stay silent. Successful alerts are journaled so later notifier passes do not
send the same race again.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path

import daily_report as report
import direct_discord_notify as base

DELIVERY_PATH = Path("data/hit_alert_deliveries.jsonl")
UNIT_YEN = 100


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _race_key(row: dict) -> str:
    return f"{row.get('day')}:{str(row.get('jcd')).zfill(2)}:{int(row.get('rno', 0))}"


def _sent_keys(day: str) -> set[str]:
    return {
        str(row.get("key"))
        for row in _read_jsonl(DELIVERY_PATH)
        if row.get("day") == day and row.get("status") == "sent"
    }


def _send_hit_channel(content: str) -> None:
    hit_url = os.getenv("DISCORD_HIT_WEBHOOK_URL", "").strip()
    if not hit_url:
        raise RuntimeError("DISCORD_HIT_WEBHOOK_URL is missing")
    original = os.environ.get("DISCORD_WEBHOOK_URL")
    os.environ["DISCORD_WEBHOOK_URL"] = hit_url
    try:
        base.send_discord(content)
    finally:
        if original is None:
            os.environ.pop("DISCORD_WEBHOOK_URL", None)
        else:
            os.environ["DISCORD_WEBHOOK_URL"] = original


def _hit_section(row: dict, winner: str) -> str:
    if winner in (row.get("main") or []):
        return "◎ 本線"
    if winner in (row.get("cover") or []):
        return "○ 押さえ"
    if winner in (row.get("outsiders") or []):
        return "△ 穴"
    return "予想内"


def _settle_3000(row: dict, result: dict) -> dict | None:
    plan = row.get("stake_3000_units")
    if not isinstance(plan, dict) or not plan:
        return None
    clean = {}
    for combo, units in plan.items():
        if type(units) is int and units > 0:
            clean[str(combo)] = units
    if not clean:
        return None

    refund_lanes = set(int(x) for x in (result.get("refund_lanes") or []))
    payouts = result.get("payouts") or {}
    stake = sum(clean.values()) * UNIT_YEN
    returned = 0
    for combo, units in clean.items():
        try:
            lanes = set(map(int, combo.split("-")))
        except ValueError:
            lanes = set()
        if lanes & refund_lanes:
            returned += units * UNIT_YEN
        else:
            returned += units * int(payouts.get(combo) or 0)
    profit = returned - stake
    return {
        "stake": stake,
        "return": returned,
        "profit": profit,
        "roi": returned / stake * 100 if stake else None,
    }


def _message(row: dict, winner: str, payout: int, result: dict) -> str:
    is_man = payout >= 10000
    title = "🚨🎯 **万舟的中速報**" if is_man else "🎯 **的中速報**"
    section = _hit_section(row, winner)
    grade = row.get("grade") or "-"
    score = row.get("selection_score")
    score_text = f" / 総合スコア **{int(score)}/100**" if score is not None else ""

    lines = [
        f"{title}｜{row.get('venue')} {row.get('rno')}R**",
        f"結果：**{winner}　{payout:,}円**",
        f"的中：**{section}** / 評価 **{grade}**{score_text}",
    ]

    settled = _settle_3000(row, result)
    if settled is not None:
        if settled["profit"] > 0:
            outcome = "✅ プラス"
        elif settled["profit"] < 0:
            outcome = "⚠️ トリガミ"
        else:
            outcome = "➖ 元返し"
        lines += [
            "",
            "💰 **3,000円資金配分**",
            f"投資 {settled['stake']:,}円 → 払戻 **{settled['return']:,}円**",
            f"収支 **{settled['profit']:+,}円** / ROI **{settled['roi']:.1f}%** / {outcome}",
        ]

    return "\n".join(lines)


def check_and_send(day: str | None = None, now: datetime | None = None) -> int:
    now = (now or datetime.now(base.JST)).astimezone(base.JST)
    day = day or now.strftime("%Y%m%d")
    if not base.LOG_PATH.exists():
        return 0

    predictions = report.read_jsonl(base.LOG_PATH)
    chosen, _ = report.latest_predictions(predictions, day)
    sent = _sent_keys(day)
    delivered = 0

    for key, row in sorted(chosen.items()):
        delivery_key = _race_key(row)
        if delivery_key in sent:
            continue
        try:
            close = datetime.strptime(day + " " + row["deadline"], "%Y%m%d %H:%M").replace(tzinfo=base.JST)
        except (KeyError, TypeError, ValueError):
            continue
        if now <= close:
            continue

        jcd = str(row.get("jcd")).zfill(2)
        rno = int(row.get("rno") or 0)
        url = base.official_url("raceresult", day, jcd, rno)
        try:
            result = report.parse_payout(base.fetch(url))
        except Exception as exc:
            print(f"hit result pending {jcd} {rno}R: {type(exc).__name__}", flush=True)
            continue
        if result.get("status") != "settled":
            continue

        picks = set(report.disclosed_picks(row))
        matches = [(combo, int(yen)) for combo, yen in (result.get("payouts") or {}).items() if combo in picks]
        if not matches:
            continue

        winner, payout = max(matches, key=lambda item: item[1])
        try:
            _send_hit_channel(_message(row, winner, payout, result))
        except Exception as exc:
            print(f"hit alert failed {jcd} {rno}R: {type(exc).__name__}", flush=True)
            continue

        _append_jsonl(DELIVERY_PATH, {
            "day": day,
            "key": delivery_key,
            "jcd": jcd,
            "rno": rno,
            "venue": row.get("venue"),
            "winning_combo": winner,
            "payout_per_100": payout,
            "prediction_sent_at": row.get("sent_at"),
            "sent_at": datetime.now(base.JST).isoformat(),
            "status": "sent",
        })
        sent.add(delivery_key)
        delivered += 1
        print(f"hit alert sent {jcd} {rno}R {winner} {payout}", flush=True)

    return delivered
