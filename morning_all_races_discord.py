"""Daily all-race morning Discord briefing.

Runs from the existing 5-minute notifier schedule. It sends each active venue's
remaining card once per day, with compact formations and odds-aware virtual
betting. Records are appended to prediction_log.jsonl so the existing workflow
persists them and later result evaluation can use the exact pre-race picks.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
from pathlib import Path
import time

import direct_discord_notify as base
from discord_formation import formation_summary
from virtual_betting import allocate_virtual_bets, compact_virtual_text
from daily_report import CARD_DIR, write_json


def sent_morning_keys(day: str) -> set[tuple[str, int]]:
    keys = set()
    if not base.LOG_PATH.exists():
        return keys
    for line in base.LOG_PATH.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        if row.get("day") == day and row.get("phase") in {"morning", "preliminary", "final"}:
            try:
                keys.add((str(row["jcd"]), int(row["rno"])))
            except Exception:
                pass
    return keys


def classify(analysis: dict) -> tuple[str, str]:
    heads = analysis["heads"]
    ranking = sorted(heads, key=heads.get, reverse=True)
    top = float(heads[ranking[0]])
    gap = top - float(heads[ranking[1]])
    if top >= .48 and gap >= .22:
        return "S", "堅"
    if top >= .39 and gap >= .14:
        return "A", "堅"
    if top >= .29 and gap >= .07:
        return "B", "中穴"
    return "C", "波乱"


def select_rows(analysis: dict) -> list[dict]:
    rows = analysis.get("trifecta", [])
    if not rows:
        return []
    picks = list(rows[:4])
    represented = {row["combination"].split("-")[0] for row in picks}
    for row in rows:
        head = row["combination"].split("-")[0]
        if head not in represented:
            picks.append(row)
            represented.add(head)
            if len(picks) >= 8:
                break
    for row in rows:
        if len(picks) >= 8:
            break
        if row not in picks:
            picks.append(row)
    return picks[:8]


def compact_formation(rows: list[dict]) -> tuple[str, dict]:
    combos = [row["combination"] for row in rows]
    summary = formation_summary(combos[:3], combos[3:6], combos[6:8])
    labels = {"main": "本", "cover": "押", "outsiders": "穴"}
    parts = []
    for section in summary["sections"]:
        forms = "・".join(item["text"] for item in section["formations"])
        parts.append(f"{labels[section['key']]}({section['point_count']}点):{forms}")
    return " / ".join(parts), summary


def compact_virtual(allocation: dict) -> str:
    if allocation.get("status") != "bet":
        return "仮0口(見送り)"
    bets = "/".join(
        f"{b['combination']}@{b['odds']:.1f}×{b['units']}"
        for b in allocation["bets"]
    )
    return f"仮{len(allocation['bets'])}点・{allocation['total_units']}口（{allocation['total_units'] * 100:,}円） {bets}"


def send_chunks(header: str, race_lines: list[str], records: list[dict]) -> int:
    """Journal each acknowledged chunk before attempting the next one."""
    chunks, lines, batch = [], [], []
    for line, record in zip(race_lines, records):
        if len((header + "\n" + "\n".join(lines + [line])).encode("utf-16-le")) // 2 > 1800 and lines:
            chunks.append((lines, batch))
            lines, batch = [], []
        lines.append(line)
        batch.append(record)
    if lines:
        chunks.append((lines, batch))
    delivered = 0
    for lines, batch in chunks:
        current = datetime.now(base.JST)
        valid = [(line, row) for line, row in zip(lines, batch)
                 if row["day"] == current.strftime("%Y%m%d") and base.minutes_until(current, row["deadline"]) >= 5]
        if not valid:
            continue
        base.send_discord(header + "\n" + "\n".join(line for line, _ in valid))
        sent_at = datetime.now(base.JST).isoformat()
        for _, row in valid:
            base.log_prediction({**row, "sent_at": sent_at})
            delivered += 1
        time.sleep(.65)
    return delivered


def run_once(now: datetime | None = None) -> int:
    now = (now or datetime.now(base.JST)).astimezone(base.JST)
    # Odds are much more useful after sales have opened. Retry on the existing
    # 5-minute schedule rather than sending a 07:30 card full of guessed odds.
    if now.hour < 8 or now.hour >= 22:
        return 0
    day = now.strftime("%Y%m%d")
    base.fetch.cache_clear()
    already = sent_morning_keys(day)

    try:
        venues = base.discover_venues(day)
    except Exception as exc:
        print(f"morning discover failed: {type(exc).__name__}")
        return 0
    if not venues:
        return 0

    venue_deadlines = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {pool.submit(base.deadlines, day, jcd): jcd for jcd in venues}
        for future in as_completed(jobs):
            jcd = jobs[future]
            try:
                venue_deadlines[jcd] = future.result()
            except Exception:
                venue_deadlines[jcd] = []

    card = {"day": day, "complete": all(len(venue_deadlines.get(jcd, [])) == 12 for jcd in venues),
            "checked_at": now.isoformat(), "races": {}}
    for jcd in venues:
        times = venue_deadlines.get(jcd, [])
        for rno in range(1, 13):
            card["races"][f"{jcd}:{rno}"] = {"jcd": jcd, "rno": rno,
                "deadline": times[rno - 1] if len(times) >= rno else None}
    write_json(CARD_DIR / f"{day}.json", card)

    targets = []
    passed = 0
    for jcd in venues:
        for rno, deadline in enumerate(venue_deadlines.get(jcd, []), 1):
            if base.minutes_until(now, deadline) < 5:
                passed += 1
                continue
            if (jcd, rno) not in already:
                targets.append((jcd, rno, deadline))
    if not targets:
        return 0

    analyses = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        jobs = {
            pool.submit(base.analyze_official, day, jcd, rno): (jcd, rno, deadline)
            for jcd, rno, deadline in targets
        }
        for future in as_completed(jobs):
            key = jobs[future]
            try:
                analysis = future.result()
            except Exception as exc:
                print(f"morning analysis failed {key[0]} {key[1]}R: {type(exc).__name__}")
                continue
            if analysis:
                analyses[key] = analysis

    if not analyses:
        return 0

    current = datetime.now(base.JST)
    analyses = {key: value for key, value in analyses.items()
                if current.strftime("%Y%m%d") == day and base.minutes_until(current, key[2]) >= 5}
    if not analyses:
        return 0

    odds_ready = sum(1 for analysis in analyses.values() if any(row.get("odds") for row in analysis.get("trifecta", [])))
    coverage = odds_ready / len(analyses)
    # Before 08:30, hold briefly for odds if most races still have no market.
    if now.hour == 8 and now.minute < 30 and coverage < .60:
        print(f"morning waiting for odds coverage={coverage:.1%}")
        return 0

    first_message = (
        f"🌅 **競艇AIナビ｜全レース予想＋仮想投票 {day[4:6]}/{day[6:8]}**\n"
        f"対象 {len(venues)}会場 / 今回 {len(analyses)}R / オッズ取得 {coverage:.0%}\n"
        "1口=100円換算。条件未達は0口見送り。展示前は暫定評価。\n"
        "集計は締切前の最新配信で差替え（追加投票なし）。オッズ・推定EVは利益保証ではありません。"
    )
    if passed:
        first_message += f"\n※締切間近・締切済み{passed}Rは今回の新規配信対象外（過去の配信は別途集計）。"
    base.send_discord(first_message)
    time.sleep(.65)

    sent_races = 0
    grouped = {jcd: [] for jcd in venues}
    for (jcd, rno, deadline), analysis in analyses.items():
        grouped.setdefault(jcd, []).append((rno, deadline, analysis))

    for jcd in venues:
        races = sorted(grouped.get(jcd, []), key=lambda item: item[0])
        if not races:
            continue
        lines = []
        records = []
        venue_units = 0
        for rno, deadline, analysis in races:
            rows = select_rows(analysis)
            if not rows:
                continue
            rank, category = classify(analysis)
            formation_text, summary = compact_formation(rows)
            allocation = allocate_virtual_bets(rows)
            venue_units += int(allocation.get("total_units") or 0)
            lines.append(
                f"**{rno}R {deadline}｜{rank}/{category}｜{summary['point_count']}点** {formation_text}\n"
                + compact_virtual(allocation)
            )
            combos = [row["combination"] for row in rows]
            records.append({
                "day": day,
                "jcd": jcd,
                "venue": base.VENUES.get(jcd, jcd),
                "rno": rno,
                "deadline": deadline,
                "phase": "morning",
                "source": "独自AI・朝全レース",
                "model_version": analysis.get("model_version"),
                "rank": rank,
                "category": category,
                "grade": analysis.get("grade"),
                "exhibition": analysis.get("preview", {}).get("exhibition_count") == 6,
                "main": combos[:3],
                "cover": combos[3:6],
                "outsiders": combos[6:8],
                "all_picks": combos,
                "heads": analysis.get("heads"),
                "message_format": "formation-virtual-v1",
                "point_count": summary["point_count"],
                "formation_sections": summary["sections"],
                "virtual_bets": allocation.get("bets", []),
                "virtual_status": allocation.get("status"),
                "virtual_unit_yen": 100,
                "virtual_selection_rule": "latest_pre_deadline_per_race",
                "virtual_total_units": allocation.get("total_units", 0),
                "virtual_min_return_units": allocation.get("min_return_units"),
                "odds_available": any(row.get("odds") is not None for row in analysis.get("trifecta", [])),
                "previous_form": analysis.get("previous_form", {}),
            })

        if not lines:
            continue
        header = f"🚤 **{base.VENUES.get(jcd, jcd)}｜全R予想**（展示前は暫定）"
        try:
            sent_races += send_chunks(header, lines, records)
        except Exception as exc:
            print(f"morning Discord failed {jcd}: {type(exc).__name__}")
            continue

    print(f"morning all-races sent races={sent_races} venues={len(venues)} coverage={coverage:.1%}")
    return sent_races


if __name__ == "__main__":
    raise SystemExit(0 if run_once() >= 0 else 1)
