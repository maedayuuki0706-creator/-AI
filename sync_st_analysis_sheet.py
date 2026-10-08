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
ANALYSIS_SHEET = os.getenv("ST_ANALYSIS_SHEET", "ST展開分析")
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

ANALYSIS_HEADER = [
    "日付", "場", "R", "締切", "枠", "登録番号", "級別", "F数", "L数", "公式平均ST", "元展開材料",
    "節間平均ST", "直近3走平均", "節間走数", "最新ST", "最新展示ST", "節間ST推移",
    "予測ST(仮)", "ST順位", "内隣予測ST", "内隣差(+＝自分早い)", "外隣予測ST", "外隣差(+＝自分早い)",
    "ST信頼度", "スリット判定", "展開フラグ", "AI入力キー", "AI入力要約",
]


def _number(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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



def _build_series_stats(result_map: dict) -> dict:
    grouped = {}
    for key, row in result_map.items():
        if len(row) < 9:
            continue
        venue = str(row[1]).strip()
        reg = str(row[4]).strip()
        st = _number(row[8])
        if not venue or not reg or st is None:
            continue
        grouped.setdefault((venue, reg), []).append((key[0], int(key[2]), st))
    out = {}
    for key, values in grouped.items():
        values.sort(key=lambda x: (x[0], x[1]))
        sts = [x[2] for x in values]
        out[key] = {
            "avg": sum(sts) / len(sts),
            "last3": sum(sts[-3:]) / min(3, len(sts)),
            "n": len(sts),
            "latest": sts[-1],
            "sequence": " → ".join(f"{x:.2f}" for x in sts),
        }
    return out


def _predicted_st(official, stats):
    sec = stats.get("avg") if stats else None
    last3 = stats.get("last3") if stats else None
    n = int(stats.get("n") or 0) if stats else 0
    if official is None and sec is None:
        return None
    if official is None:
        return round(sec, 3)
    if sec is None:
        return round(official, 3)
    recent = last3 if last3 is not None else sec
    if n <= 1:
        value = 0.75 * official + 0.25 * sec
    elif n <= 3:
        value = 0.55 * official + 0.25 * sec + 0.20 * recent
    else:
        value = 0.40 * official + 0.35 * sec + 0.25 * recent
    return round(value, 3)


def _confidence(n: int) -> str:
    if n >= 4:
        return "高"
    if n >= 2:
        return "中"
    if n == 1:
        return "低"
    return "基準のみ"


def _slit_judgment(lane: int, pred, inner_gap, outer_gap) -> str:
    if pred is None:
        return "判定不可"
    if lane == 1:
        if outer_gap is not None and outer_gap <= -0.05:
            return "外圧強"
        if outer_gap is not None and outer_gap >= 0.03:
            return "イン先行"
        return "互角"
    if lane == 6:
        if inner_gap is not None and inner_gap >= 0.05:
            return "内へ強く先行"
        if inner_gap is not None and inner_gap <= -0.05:
            return "内に遅れ"
        return "互角"
    if inner_gap is not None and outer_gap is not None:
        if inner_gap >= 0.04 and outer_gap >= -0.01:
            return "攻め先行"
        if inner_gap <= -0.03 and outer_gap <= -0.03:
            return "凹み警戒"
    if inner_gap is not None and inner_gap >= 0.03:
        return "内へ圧"
    if outer_gap is not None and outer_gap <= -0.03:
        return "外圧注意"
    return "互角"


def _development_flag(lane: int, f_count: int, pred, inner_gap, outer_gap) -> str:
    flags = []
    if f_count >= 1:
        flags.append("F持ち")
    if pred is None:
        flags.append("ST不足")
        return "｜".join(flags)
    if lane == 1:
        if outer_gap is not None and outer_gap <= -0.04:
            flags.append("イン受け圧")
    elif lane == 6:
        if inner_gap is not None and inner_gap >= 0.05:
            flags.append("6のぞき注意")
        elif inner_gap is not None and inner_gap <= -0.05:
            flags.append("6遅れ")
    else:
        if inner_gap is not None and inner_gap >= 0.05:
            flags.append("攻め起点候補")
        elif inner_gap is not None and outer_gap is not None and inner_gap <= -0.03 and outer_gap <= -0.03:
            flags.append("凹み候補")
        elif outer_gap is not None and outer_gap <= -0.05:
            flags.append("外から攻められ")
    return "｜".join(flags)


def _build_analysis_rows(today_rows: list[list], result_map: dict) -> list[list]:
    stats_map = _build_series_stats(result_map)
    base_rows = []
    by_race = {}
    for row in today_rows:
        if len(row) < 15:
            continue
        day, venue = str(row[0]), str(row[1])
        rno, lane = int(row[2]), int(row[4])
        reg = str(row[5])
        official = _number(row[11])
        stats = stats_map.get((venue, reg), {})
        pred = _predicted_st(official, stats)
        item = {
            "day": day, "venue": venue, "rno": rno, "deadline": row[3],
            "lane": lane, "reg": reg, "class": row[6], "f": int(_number(row[8]) or 0),
            "l": int(_number(row[12]) or 0), "official": official, "material": row[7],
            "stats": stats, "pred": pred,
        }
        base_rows.append(item)
        by_race.setdefault((day, venue, rno), {})[lane] = item

    output = []
    for item in base_rows:
        race = by_race[(item["day"], item["venue"], item["rno"])]
        lane, pred = item["lane"], item["pred"]
        valid_preds = [x["pred"] for x in race.values() if x["pred"] is not None]
        rank = 1 + sum(1 for value in valid_preds if pred is not None and value < pred) if pred is not None else ""
        inner = race.get(lane - 1, {}).get("pred") if lane > 1 else None
        outer = race.get(lane + 1, {}).get("pred") if lane < 6 else None
        inner_gap = round(inner - pred, 3) if inner is not None and pred is not None else None
        outer_gap = round(outer - pred, 3) if outer is not None and pred is not None else None
        stats = item["stats"]
        n = int(stats.get("n") or 0)
        confidence = _confidence(n)
        slit = _slit_judgment(lane, pred, inner_gap, outer_gap)
        flag = _development_flag(lane, item["f"], pred, inner_gap, outer_gap)
        key = f'{item["day"]}|{item["venue"]}|{item["rno"]:02d}|{lane}'
        def st_text(value, digits=2):
            return "-" if value is None else f"{value:.{digits}f}"
        summary = (
            f'{lane}号艇 ST[公式:{st_text(item["official"])}/節間:{st_text(stats.get("avg"))}/'
            f'予測:{st_text(pred,3)}] 隣差[内:{st_text(inner_gap,3)}/外:{st_text(outer_gap,3)}] '
            f'{slit} 信頼:{confidence}'
        )
        output.append([
            item["day"], item["venue"], item["rno"], item["deadline"], lane, item["reg"], item["class"],
            item["f"], item["l"], item["official"] if item["official"] is not None else "", item["material"],
            round(stats["avg"], 3) if stats.get("avg") is not None else "",
            round(stats["last3"], 3) if stats.get("last3") is not None else "",
            n if n else "", stats.get("latest") if stats.get("latest") is not None else "",
            "", stats.get("sequence") or "", pred if pred is not None else "", rank,
            inner if inner is not None else "", inner_gap if inner_gap is not None else "",
            outer if outer is not None else "", outer_gap if outer_gap is not None else "",
            confidence, slit, flag, key, summary,
        ])
    output.sort(key=lambda r: (int(VENUE_CODES.get(r[1], "99")), int(r[2]), int(r[4])))
    return output


def _write_analysis(book, rows: list[list]) -> None:
    ws = book.worksheet(ANALYSIS_SHEET)
    ws.batch_clear(["A2:AB2000"])
    if rows:
        ws.update(rows, f"A2:AB{len(rows)+1}", raw=True)


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

    # First backfill can contain hundreds of historical races. Cap each run so
    # the 15-minute workflow stays well inside its timeout, prioritizing the
    # newest/current races; later scheduled runs fill the remainder.
    result_tasks.sort(key=lambda x: (x[0], x[3], x[2]), reverse=True)
    result_tasks = result_tasks[:int(os.getenv("ST_RESULT_FETCH_CAP", "48"))]

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(_fetch_result, *task): task for task in result_tasks}
        for future in as_completed(futures):
            try:
                fetched_rows = future.result()
            except Exception:
                fetched_rows = []
            for row in fetched_rows:
                result_map[(_norm_day(row[0]), row[1], int(row[2]), int(row[3]))] = row

    result_rows = [result_map[k] for k in sorted(result_map, key=lambda x: (x[0], int(VENUE_CODES[x[1]]), x[2], x[3]))]
    _write_full(result_ws, RESULT_HEADER, result_rows)

    analysis_rows = _build_analysis_rows(today_rows, result_map)
    _write_analysis(book, analysis_rows)

    print(json.dumps({
        "ok": True,
        "active_venues": sorted(active_names),
        "today_rows": len(today_rows),
        "today_races_fetched": len(lineup_tasks),
        "section_result_rows": len(result_rows),
        "result_races_fetched": len(result_tasks),
        "analysis_rows": len(analysis_rows),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
