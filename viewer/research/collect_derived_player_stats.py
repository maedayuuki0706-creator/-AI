#!/usr/bin/env python3
"""Bounded private-research ingestion of independently published daily race CSVs.

Source: https://github.com/BoatraceCSV/boatracecsv.github.io
The CSVs are THIRD-PARTY transformations. They are NOT validated official originals.
This job never touches existing site production, predictions, Discord/X, Sheets or secrets.
Raw CSV responses remain in memory. Normalized private SQLite is an Actions artifact.
"""
from __future__ import annotations
import argparse
import csv
from datetime import date, timedelta, datetime, timezone
from collections import Counter, defaultdict
from io import StringIO
import json
from pathlib import Path
import sqlite3
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

SOURCE = "https://raw.githubusercontent.com/BoatraceCSV/boatracecsv.github.io/main/data"
HEADERS = {"User-Agent": "BoatAINavi/1.0 research archive (low-rate single worker)"}


def dates(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def fetch(kind, d):
    yyyy, mm, dd = d.strftime("%Y"), d.strftime("%m"), d.strftime("%d")
    url = f"{SOURCE}/{kind}/{yyyy}/{mm}/{dd}.csv"
    with urlopen(Request(url, headers=HEADERS), timeout=18) as response:
        if response.status != 200:
            raise ValueError(f"HTTP {response.status}")
        blob = response.read(2_000_001)
    if len(blob) > 2_000_000:
        raise ValueError("CSV exceeds safety cap")
    text = blob.decode("utf-8-sig")
    rows = list(csv.DictReader(StringIO(text)))
    if not rows or "レースコード" not in rows[0]:
        raise ValueError("CSV has no usable race code")
    return rows, url


def init(db):
    db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS race(
            race_code TEXT PRIMARY KEY, day TEXT, venue TEXT, race_no INTEGER,
            first_boat INTEGER, second_boat INTEGER, third_boat INTEGER,
            deciding_method TEXT, wind_direction TEXT, wind_speed REAL, wave_cm REAL,
            result_source TEXT, card_source TEXT
        );
        CREATE TABLE IF NOT EXISTS entry(
            race_code TEXT NOT NULL, boat INTEGER NOT NULL, racer_id TEXT NOT NULL,
            name TEXT, race_course INTEGER NOT NULL, place INTEGER NOT NULL,
            start_timing REAL, national_win_rate REAL, local_win_rate REAL,
            motor_number TEXT,
            PRIMARY KEY(race_code,boat)
        );
        CREATE INDEX IF NOT EXISTS player_entry ON entry(racer_id);
        CREATE INDEX IF NOT EXISTS venue_day ON race(venue,day);
    """)


def number(s):
    try:
        return float(s) if s not in ("", None, "-", "—") else None
    except ValueError:
        return None


def is_permutation(values):
    return len(values) == 6 and set(values) == {"1", "2", "3", "4", "5", "6"}


def ingest_pair(conn, cards, results, card_url, result_url, counters):
    by_code = {r["レースコード"]: r for r in cards if len(r.get("レースコード", "")) == 12}
    counters["cards"] += len(cards)
    counters["results"] += len(results)
    for result in results:
        code = result.get("レースコード", "")
        card = by_code.get(code)
        if not card:
            counters["unjoined"] += 1
            continue
        ids = [card.get(f"艇{i}_登録番号", "") for i in range(1,7)]
        places = [result.get(f"{i}着_艇番", "") for i in range(1,7)]
        courses = [result.get(f"{i}コース_艇番", "") for i in range(1,7)]
        if (len(code) != 12 or not code.isdigit()
                or any(len(x) != 4 or not x.isdigit() for x in ids)
                or len(set(ids)) != 6
                or not is_permutation(places)
                or not is_permutation(courses)):
            counters["excluded_incomplete"] += 1
            continue
        day = code[:8]
        venue = code[8:10]
        race_no = int(code[10:12])
        if not (1 <= int(venue) <= 24 and 1 <= race_no <= 12):
            counters["excluded_incomplete"] += 1
            continue
        try:
            conn.execute(
                """INSERT INTO race VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (code, day, venue, race_no, int(places[0]), int(places[1]), int(places[2]),
                 result.get("決まり手", "").strip(), result.get("風向", ""),
                 number(result.get("風速(m)")), number(result.get("波の高さ(cm)")),
                 result_url, card_url)
            )
            for boat in range(1,7):
                i = boat-1
                place = places.index(str(boat))+1
                course = courses.index(str(boat))+1
                conn.execute("""INSERT INTO entry VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (code, boat, ids[i], card.get(f"艇{boat}_選手名", "").replace(" ", "").replace("　", ""),
                     course, place, number(result.get(f"{course}コース_スタートタイミング")),
                     number(card.get(f"艇{boat}_全国勝率")), number(card.get(f"艇{boat}_当地勝率")),
                     card.get(f"艇{boat}_モーター番号")))
            counters["joined_complete"] += 1
        except sqlite3.IntegrityError:
            counters["duplicate"] += 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from-date", type=date.fromisoformat, default=date(2026,1,1))
    p.add_argument("--to-date", type=date.fromisoformat, default=date(2026,10,23))
    p.add_argument("--out", default="/tmp/boat-navi-public-derived")
    p.add_argument("--delay", type=float, default=1.3)
    args = p.parse_args()
    if not (0 <= (args.to_date - args.from_date).days <= 365):
        p.error("maximum 366 days per one-off research run")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(out/"race_history.sqlite"))
    init(conn)
    quality = Counter()
    errors = []
    scanned = 0
    consecutive = 0
    for d in dates(args.from_date, args.to_date):
        scanned += 1
        try:
            cards, card_url = fetch("programs/race_cards", d)
            time.sleep(max(1.2,args.delay))
            results, result_url = fetch("results/realtime", d)
            quality["source_days"] += 1
            ingest_pair(conn, cards, results, card_url, result_url, quality)
            conn.commit()
            consecutive = 0
        except (HTTPError, URLError, ValueError, TimeoutError) as exc:
            errors.append({"day": d.isoformat(), "error": str(exc)[:100]})
            quality["failed_days"] += 1
            consecutive += 1
            if consecutive >= 7:
                quality["stopped_after_consecutive_errors"] = 1
                break
        if scanned % 20 == 0:
            print(f"INGEST_PROGRESS scanned_days={scanned} valid_races={quality['joined_complete']} failed_days={quality['failed_days']}", flush=True)
        time.sleep(max(1.2,args.delay))
    joined = conn.execute("SELECT COUNT(*) FROM race").fetchone()[0]
    entries = conn.execute("SELECT COUNT(*) FROM entry").fetchone()[0]
    unique_racers = conn.execute("SELECT COUNT(DISTINCT racer_id) FROM entry").fetchone()[0]
    # These are derived stats, not original CSV republishing.
    stats = {}
    for id_, course, boat, place, name in conn.execute("SELECT racer_id,race_course,boat,place,name FROM entry"):
        pstat = stats.setdefault(id_, {"name": name, "frame": [[0,0,0,0] for _ in range(6)],
                                              "course": [[0,0,0,0] for _ in range(6)]})
        for aggregate in (pstat["frame"][boat-1], pstat["course"][course-1]):
            aggregate[0] += 1
            if place <= 3:
                aggregate[place] += 1
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    (out/"player_frame_course_counts.json").write_text(
        json.dumps({"schema":"observed-player-stat-v1","period":[args.from_date.isoformat(),args.to_date.isoformat()],
                    "definition":"Joined third-party historical result+card; complete six-boat ranked finishes only; not full official career statistics",
                    "stats":stats},ensure_ascii=False,separators=(",",":"))+"\n", encoding="utf-8")
    report={"schema":"read-only-race-ingest-audit-v1","created_at":datetime.now(timezone.utc).isoformat(),
            "source":"BoatraceCSV github.io / 2026 CSV / third-party not official verified",
            "days_requested":(args.to_date-args.from_date).days+1,"days_processed":scanned,
            "from_date":str(args.from_date),"to_date":str(args.to_date),
            "quality":dict(quality),"verified_join_races":joined,
            "entry_rows":entries,"unique_racers":unique_racers,
            "warnings":["Inferred from third-party CSV; validate against official before model training",
                        "Incomplete races omitted; rates are sample-specific",
                        "No production changes, no public raw file republishing"],
            "errors":errors}
    (out/"audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("INGEST_FINAL "+json.dumps({k:v for k,v in report.items() if k!="errors"},ensure_ascii=False),flush=True)

if __name__ == "__main__":
    main()
