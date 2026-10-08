"""Direct BOAT RACE official -> Google Sheets ST analysis sync.

Isolated from prediction/delivery. It refreshes only two raw sheets used by
ST analysis formulas:
- ST当日出走_RAW: today's official lineups / average ST / F-L counts
- ST節間結果_RAW: finalized actual STs for the currently active meetings

The existing ST展開分析 sheet consumes these tabs. A failure here must never
stop Discord/X prediction delivery.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import json
import os
import re

import gspread
from google.oauth2.service_account import Credentials

import direct_discord_notify as base
import race_context

SPREADSHEET_ID = os.getenv(
    "BOAT_SHEET_ID",
    "1dbUPyfxjIRaT-G8F_LlGMX7Ld_ZB951UmF4HpW_PYJo",
)
TODAY_SHEET = os.getenv("ST_TODAY_SHEET", "ST当日出走_RAW")
RESULT_SHEET = os.getenv("ST_RESULT_SHEET", "ST節間結果_RAW")
ACTIVE_SHEET = "開催中会場"

TODAY_HEADER = [
    "日付", "場", "R", "締切", "枠", "登録番号", "級別", "展開材料",
    "F数", "当地勝率", "全国勝率", "平均ST", "L数", "全国2連率", "全国3連率",
]
RESULT_HEADER = [
    "日付", "場", "R", "枠", "登録番号", "選手名", "着順", "進入", "実ST", "決まり手",
    "3連単", "3連単払戻", "2連単", "2連単払戻", "確定",
]
VENUE_CODES = {name: code for code, name in base.VENUES.items()}


def _norm_day(value: str) -> str:
    text = str(value or "").strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y%m%d")
        except ValueError:
            pass
    return text.replace("/", "").replace("-", "")


def _day_range(start: str, end: str):
    s = datetime.strptime(start, "%Y%m%d").date()
    e = datetime.strptime(end, "%Y%m%d").date()
    d = s
    while d <= e:
        yield d.strftime("%Y%m%d")
        d += timedelta(days=1)


def _deadline_dt(day: str, hhmm: str | None):
    if not hhmm:
        return None
    try:
        value = datetime.strptime(f"{day} {hhmm}", "%Y%m%d %H:%M")
        return value.replace(tzinfo=base.JST)
    except ValueError:
        return None


def _active_sections(book, today: str) -> dict[str, dict]:
    ws = book.worksheet(ACTIVE_SHEET)
    names = []
    for row in ws.get("C2:C50"):
        name = str(row[0]).strip() if row else ""
        if name and name not in names and name in VENUE_CODES:
            names.append(name)

    out = {}
    for name in names:
        try:
            venue_ws = book.worksheet(name)
            values = venue_ws.get("C3:D3")
            row = values[0] if values else []
            start = _norm_day(row[0] if len(row) > 0 else "")
            end = _norm_day(row[1] if len(row) > 1 else "")
        except Exception:
            continue
        if not (re.fullmatch(r"20\d{6}", start) and re.fullmatch(r"20\d{6}", end)):
            continue
        capped_end = min(end, today)
        if start > capped_end:
            continue
        out[name] = {"jcd": VENUE_CODES[name], "start": start, "end": capped_end}
    return out


def _fl_counts(raw: str) -> dict[int, tuple[int, int]]:
    out = {}
    for body in re.findall(r"<tbody\b[^>]*>(.*?)</tbody>", raw, re.I | re.S):
        lane_match = re.search(r"is-boatColor([1-6])", body)
        if not lane_match:
            continue
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", body, re.I | re.S)
        if len(cells) < 4:
            continue
        text = base.textify(cells[3])
        match = re.search(r"F\s*(\d+)\s*\nL\s*(\d+)\s*\n", text)
        if match:
            out[int(lane_match.group(1))] = (int(match.group(1)), int(match.group(2)))
    return out


def _fetch_lineup(day: str, venue: str, jcd: str, rno: int, deadline: str) -> list[list]:
    try:
        raw = base.fetch(base.official_url("racelist", day, jcd, rno))
        boats = base.parse_racelist_boats(day, jcd, rno)
    except Exception:
        return []
    if len(boats) != 6:
        return []
    fl = _fl_counts(raw)
    rows = []
    for boat in boats:
        lane = int(boat.get("lane") or 0)
        f_count, l_count = fl.get(lane, (1 if boat.get("flying") else 0, 0))
        local_win = boat.get("local_win_rate")
        material = []
        if f_count:
            material.append(f"F{f_count}持ち")
        if l_count:
            material.append(f"L{l_count}")
        if local_win is not None:
            material.append(f"当地勝率{float(local_win):.2f}")
        rows.append([
            day, venue, rno, deadline, lane,
            str(boat.get("racer_id") or ""), str(boat.get("current_class") or ""),
            " / ".join(material), f_count,
            local_win if local_win is not None else "",
            boat.get("win_rate") if boat.get("win_rate") is not None else "",
            boat.get("avg_st") if boat.get("avg_st") is not None else "",
            l_count,
            boat.get("top2_rate") if boat.get("top2_rate") is not None else "",
            boat.get("top3_rate") if boat.get("top3_rate") is not None else "",
        ])
    return rows


def _fetch_result(day: str, venue: str, jcd: str, rno: int) -> list[list]:
    try:
        raw = base.fetch(base.official_url("raceresult", day, jcd, rno))
        result = race_context.parse_result(raw, day, jcd, rno)
    except Exception:
        return []
    rows = []
    for item in sorted(result.get("finish") or [], key=lambda x: int(x.get("lane") or 9)):
        st = item.get("st")
        rows.append([
            day, venue, rno, item.get("lane") or "", str(item.get("racer_id") or ""),
            str(item.get("name") or ""), item.get("finish") if item.get("finish") is not None else item.get("status") or "",
            item.get("course") or "", st if st is not None else "", result.get("method") or "",
            result.get("trifecta") or "", result.get("payout_per_100") or "", "", "", 1,
        ])
    return rows if len(rows) == 6 else []


def _valid_today_row(row: list[str], today: str, active: set[str]) -> bool:
    return len(row) >= 15 and _norm_day(row[0]) == today and str(row[1]).strip() in active and str(row[4]).strip() in set("123456")


def _valid_result_row(row: list[str], sections: dict[str, dict]) -> bool:
    if len(row) < 15:
        return False
    day = _norm_day(row[0])
    venue = str(row[1]).strip()
    sec = sections.get(venue)
    return bool(sec and re.fullmatch(r"20\d{6}", day) and sec["start"] <= day <= sec["end"] and str(row[3]).strip() in set("123456"))


def _race_complete(rows_by_key: dict, day: str, venue: str, rno: int) -> bool:
    lanes = {
        int(key[3]) for key in rows_by_key
        if key[0] == day and key[1] == venue and int(key[2]) == int(rno)
    }
    return lanes == set(range(1, 7))


def _write_full(ws, header: list[str], rows: list[list]) -> None:
    ws.clear()
    payload = [header] + rows
    needed = len(payload) + 20
    if needed > ws.row_count:
        ws.add_rows(needed - ws.row_count)
    ws.update(payload, "A1", raw=True)


def main() -> int:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON secret is required")
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    book = gspread.authorize(creds).open_by_key(SPREADSHEET_ID)

    now = datetime.now(base.JST)
    today = now.strftime("%Y%m%d")
    sections = _active_sections(book, today)
    active_names = set(sections)
    if not sections:
        print(json.dumps({"ok": True, "active_venues": 0, "message": "no active sections"}, ensure_ascii=False))
        return 0

    today_ws = book.worksheet(TODAY_SHEET)
    old_today = today_ws.get_all_values()
    today_map = {}
    for row in old_today[1:] if old_today else []:
        if _valid_today_row(row, today, active_names):
            key = (today, str(row[1]).strip(), int(float(row[2])), int(float(row[4])))
            today_map[key] = row[:15]

    lineup_tasks = []
    deadlines_by_venue = {}
    for venue, sec in sections.items():
        try:
            deadlines = base.deadlines(today, sec["jcd"])
        except Exception:
            deadlines = []
        deadlines_by_venue[venue] = deadlines
        for rno in range(1, 13):
            deadline = deadlines[rno - 1] if len(deadlines) >= rno else ""
            existing = sum(1 for lane in range(1, 7) if (today, venue, rno, lane) in today_map)
            ddt = _deadline_dt(today, deadline)
            near = bool(ddt and -timedelta(minutes=10) <= ddt - now <= timedelta(minutes=90))
            if existing < 6 or near:
                lineup_tasks.append((today, venue, sec["jcd"], rno, deadline))

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch_lineup, *task): task for task in lineup_tasks}
        for future in as_completed(futures):
            for row in future.result():
                today_map[(today, row[1], int(row[2]), int(row[4]))] = row

    today_rows = [today_map[k] for k in sorted(today_map, key=lambda x: (int(VENUE_CODES[x[1]]), x[2], x[3]))]
    _write_full(today_ws, TODAY_HEADER, today_rows)

    result_ws = book.worksheet(RESULT_SHEET)
    old_results = result_ws.get_all_values()
    result_map = {}
    for row in old_results[1:] if old_results else []:
        if _valid_result_row(row, sections):
            key = (_norm_day(row[0]), str(row[1]).strip(), int(float(row[2])), int(float(row[3])))
            result_map[key] = row[:15]

    result_tasks = []
    for venue, sec in sections.items():
        deadlines = deadlines_by_venue.get(venue) or []
        for day in _day_range(sec["start"], sec["end"]):
            for rno in range(1, 13):
                if _race_complete(result_map, day, venue, rno):
                    continue
                if day == today:
                    deadline = deadlines[rno - 1] if len(deadlines) >= rno else ""
                    ddt = _deadline_dt(today, deadline)
                    if not ddt or now < ddt + timedelta(seconds=45):
                        continue
                result_tasks.append((day, venue, sec["jcd"], rno))

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(_fetch_result, *task): task for task in result_tasks}
        for future in as_completed(futures):
            for row in future.result():
                result_map[(_norm_day(row[0]), row[1], int(row[2]), int(row[3]))] = row

    result_rows = [result_map[k] for k in sorted(result_map, key=lambda x: (x[0], int(VENUE_CODES[x[1]]), x[2], x[3]))]
    _write_full(result_ws, RESULT_HEADER, result_rows)

    print(json.dumps({
        "ok": True,
        "active_venues": sorted(active_names),
        "today_rows": len(today_rows),
        "today_races_fetched": len(lineup_tasks),
        "section_result_rows": len(result_rows),
        "result_races_fetched": len(result_tasks),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
