"""Sync exhibition-vs-race data into the 足回り推移 Google Sheet.

The sheet keeps raw exhibition and official result fields together so later
motor/racer learning can measure how faithfully exhibition signals translate
into race performance.
"""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import json
from functools import lru_cache
import os
import re
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

import direct_discord_notify as base

SPREADSHEET_ID = os.getenv(
    "BOAT_SHEET_ID",
    "1dbUPyfxjIRaT-G8F_LlGMX7Ld_ZB951UmF4HpW_PYJo",
)
SHEET_NAME = os.getenv("FOOT_TREND_SHEET", "足回り推移")
ROOT = Path("data/exhibition_log")

NEW_HEADERS = [
    "本番進入",
    "ST差(本番-展示)",
    "進入差(本番-展示)",
    "着順差(本番-展示順位)",
    "展示上位→3着内(1/0)",
    "展示下位→3着内(1/0)",
    "決まり手",
    "展示再現判定",
]

# 1-based sheet columns.
COL = {
    "venue": 1, "section_start": 2, "day": 3, "section_day": 4,
    "racer_id": 5, "name": 6, "class": 7, "motor": 8, "boat": 9,
    "rno": 10, "run_no": 11, "lane": 12, "exhibition_time": 13,
    "actual_st": 17, "finish": 18, "exhibition_rank": 19,
    "wind_m": 30, "learning_weight": 32, "compare_kind": 33,
    "memo": 34, "source": 35, "measure_kind": 36,
    "actual_course": 37, "method": 43,
    "exhibition_course": 45, "exhibition_st": 46, "tilt": 47,
    "propeller": 48, "parts": 49, "wave_cm": 50,
    "air_temp_c": 51, "water_temp_c": 52, "wind_dir": 53, "wind_raw": 54,
}


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _day_sheet(day: str) -> str:
    try:
        return datetime.strptime(day, "%Y%m%d").strftime("%Y/%m/%d")
    except ValueError:
        return str(day)


def _norm_day(value: str) -> str:
    text = str(value or "").strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y%m%d")
        except ValueError:
            pass
    return text.replace("/", "").replace("-", "")


def _num(value):
    if value in (None, ""):
        return ""
    return value


def _key(day: str, venue: str, rno, racer_id: str) -> tuple[str, str, int, str] | None:
    try:
        race = int(float(rno))
    except (TypeError, ValueError):
        return None
    rid = str(racer_id or "").strip()
    venue = str(venue or "").strip()
    day = _norm_day(day)
    if not day or not venue or not rid or not race:
        return None
    return day, venue, race, rid


def _load_records() -> list[dict]:
    records = []
    for day_dir in sorted(p for p in ROOT.iterdir() if p.is_dir() and p.name.isdigit()):
        for path in sorted(day_dir.glob("*.json")):
            payload = _read_json(path)
            if not payload:
                continue
            day = str(payload.get("day") or day_dir.name)
            venue = str(payload.get("venue") or "")
            jcd = str(payload.get("jcd") or "").zfill(2)
            try:
                rno = int(payload.get("rno") or 0)
            except (TypeError, ValueError):
                continue
            for row in payload.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                rid = str(row.get("racer_id") or "").strip()
                if not rid:
                    continue
                records.append({
                    "day": day,
                    "venue": venue,
                    "jcd": jcd,
                    "rno": rno,
                    "racer_id": rid,
                    "name": str(row.get("name") or ""),
                    "lane": row.get("lane"),
                    "class": str(row.get("current_class") or ""),
                    "motor": row.get("motor_number"),
                    "boat": row.get("boat_number"),
                    "exhibition_time": row.get("exhibition_time"),
                    "exhibition_rank": row.get("exhibition_rank"),
                    "exhibition_course": row.get("exhibition_course"),
                    "exhibition_st": row.get("exhibition_st"),
                    "tilt": row.get("tilt"),
                    "propeller": row.get("propeller_exchange"),
                    "parts": row.get("parts_exchange"),
                    "actual_course": row.get("actual_course"),
                    "actual_st": row.get("actual_st"),
                    "finish": row.get("finish"),
                    "method": row.get("method"),
                    "wind_m": row.get("wind_m"),
                    "wave_cm": row.get("wave_cm"),
                    "air_temp_c": row.get("air_temp_c"),
                    "water_temp_c": row.get("water_temp_c"),
                    "source": payload.get("source") or "BOAT RACE official beforeinfo",
                })
    records.sort(key=lambda x: (x["day"], x["jcd"], x["rno"], int(x.get("lane") or 9)))
    run_counts = defaultdict(int)
    for rec in records:
        k = (rec["day"], rec["racer_id"])
        run_counts[k] += 1
        rec["run_no"] = run_counts[k]
    return records


def _existing_map(values: list[list[str]]) -> dict[tuple[str, str, int, str], int]:
    out = {}
    for rowno, row in enumerate(values[1:], start=2):
        def v(index):
            return row[index - 1] if index - 1 < len(row) else ""
        key = _key(v(COL["day"]), v(COL["venue"]), v(COL["rno"]), v(COL["racer_id"]))
        if key:
            out[key] = rowno
    return out


def _section_starts(values: list[list[str]]) -> dict[str, list[str]]:
    starts = defaultdict(set)
    for row in values[1:]:
        venue = row[COL["venue"] - 1].strip() if len(row) >= COL["venue"] else ""
        start = row[COL["section_start"] - 1].strip() if len(row) >= COL["section_start"] else ""
        start = _norm_day(start)
        if venue and len(start) == 8 and start.isdigit():
            starts[venue].add(start)
    return {venue: sorted(days) for venue, days in starts.items()}


VENUE_CODES = {name: code for code, name in base.VENUES.items()}


@lru_cache(maxsize=512)
def _official_section_start(day: str, jcd: str) -> str:
    """Current-meeting start from the official race page, with calendar fallback."""
    try:
        current = datetime.strptime(day, "%Y%m%d").date()
    except ValueError:
        return ""
    try:
        raw = base.fetch(base.official_url("racelist", day, str(jcd).zfill(2), 1))
        text = base.textify(raw)
        match = re.search(r"(\d{1,2})月(\d{1,2})日初日", text)
        if match:
            year = current.year
            start = datetime(year, int(match.group(1)), int(match.group(2))).date()
            if (start - current).days > 30:
                start = datetime(year - 1, int(match.group(1)), int(match.group(2))).date()
            elif (current - start).days > 330:
                start = datetime(year + 1, int(match.group(1)), int(match.group(2))).date()
            return start.strftime("%Y%m%d")
    except Exception:
        pass

    start = current
    for _ in range(7):
        prev = start - timedelta(days=1)
        try:
            if str(jcd).zfill(2) not in base.discover_venues(prev.strftime("%Y%m%d")):
                break
        except Exception:
            break
        start = prev
    return start.strftime("%Y%m%d")


def _section_info(venue: str, day: str, starts: dict[str, list[str]], jcd: str = "") -> tuple[str, str]:
    try:
        d = datetime.strptime(day, "%Y%m%d").date()
    except ValueError:
        return "", ""
    eligible = []
    for raw in starts.get(venue, []):
        try:
            s = datetime.strptime(raw, "%Y%m%d").date()
        except ValueError:
            continue
        delta = (d - s).days
        if 0 <= delta <= 7:
            eligible.append((s, delta))
    if eligible:
        s, delta = max(eligible, key=lambda x: x[0])
        return s.strftime("%Y/%m/%d"), str(delta + 1)

    code = str(jcd or VENUE_CODES.get(venue, "")).zfill(2)
    if code and code in base.VENUES:
        raw_start = _official_section_start(day, code)
        try:
            s = datetime.strptime(raw_start, "%Y%m%d").date()
            delta = (d - s).days
            if 0 <= delta <= 7:
                return s.strftime("%Y/%m/%d"), str(delta + 1)
        except ValueError:
            pass
    return "", ""


def _needs_enrichment(rec: dict, existing_row: list[str] | None) -> bool:
    if rec.get("class") and rec.get("motor") not in (None, "") and rec.get("boat") not in (None, ""):
        return False
    if existing_row:
        have_class = len(existing_row) >= COL["class"] and str(existing_row[COL["class"] - 1]).strip()
        have_motor = len(existing_row) >= COL["motor"] and str(existing_row[COL["motor"] - 1]).strip()
        have_boat = len(existing_row) >= COL["boat"] and str(existing_row[COL["boat"] - 1]).strip()
        if have_class and have_motor and have_boat:
            return False
    return True


def _enrich_races(records: list[dict], existing_values: list[list[str]], existing: dict) -> None:
    by_key = {}
    for rec in records:
        k = _key(rec["day"], rec["venue"], rec["rno"], rec["racer_id"])
        row = existing_values[existing[k] - 1] if k in existing else None
        if _needs_enrichment(rec, row):
            by_key.setdefault((rec["day"], rec["jcd"], rec["rno"]), []).append(rec)
    if not by_key:
        return

    def fetch_one(key):
        day, jcd, rno = key
        try:
            boats = base.parse_racelist_boats(day, jcd, rno)
        except Exception:
            boats = []
        return key, {str(b.get("racer_id") or ""): b for b in boats}

    results = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = [pool.submit(fetch_one, key) for key in by_key]
        for future in as_completed(jobs):
            key, racers = future.result()
            results[key] = racers

    for key, recs in by_key.items():
        racers = results.get(key, {})
        for rec in recs:
            boat = racers.get(rec["racer_id"]) or {}
            if not rec.get("class"):
                rec["class"] = str(boat.get("current_class") or "")
            if rec.get("motor") in (None, ""):
                rec["motor"] = boat.get("motor_number")
            if rec.get("boat") in (None, ""):
                rec["boat"] = boat.get("boat_number")


def _build_prefix(rec: dict, section_start: str, section_day: str) -> list:
    # A:AK (37 columns). Derived columns AL:AP and AR are ARRAYFORMULA-driven.
    row = [""] * 37
    def setv(name, value):
        row[COL[name] - 1] = _num(value)
    setv("venue", rec["venue"])
    setv("section_start", section_start)
    setv("day", _day_sheet(rec["day"]))
    setv("section_day", section_day)
    setv("racer_id", rec["racer_id"])
    setv("name", rec["name"])
    setv("class", rec.get("class"))
    setv("motor", rec.get("motor"))
    setv("boat", rec.get("boat"))
    setv("rno", rec["rno"])
    setv("run_no", rec.get("run_no"))
    setv("lane", rec.get("lane"))
    setv("exhibition_time", rec.get("exhibition_time"))
    setv("actual_st", rec.get("actual_st"))
    setv("finish", rec.get("finish"))
    setv("exhibition_rank", rec.get("exhibition_rank"))
    setv("wind_m", rec.get("wind_m"))
    setv("learning_weight", 1)
    setv("compare_kind", "展示→本番")
    memo = []
    if rec.get("wave_cm") not in (None, ""):
        memo.append(f"波高{rec['wave_cm']}cm")
    setv("memo", " / ".join(memo))
    setv("source", "BOAT RACE公式 展示・結果")
    setv("measure_kind", "展示→本番")
    setv("actual_course", rec.get("actual_course"))
    return row


def _tail_values(rec: dict) -> list:
    # AS:BB (10 columns)
    return [
        _num(rec.get("exhibition_course")),
        _num(rec.get("exhibition_st")),
        _num(rec.get("tilt")),
        _num(rec.get("propeller")),
        _num(rec.get("parts")),
        _num(rec.get("wave_cm")),
        _num(rec.get("air_temp_c")),
        _num(rec.get("water_temp_c")),
        "",
        _num(rec.get("wind_m")),
    ]


def _chunked(items, size=250):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def main() -> int:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON secret is required")
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    book = gspread.authorize(creds).open_by_key(SPREADSHEET_ID)
    ws = book.worksheet(SHEET_NAME)

    # Keep the reserved AK:AR block as the exhibition-vs-race analysis section.
    ws.update([NEW_HEADERS], "AK1", raw=True)

    values = ws.get_all_values()
    existing = _existing_map(values)
    starts = _section_starts(values)
    records = _load_records()
    _enrich_races(records, values, existing)

    missing = []
    existing_updates = []

    # Repair recent rows that already have official ST/results but missed their
    # meeting start/day. This is intentionally limited to recent rows so old
    # curated history is not rewritten.
    today_date = datetime.now(base.JST).date()
    for rowno, row in enumerate(values[1:], start=2):
        def rv(index):
            return row[index - 1] if index - 1 < len(row) else ""
        venue = str(rv(COL["venue"]) or "").strip()
        day = _norm_day(rv(COL["day"]))
        if not venue or not re.fullmatch(r"20\d{6}", day):
            continue
        try:
            age = (today_date - datetime.strptime(day, "%Y%m%d").date()).days
        except ValueError:
            continue
        if not 0 <= age <= 14:
            continue
        if str(rv(COL["section_start"]) or "").strip() and str(rv(COL["section_day"]) or "").strip():
            continue
        section_start, section_day = _section_info(venue, day, starts, VENUE_CODES.get(venue, ""))
        if not section_start:
            continue
        if not str(rv(COL["section_start"]) or "").strip():
            existing_updates.append({"range": f"B{rowno}", "values": [[section_start]]})
        if not str(rv(COL["section_day"]) or "").strip():
            existing_updates.append({"range": f"D{rowno}", "values": [[section_day]]})

    for rec in records:
        k = _key(rec["day"], rec["venue"], rec["rno"], rec["racer_id"])
        if not k:
            continue
        rowno = existing.get(k)
        if rowno is None:
            section_start, section_day = _section_info(rec["venue"], rec["day"], starts, rec.get("jcd") or "")
            missing.append((rec, section_start, section_day))
            continue

        row = values[rowno - 1]
        def current(col):
            return row[col - 1] if col - 1 < len(row) else ""

        updates = []
        # Fill only authoritative raw fields when the sheet is blank.
        for colname, value in (
            ("class", rec.get("class")),
            ("motor", rec.get("motor")),
            ("boat", rec.get("boat")),
            ("exhibition_time", rec.get("exhibition_time")),
            ("actual_st", rec.get("actual_st")),
            ("finish", rec.get("finish")),
            ("exhibition_rank", rec.get("exhibition_rank")),
            ("actual_course", rec.get("actual_course")),
        ):
            if value in (None, "") or str(current(COL[colname])).strip():
                continue
            letter = gspread.utils.rowcol_to_a1(1, COL[colname]).rstrip("1")
            updates.append({"range": f"{letter}{rowno}", "values": [[value]]})

        # The official outcome method should refresh once the race settles.
        if rec.get("method") not in (None, "") and str(current(COL["method"])).strip() != str(rec.get("method")):
            updates.append({"range": f"AQ{rowno}", "values": [[rec.get("method")]]})

        tail = _tail_values(rec)
        # Fill blank AS:BB cells only; keep any manually curated values.
        for offset, value in enumerate(tail):
            col = 45 + offset
            if value in (None, "") or str(current(col)).strip():
                continue
            letter = gspread.utils.rowcol_to_a1(1, col).rstrip("1")
            updates.append({"range": f"{letter}{rowno}", "values": [[value]]})
        existing_updates.extend(updates)

    for chunk in _chunked(existing_updates, 300):
        ws.batch_update(chunk, raw=True)

    appended = 0
    if missing:
        start_row = len(values) + 1
        needed_last = start_row + len(missing) - 1
        if needed_last > ws.row_count:
            ws.add_rows(max(500, needed_last - ws.row_count + 100))

        prefixes = [_build_prefix(rec, sec_start, sec_day) for rec, sec_start, sec_day in missing]
        ws.append_rows(prefixes, value_input_option="RAW")
        end_row = start_row + len(missing) - 1

        # AQ is raw 決まり手. AR stays free for its ARRAYFORMULA.
        methods = [[_num(rec.get("method"))] for rec, _, _ in missing]
        ws.update(methods, f"AQ{start_row}:AQ{end_row}", raw=True)

        tails = [_tail_values(rec) for rec, _, _ in missing]
        ws.update(tails, f"AS{start_row}:BB{end_row}", raw=True)
        appended = len(missing)

    print(json.dumps({
        "sheet": SHEET_NAME,
        "records_seen": len(records),
        "existing_cell_updates": len(existing_updates),
        "rows_appended": appended,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
