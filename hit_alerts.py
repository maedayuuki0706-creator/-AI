"""Send Discord hit alerts after official BOAT RACE results are settled.

Normal predictions plus the independent 中穴AI / 穴AI calibration streams are
judged after the official result settles. Misses stay silent. Successful alerts
are journaled so later notifier passes do not send the same stream/race again.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path

import daily_report as report
import direct_discord_notify as base

DELIVERY_PATH = Path("data/hit_alert_deliveries.jsonl")
OPPORTUNITY_PATH = Path("data/opportunity_alert_deliveries.jsonl")
UNIT_YEN = 100
# 中穴/穴の的中速報は、この機能追加より前の終了レースを一斉送信しない。
OPPORTUNITY_ALERT_START = datetime(2026, 9, 16, 13, 38, tzinfo=base.JST)


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


def _stream_key(row: dict, stream: str) -> str:
    # Keep the legacy normal key unchanged so old delivery journals continue to
    # suppress duplicate normal alerts. Independent AI streams get their own key.
    if stream == "normal":
        return _race_key(row)
    return f"{stream}:{_race_key(row)}"


def _sent_keys(day: str) -> set[str]:
    return {
        str(row.get("key"))
        for row in _read_jsonl(DELIVERY_PATH)
        if row.get("day") == day and row.get("status") == "sent"
    }


def _venue_hit_count(day: str, venue: str, stream: str) -> int:
    """Count already delivered hits for this venue/category today."""
    seen = set()
    for row in _read_jsonl(DELIVERY_PATH):
        if row.get("day") != day or row.get("status") != "sent":
            continue
        if str(row.get("venue") or "") != str(venue or ""):
            continue
        # Old main-prediction delivery rows predate the explicit stream field.
        row_stream = str(row.get("stream") or "normal")
        if row_stream != stream:
            continue
        key = str(row.get("key") or "")
        if key and key not in seen:
            seen.add(key)
    return len(seen)


def _current_venue_tally(row: dict, stream: str) -> int:
    # The alert is formatted before its delivery record is appended, so include
    # the current hit here. Duplicate alerts are already blocked by _sent_keys.
    return _venue_hit_count(
        str(row.get("day") or ""),
        str(row.get("venue") or ""),
        stream,
    ) + 1


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
    alert = "万舟的中速報" if is_man else "的中速報"
    title = f"🚨🔵🎯 **【メイン予想】{alert}" if is_man else f"🔵🎯 **【メイン予想】{alert}"
    section = _hit_section(row, winner)
    grade = row.get("grade") or "-"
    score = row.get("selection_score")
    score_text = f" / 総合スコア **{int(score)}/100**" if score is not None else ""
    tally = _current_venue_tally(row, "normal")

    lines = [
        f"{title}｜{row.get('venue')} {row.get('rno')}R**",
        "カテゴリ：**メイン予想**",
        f"本日：**{tally}/12的中🎯**",
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


def _opportunity_picks(row: dict) -> set[str]:
    picks = set()
    for pick in row.get("picks") or []:
        if not isinstance(pick, dict):
            continue
        combo = str(pick.get("combination") or "").strip()
        if combo:
            picks.add(combo)
    return picks


def _opportunity_message(row: dict, winner: str, payout: int) -> str:
    stream = str(row.get("stream") or "")
    if stream == "mid_odds":
        icon = "🟡🔥🎯"
        label = "中穴"
        name = "中穴AI"
    else:
        icon = "🔴💣🎯"
        label = "穴"
        name = "穴AI"

    is_man = payout >= 10000
    alert = "万舟的中速報" if is_man else "的中速報"
    if is_man:
        icon = "🚨" + icon
    score = row.get("score")
    confidence = row.get("confidence") or "-"
    score_text = f"期待度 **{int(score)}/100** / 自信度 **{confidence}**" if score is not None else f"自信度 **{confidence}**"
    tally = _current_venue_tally(row, stream)

    predicted_odds = None
    for pick in row.get("picks") or []:
        if isinstance(pick, dict) and str(pick.get("combination") or "") == winner:
            try:
                predicted_odds = float(pick.get("odds"))
            except (TypeError, ValueError):
                predicted_odds = None
            break

    lines = [
        f"{icon} **【{label}】{alert}｜{row.get('venue')} {row.get('rno')}R**",
        f"カテゴリ：**{label}**",
        f"本日：**{tally}/12的中🎯**",
        f"結果：**{winner}　{payout:,}円**",
        f"的中：**{name}** / {score_text}",
    ]
    if predicted_odds is not None and predicted_odds > 0:
        lines.append(f"予想時オッズ：**{predicted_odds:.1f}倍**")
    lines.append(f"買い目：**{int(row.get('point_count') or len(_opportunity_picks(row)))}点**")
    return "\n".join(lines)


def _latest_opportunities(day: str) -> dict[tuple[str, str, int], dict]:
    chosen: dict[tuple[str, str, int], dict] = {}
    for row in _read_jsonl(OPPORTUNITY_PATH):
        if row.get("day") != day:
            continue
        stream = str(row.get("stream") or "")
        if stream not in {"mid_odds", "longshot"}:
            continue
        try:
            close = datetime.strptime(day + " " + row["deadline"], "%Y%m%d %H:%M").replace(tzinfo=base.JST)
        except (KeyError, TypeError, ValueError):
            continue
        if close < OPPORTUNITY_ALERT_START:
            continue
        jcd = str(row.get("jcd")).zfill(2)
        rno = int(row.get("rno") or 0)
        key = (stream, jcd, rno)
        previous = chosen.get(key)
        if previous is None or str(row.get("sent_at") or "") >= str(previous.get("sent_at") or ""):
            chosen[key] = row
    return chosen


def _load_official(day: str, jcd: str, rno: int) -> dict | None:
    url = base.official_url("raceresult", day, jcd, rno)
    try:
        result = report.parse_payout(base.fetch(url))
    except Exception as exc:
        print(f"hit result pending {jcd} {rno}R: {type(exc).__name__}", flush=True)
        return None
    if result.get("status") != "settled":
        return None
    return result


def check_and_send(day: str | None = None, now: datetime | None = None) -> int:
    now = (now or datetime.now(base.JST)).astimezone(base.JST)
    day = day or now.strftime("%Y%m%d")
    sent = _sent_keys(day)
    delivered = 0

    # Normal AI hit alerts.
    if base.LOG_PATH.exists():
        predictions = report.read_jsonl(base.LOG_PATH)
        chosen, _ = report.latest_predictions(predictions, day)

        for key, row in sorted(chosen.items()):
            delivery_key = _stream_key(row, "normal")
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
            result = _load_official(day, jcd, rno)
            if result is None:
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
                "stream": "normal",
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
            print(f"hit alert sent normal {jcd} {rno}R {winner} {payout}", flush=True)

    # Independent 中穴AI / 穴AI hit alerts. Each stream is judged separately,
    # so one race can legitimately produce normal + 中穴 + 穴 hit reports.
    for (stream, jcd, rno), row in sorted(_latest_opportunities(day).items()):
        delivery_key = _stream_key(row, stream)
        if delivery_key in sent:
            continue
        try:
            close = datetime.strptime(day + " " + row["deadline"], "%Y%m%d %H:%M").replace(tzinfo=base.JST)
        except (KeyError, TypeError, ValueError):
            continue
        if now <= close:
            continue

        picks = _opportunity_picks(row)
        if not picks:
            continue
        result = _load_official(day, jcd, rno)
        if result is None:
            continue
        matches = [(combo, int(yen)) for combo, yen in (result.get("payouts") or {}).items() if combo in picks]
        if not matches:
            continue

        winner, payout = max(matches, key=lambda item: item[1])
        try:
            _send_hit_channel(_opportunity_message(row, winner, payout))
        except Exception as exc:
            print(f"hit alert failed {stream} {jcd} {rno}R: {type(exc).__name__}", flush=True)
            continue

        _append_jsonl(DELIVERY_PATH, {
            "day": day,
            "key": delivery_key,
            "stream": stream,
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
        print(f"hit alert sent {stream} {jcd} {rno}R {winner} {payout}", flush=True)

    return delivered
