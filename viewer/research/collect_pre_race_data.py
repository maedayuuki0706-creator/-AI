#!/usr/bin/env python3
"""Private, bounded race PREVIEW dataset: no model, production or published data writes.

Third-party source: https://github.com/BoatraceCSV/boatracecsv.github.io
All as-of timestamps are verified against each race's local deadline.
Missing/late values NEVER masquerade as pre-race observations.
Motor stats are captured as independent research rows, NOT assumed pre-race safe.
"""
from __future__ import annotations
import argparse
import csv
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import re
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SOURCE = "https://raw.githubusercontent.com/BoatraceCSV/boatracecsv.github.io/main/data"
CATEGORIES = (
    "previews/stt", "previews/sui", "previews/tkz",
    "previews/od3", "previews/original_exhibition",
    "programs/motor_stats", "programs/motor_history"
)
ODDS_PATTERN = re.compile(r"^3連単_([1-6])-([1-6])-([1-6])$")
MAX_CSV_BYTES = 3_000_000

def download(category: str, day: date):
    url = f"{SOURCE}/{category}/{day:%Y/%m/%d}.csv"
    request = Request(url, headers={"User-Agent": "BoatAINavi-Research/1.0 (bounded low-rate noncommercial evaluation)"})
    with urlopen(request, timeout=25) as r:
        if r.status != 200:
            raise RuntimeError(f"unexpected HTTP {r.status}")
        blob = r.read(MAX_CSV_BYTES + 1)
    if len(blob) > MAX_CSV_BYTES:
        raise ValueError("maximum CSV size exceeded")
    content = blob.decode("utf-8-sig")
    rows = list(csv.DictReader(StringIO(content)))
    if not rows:
        raise ValueError("empty CSV")
    return rows, url, len(blob)

def number(s):
    try:
        return float(s) if s not in ("", None, "-", "欠", "F", "L") else None
    except (ValueError, TypeError):
        return None

def before_deadline(row: dict):
    day = row.get("レース日")
    deadline = row.get("締切時刻")
    asof = row.get("取得日時")
    try:
        observed = datetime.fromisoformat(asof)
        if observed.tzinfo is None:
            return None
        cutoff = datetime.fromisoformat(f"{day}T{deadline}:00+09:00")
        return observed <= cutoff
    except (ValueError, TypeError):
        return None

def initialize(conn):
    conn.executescript("""
      PRAGMA journal_mode=WAL;
      CREATE TABLE IF NOT EXISTS preview(
        code TEXT NOT NULL, category TEXT NOT NULL, race_day TEXT, venue TEXT,
        deadline TEXT, asof TEXT, before_deadline INTEGER,
        source_url TEXT,
        PRIMARY KEY(code, category)
      );
      CREATE TABLE IF NOT EXISTS exhibition(
        code TEXT NOT NULL, boat INTEGER NOT NULL,
        start_course INTEGER, start_exhibition REAL, exhibition_time REAL,
        tilt REAL, weight REAL, weight_adjustment REAL,
        original_1 REAL, original_2 REAL, original_3 REAL,
        PRIMARY KEY(code, boat)
      );
      CREATE TABLE IF NOT EXISTS conditions(
        code TEXT PRIMARY KEY, wind REAL, wind_direction TEXT, wave_cm REAL,
        temperature REAL, water_temperature REAL, weather TEXT
      );
      CREATE TABLE IF NOT EXISTS odds3(
        code TEXT NOT NULL, combination TEXT NOT NULL, odds REAL NOT NULL,
        asof TEXT NOT NULL, PRIMARY KEY(code, combination)
      );
      CREATE TABLE IF NOT EXISTS motor_stats(
        day TEXT NOT NULL, venue TEXT NOT NULL, motor TEXT NOT NULL,
        motor_epoch TEXT, starts REAL, win_rate REAL,
        two_rate REAL, three_rate REAL,
        source_url TEXT, PRIMARY KEY(day, venue, motor)
      );
      CREATE INDEX IF NOT EXISTS prev_date ON preview(race_day);
      CREATE INDEX IF NOT EXISTS motors_venue ON motor_stats(venue,motor);
    """)

def upsert_exhibition(conn, code, boat, name, value):
    allowed={"start_course","start_exhibition","exhibition_time","tilt",
             "weight","weight_adjustment","original_1","original_2","original_3"}
    if name not in allowed or value is None:
        return
    conn.execute("INSERT OR IGNORE INTO exhibition(code,boat) VALUES (?,?)", (code,boat))
    conn.execute(f"UPDATE exhibition SET {name}=? WHERE code=? AND boat=?", (value,code,boat))

def feed(conn, category, day, rows, url, counters):
    n=0
    if category == "programs/motor_stats":
        for r in rows:
            venue=r.get("場コード","")
            motor=r.get("モーター番号","")
            if not (venue.isdigit() and 1 <= int(venue) <= 24 and motor.isdigit()):
                counters["bad_motor_row"]+=1
                continue
            conn.execute("""
              INSERT OR REPLACE INTO motor_stats VALUES (?,?,?,?,?,?,?,?,?)
            """, (str(day),venue.zfill(2),motor,r.get("モーター期起算日"),
                  number(r.get("出走数")),number(r.get("勝率")),
                  number(r.get("2連対率")),number(r.get("3連対率")),url))
            n+=1
        counters["motor_stats_rows"]+=n
        return n
    if category == "programs/motor_history":
        # Do not ingest post-race "着順列" as a deadline-time feature.
        counters["motor_history_source_rows"] += len(rows)
        return len(rows)
    for row in rows:
        code=row.get("レースコード","")
        if len(code)!=12 or not code.isdigit() or code[:8] != day.strftime("%Y%m%d"):
            counters["bad_race_code"]+=1
            continue
        valid=before_deadline(row)
        if valid is not True:
            counters["rejected_late_or_unknown"]+=1
            continue
        prior=conn.execute("SELECT asof FROM preview WHERE code=? AND category=?", (code,category)).fetchone()
        if prior and prior[0]>=row.get("取得日時",""):
            counters["duplicate_older"]+=1
            continue
        conn.execute("""
          INSERT OR REPLACE INTO preview VALUES (?,?,?,?,?,?,?,?)
        """, (code,category,row.get("レース日"),code[8:10],
              row.get("締切時刻"),row.get("取得日時"),1,url))
        if category=="previews/sui":
            conn.execute("""
              INSERT OR REPLACE INTO conditions VALUES (?,?,?,?,?,?,?)
            """,(code,number(row.get("風速(m)")),row.get("風向"),
                 number(row.get("波の高さ(cm)")),number(row.get("気温(℃)")),
                 number(row.get("水温(℃)")),row.get("天候")))
        elif category=="previews/od3":
            count=0
            for key,value in row.items():
                match=ODDS_PATTERN.match(key)
                if not match or len(set(match.groups()))!=3:
                    continue
                odd=number(value)
                if odd is None or odd<=0:
                    continue
                conn.execute("INSERT OR REPLACE INTO odds3 VALUES (?,?,?,?)",
                             (code,"-".join(match.groups()),odd,row.get("取得日時")))
                count+=1
            counters["valid_trifecta_odds_values"]+=count
            if count != 120:
                counters["incomplete_120_odds_races"]+=1
        elif category in ("previews/tkz","previews/stt","previews/original_exhibition"):
            for boat in range(1,7):
                if category=="previews/tkz":
                    mapping={
                        "exhibition_time":row.get(f"艇{boat}_展示タイム"),
                        "tilt":row.get(f"艇{boat}_チルト"),
                        "weight":row.get(f"艇{boat}_体重(kg)"),
                        "weight_adjustment":row.get(f"艇{boat}_体重調整(kg)")}
                elif category=="previews/stt":
                    mapping={
                        "start_course":row.get(f"艇{boat}_コース"),
                        "start_exhibition":row.get(f"艇{boat}_スタート展示")}
                else:
                    mapping={
                        "original_1":row.get(f"艇{boat}_値1"),
                        "original_2":row.get(f"艇{boat}_値2"),
                        "original_3":row.get(f"艇{boat}_値3")}
                for name, value in mapping.items():
                    x=number(value)
                    if name=="start_course" and (x is None or int(x)!=x or x<1 or x>6):
                        continue
                    upsert_exhibition(conn,code,boat,name,int(x) if name=="start_course" else x)
        n+=1
    counters[f"{category}_pre_deadline_races"]+=n
    return n

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--start",type=date.fromisoformat,default=date(2026,10,1))
    parser.add_argument("--end",type=date.fromisoformat,default=date(2026,10,23))
    parser.add_argument("--delay",type=float,default=1.6)
    parser.add_argument("--out",default="/tmp/boat-navi-preview-research")
    args=parser.parse_args()
    if not (0 <= (args.end-args.start).days <= 31):
        parser.error("maximum 32 days per independent research sample")
    output=Path(args.out)
    output.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(str(output/"preview_research.sqlite"))
    initialize(conn)
    quality=Counter()
    failures=[]
    entries=[]
    for i in range((args.end-args.start).days+1):
        d=args.start+timedelta(days=i)
        for category in CATEGORIES:
            try:
                rows,url,byte_count=download(category,d)
                count=feed(conn,category,d,rows,url,quality)
                quality["downloaded_files"]+=1
                quality["downloaded_bytes"]+=byte_count
                entries.append({"day":str(d),"kind":category,"status":"ok","rows":len(rows),"accepted":count})
            except HTTPError as e:
                state="404_missing" if e.code==404 else f"http_{e.code}"
                failures.append({"day":str(d),"kind":category,"error":state})
                entries.append({"day":str(d),"kind":category,"status":state})
                if e.code in (403,429):
                    quality["provider_blocked"]+=1
                    break
            except (URLError,TimeoutError,RuntimeError,ValueError) as e:
                failures.append({"day":str(d),"kind":category,"error":str(e)[:150]})
                entries.append({"day":str(d),"kind":category,"status":"failed"})
            finally:
                time.sleep(max(1.5,args.delay))
        conn.commit()
        print("PREVIEW_PROGRESS",d,"files",quality["downloaded_files"],"failures",len(failures),flush=True)
        if quality["provider_blocked"]:
            break
    sqlite_counts={}
    for tab in ("preview","exhibition","conditions","odds3","motor_stats"):
        sqlite_counts[tab]=conn.execute(f"SELECT COUNT(*) FROM {tab}").fetchone()[0]
    sqlite_counts["complete_120_odds_races"]=conn.execute(
        "SELECT COUNT(*) FROM (SELECT code,COUNT(*) n FROM odds3 GROUP BY code HAVING n=120)"
    ).fetchone()[0]
    sqlite_counts["joined_stt_tkz_sui_od3"]=conn.execute("""
        SELECT COUNT(*) FROM (
          SELECT code FROM preview
          WHERE category IN ('previews/stt','previews/tkz','previews/sui','previews/od3')
          GROUP BY code HAVING COUNT(*)=4
        )
    """).fetchone()[0]
    integrity=conn.execute("PRAGMA quick_check").fetchone()[0]
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    audit={
        "schema":"boat-navi-asof-preview-research-v1",
        "source":"third-party BoatraceCSV; not official original-verified",
        "period":[str(args.start),str(args.end)],
        "created_at_utc":datetime.now(timezone.utc).isoformat(),
        "counts":sqlite_counts,"quality":dict(quality),
        "requested_files":((args.end-args.start).days+1)*len(CATEGORIES),
        "errors":failures,"integrity":integrity,"entries":entries,
        "critical_note":"Preview odds/exhibition accepted only when acquisition timestamp <= deadline. Motor statistics may contain end-of-day leakage; NEVER train on them without additional date-safe checks.",
        "rights":"Research only; no public republication, model input, or production changes."
    }
    (output/"audit.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("PREVIEW_FINAL "+json.dumps({k:v for k,v in audit.items() if k not in ("entries","errors")},ensure_ascii=False),flush=True)
    print("PREVIEW_ERRORS "+json.dumps(failures,ensure_ascii=False),flush=True)
if __name__=="__main__":
    main()
