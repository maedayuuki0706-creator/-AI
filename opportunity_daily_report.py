from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path

JST = timezone(timedelta(hours=9))
DAY = os.getenv("REPORT_DAY") or datetime.now(JST).strftime("%Y%m%d")
LOG_PATH = Path("data/opportunity_alert_deliveries.jsonl")
RESULT_PATH = Path(f"data/official_results/{DAY}.json")
OUT_PATH = Path(f"data/opportunity_report_{DAY}.json")
STREAMS = ("mid_odds", "longshot")


def read_jsonl(path: Path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def picks(row):
    return {
        str(item.get("combination") or "").strip()
        for item in (row.get("picks") or [])
        if isinstance(item, dict) and item.get("combination")
    }


def main():
    results = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    latest = {}
    for row in read_jsonl(LOG_PATH):
        if str(row.get("day") or "") != DAY:
            continue
        stream = str(row.get("stream") or "")
        if stream not in STREAMS:
            continue
        jcd = str(row.get("jcd") or "").zfill(2)
        try:
            rno = int(row.get("rno") or 0)
        except (TypeError, ValueError):
            continue
        if not 1 <= rno <= 12:
            continue
        key = (stream, jcd, rno)
        old = latest.get(key)
        if old is None or str(row.get("sent_at") or "") >= str(old.get("sent_at") or ""):
            latest[key] = row

    venues = defaultdict(lambda: {
        "jcd": None,
        "mid_odds": {"hits": 0, "logged": 0, "settled": 0},
        "longshot": {"hits": 0, "logged": 0, "settled": 0},
    })
    details = []

    for (stream, jcd, rno), row in sorted(latest.items(), key=lambda kv: (kv[0][1], kv[0][2], kv[0][0])):
        venue = str(row.get("venue") or jcd)
        v = venues[venue]
        v["jcd"] = jcd
        v[stream]["logged"] += 1
        result = results.get(f"{jcd}:{rno}") or {}
        status = result.get("status")
        winners = set((result.get("payouts") or {}).keys()) if status == "settled" else set()
        matched = winners & picks(row)
        hit = bool(matched)
        if status == "settled":
            v[stream]["settled"] += 1
        if hit:
            v[stream]["hits"] += 1
        details.append({
            "venue": venue,
            "jcd": jcd,
            "rno": rno,
            "stream": stream,
            "status": status or "missing",
            "hit": hit,
            "winner": sorted(matched)[0] if matched else None,
        })

    out = {
        "day": DAY,
        "generated_at": datetime.now(JST).isoformat(),
        "denominator_per_venue": 12,
        "note": "hits are rejudged from opportunity picks against official trifecta results; missing/no-pick races remain misses when displayed as /12",
        "venues": dict(sorted(venues.items(), key=lambda kv: kv[1]["jcd"] or "99")),
        "details": details,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out["venues"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
