"""Fast hit-alert settlement pass.

The legacy checker re-opened every settled losing race on every notifier run
because only successful alerts were journaled. This checker records settled
misses too and loads distinct race results concurrently, so hit monitoring does
not hold up the near-deadline prediction queue.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import daily_report as report
import direct_discord_notify as base
import hit_alerts as alerts
import sokuhou_delivery


def _processed_keys(day: str) -> set[str]:
    return {
        str(row.get("key"))
        for row in alerts._read_jsonl(alerts.DELIVERY_PATH)
        if row.get("day") == day and row.get("status") in {"sent", "miss", "suppressed"}
    }


def _closed(day: str, row: dict, now: datetime) -> bool:
    try:
        close = datetime.strptime(day + " " + row["deadline"], "%Y%m%d %H:%M").replace(tzinfo=base.JST)
    except (KeyError, TypeError, ValueError):
        return False
    return now > close


def _record(row: dict, stream: str, status: str, *, winner=None, payout=None, receipt=None) -> None:
    item = {
        "day": str(row.get("day") or ""),
        "key": alerts._stream_key(row, stream),
        "stream": stream,
        "jcd": str(row.get("jcd") or "").zfill(2),
        "rno": int(row.get("rno") or 0),
        "venue": row.get("venue"),
        "prediction_sent_at": row.get("sent_at"),
        "sent_at": datetime.now(base.JST).isoformat(),
        "status": status,
    }
    if winner is not None:
        item["winning_combo"] = winner
    if payout is not None:
        item["payout_per_100"] = int(payout)
    if receipt:
        item["message_id"] = receipt["message_id"]
        item["sent_at"] = receipt["sent_at"]
    alerts._append_jsonl(alerts.DELIVERY_PATH, item)


def _normal_candidates(day: str, now: datetime, processed: set[str]) -> list[tuple[str, dict]]:
    if not base.LOG_PATH.exists():
        return []
    predictions = report.read_jsonl(base.LOG_PATH)
    chosen, _ = report.latest_predictions(predictions, day)
    out = []
    for _, row in sorted(chosen.items()):
        key = alerts._stream_key(row, "normal")
        if key not in processed and _closed(day, row, now):
            out.append(("normal", row))
    return out


def _opportunity_candidates(day: str, now: datetime, processed: set[str]) -> list[tuple[str, dict]]:
    out = []
    for (stream, _jcd, _rno), row in sorted(alerts._latest_opportunities(day).items()):
        key = alerts._stream_key(row, stream)
        if key in processed or not _closed(day, row, now):
            continue
        if not alerts._opportunity_picks(row):
            continue
        out.append((stream, row))
    return out


def check_and_send(day: str | None = None, now: datetime | None = None) -> int:
    """Settle unprocessed races once; hits notify, misses are silently journaled."""
    if sokuhou_delivery.paused():
        return 0
    now = (now or datetime.now(base.JST)).astimezone(base.JST)
    day = day or now.strftime("%Y%m%d")
    processed = _processed_keys(day)
    candidates = _normal_candidates(day, now, processed) + _opportunity_candidates(day, now, processed)
    if not candidates:
        return 0

    by_race: dict[tuple[str, int], list[tuple[str, dict]]] = {}
    for stream, row in candidates:
        race = (str(row.get("jcd") or "").zfill(2), int(row.get("rno") or 0))
        by_race.setdefault(race, []).append((stream, row))

    results = {}
    workers = min(10, max(1, len(by_race)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(alerts._load_official, day, jcd, rno): (jcd, rno) for jcd, rno in by_race}
        for future in as_completed(jobs):
            race = jobs[future]
            try:
                results[race] = future.result()
            except Exception as exc:
                print(f"fast hit result failed {race[0]} {race[1]}R: {type(exc).__name__}", flush=True)
                results[race] = None

    delivered = 0
    failures = 0
    for race, rows in by_race.items():
        result = results.get(race)
        if result is None:
            continue
        payouts = result.get("payouts") or {}
        for stream, row in rows:
            delivery_key = alerts._stream_key(row, stream)
            if delivery_key in processed:
                continue
            if stream == "normal":
                picks = set(report.disclosed_picks(row))
            else:
                picks = alerts._opportunity_picks(row)
            matches = [(combo, int(yen)) for combo, yen in payouts.items() if combo in picks]
            if not matches:
                _record(row, stream, "miss")
                processed.add(delivery_key)
                continue

            winner, payout = max(matches, key=lambda item: item[1])
            try:
                if not sokuhou_delivery.eligible(row):
                    _record(row, stream, "suppressed", winner=winner, payout=payout)
                    processed.add(delivery_key)
                    continue
                if stream == "normal":
                    message = alerts._message(row, winner, payout, result)
                else:
                    message = alerts._opportunity_message(row, winner, payout)
                durable_key = f"normal:{delivery_key}" if stream == "normal" else delivery_key
                receipt = sokuhou_delivery.deliver(
                    durable_key, message,
                    {"day": day, "stream": stream, "jcd": race[0], "rno": race[1],
                     "winning_combo": winner, "payout_per_100": payout},
                    sender=alerts._send_hit_channel,
                )
                if receipt.get("status") != "sent":
                    failures += 1
                    print(f"::error::Sokuhou held {durable_key}: {receipt.get('status')}", flush=True)
                    continue
            except Exception as exc:
                failures += 1
                print(f"hit alert failed {stream} {race[0]} {race[1]}R: {type(exc).__name__}", flush=True)
                continue

            _record(row, stream, "sent", winner=winner, payout=payout, receipt=receipt)
            processed.add(delivery_key)
            delivered += 1
            print(f"hit alert sent {stream} {race[0]} {race[1]}R {winner} {payout}", flush=True)

    if failures:
        raise RuntimeError(f"{failures} Sokuhou alerts need retry or receipt review")
    return delivered
