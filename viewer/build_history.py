"""Build an isolated, reproducible read-only result index from archived official results.

Usage: python3 viewer/build_history.py
Reads: data/official_results/YYYYMMDD.json
Writes ONLY: viewer/data/history/{start}-{end}.json + manifest.json
Never calls official sites, GitHub APIs, Sheets, Discord, X or live prediction code.
Does not run automatically; call explicitly from an isolated research job.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
import re
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "official_results"
TARGET = ROOT / "viewer" / "data" / "history"
NAME = re.compile(r"^20\d{6}\.json$")
COMBINATION = re.compile(r"^[1-6]-[1-6]-[1-6]$")


def chunked(items, size=7):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def parse_day(path: Path) -> tuple[list, int, int]:
    day = path.stem
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not an object")
    rows, skipped = [], 0
    for key, record in data.items():
        if not isinstance(record, dict):
            skipped += 1
            continue
        parts = key.split(":")
        payouts = record.get("payouts")
        if record.get("status") != "settled" or len(parts) != 2 or not isinstance(payouts, dict) or len(payouts) != 1:
            skipped += 1
            continue
        jcd, rno = parts
        combination, payout = next(iter(payouts.items()))
        try:
            amount = float(payout)
            valid = (
                jcd in {f"{i:02d}" for i in range(1, 25)}
                and 1 <= int(rno) <= 12
                and COMBINATION.fullmatch(combination)
                and len(set(combination.split("-"))) == 3
                and amount > 0 and amount < 1_000_000_000
                and amount.is_integer()
            )
        except (TypeError, ValueError, AttributeError):
            valid = False
        if not valid:
            skipped += 1
            continue
        rows.append([day, jcd, int(rno), combination, int(amount)])
    return rows, len(data), skipped


def main():
    files = sorted(p for p in SOURCE.glob("*.json") if NAME.fullmatch(p.name))
    if not files:
        raise SystemExit("No archived official results; existing index unchanged")
    TARGET.mkdir(parents=True, exist_ok=True)
    shards = []
    total = {"source": 0, "skip": 0, "indexed": 0}
    for group in chunked(files, 7):
        rows, source, skipped = [], 0, 0
        for path in group:
            day_rows, day_total, day_skipped = parse_day(path)
            rows.extend(day_rows)
            source += day_total
            skipped += day_skipped
        rows.sort(key=lambda r: (-int(r[0]), int(r[1]), int(r[2])))
        name = group[0].stem + "-" + group[-1].stem
        target = TARGET / (name + ".json")
        target.write_text(json.dumps({"source": "official_results", "from": group[0].stem, "to": group[-1].stem, "counts": {"source": source, "skip": skipped}, "rows": rows}, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        shards.append(name)
        total["source"] += source
        total["skip"] += skipped
        total["indexed"] += len(rows)
    manifest = {"schema": "race-history-manifest-v1", "generated_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(), "source": "data/official_results (saved archive)", "shards": shards, "from": files[0].stem, "to": files[-1].stem, "counts": total, "notes": "Only archived confirmed trifecta payouts, not all 24-venue races."}
    # Commit manifest after all shards are complete. A failed build leaves the old manifest intact.
    (TARGET / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
