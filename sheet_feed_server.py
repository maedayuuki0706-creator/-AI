"""Isolated BOAT RACE -> Google Sheets feed service.

This service is intentionally standalone:
- it does NOT import or call the prediction engine
- it does NOT touch Discord/X delivery
- it does NOT write production data
- it only exposes public CSV/JSON endpoints for Google Sheets IMPORTDATA

Endpoints:
  /health
  /venues.csv?date=YYYYMMDD
  /race.csv?date=YYYYMMDD&jcd=20&rno=8
  /venue.csv?date=YYYYMMDD&jcd=20
  /today.csv?date=YYYYMMDD
  /today.json?date=YYYYMMDD
  /result.csv?date=YYYYMMDD&jcd=20&rno=8
  /venue_results.csv?date=YYYYMMDD&jcd=20
  /section_results.csv?jcd=20&start=YYYYMMDD&end=YYYYMMDD
  /section_roster.csv?jcd=20&date=YYYYMMDD
  /today_results.csv?date=YYYYMMDD
  /today_results.json?date=YYYYMMDD
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
import re
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
BASE = "https://www.boatrace.jp/owpc/pc/race"
UA = "Boat-Sheet-Feed/1.0 (+isolated-sheet-updater)"
VENUES = {
    "01":"桐生","02":"戸田","03":"江戸川","04":"平和島","05":"多摩川","06":"浜名湖",
    "07":"蒲郡","08":"常滑","09":"津","10":"三国","11":"びわこ","12":"住之江",
    "13":"尼崎","14":"鳴門","15":"丸亀","16":"児島","17":"宮島","18":"徳山",
    "19":"下関","20":"若松","21":"芦屋","22":"福岡","23":"唐津","24":"大村",
}
VENUE_CODES = {v: k for k, v in VENUES.items()}
CSV_HEADER = [
    "日付","場","R","締切","枠","登録番号","級別","展開材料",
    "F数","当地勝率","全国勝率","平均ST","L数","全国2連率","全国3連率",
]
RESULT_HEADER = [
    "日付","場","R","枠","登録番号","選手名","着順","進入","実ST","決まり手",
    "3連単","3連単払戻","2連単","2連単払戻","確定",
]
ROSTER_HEADER = ["登録番号","選手名","級別","モーターNo.","モーター2連率","モーター3連率"]
BASIC_ROSTER_HEADER = ["登録番号","選手名","級別"]
RACE_ROSTER_HEADER = ["登録番号","選手名","級別","モーターNo.","モーター2連率","モーター3連率"]

_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, object]] = {}
CACHE_TTL = int(os.getenv("FEED_CACHE_SECONDS", "300"))


def _cached(key: str, producer):
    now = time.time()
    with _cache_lock:
        item = _cache.get(key)
        if item and now - item[0] < CACHE_TTL:
            return item[1]
    value = producer()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept-Language": "ja-JP,ja;q=0.9"},
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", errors="replace")


def textify(raw: str) -> str:
    raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"</(?:td|th|tr|li|p|div|h[1-6])>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw).replace("\u3000", " ")
    raw = unicodedata.normalize("NFKC", raw)
    raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
    raw = re.sub(r"\n+", "\n", raw)
    return "\n".join(line.strip() for line in raw.splitlines() if line.strip())


def official_url(kind: str, day: str, jcd: str | None = None, rno: int | None = None) -> str:
    q = {"hd": day}
    if jcd is not None:
        q["jcd"] = jcd
    if rno is not None:
        q["rno"] = str(rno)
    return f"{BASE}/{kind}?{urllib.parse.urlencode(q)}"


def normalize_day(value: str | None) -> str:
    if value and re.fullmatch(r"20\d{6}", value):
        return value
    return datetime.now(JST).strftime("%Y%m%d")


def discover_venues(day: str) -> list[str]:
    def build():
        raw = fetch(official_url("index", day))
        found = re.findall(r"(?:\?|&amp;|&)jcd=(\d{2})", raw)
        return sorted({x for x in found if x in VENUES})
    return _cached(f"venues:{day}", build)


def deadlines(day: str, jcd: str) -> list[str]:
    def build():
        text = textify(fetch(official_url("racelist", day, jcd, 1)))
        pos = text.find("締切予定時刻")
        if pos < 0:
            return []
        chunk = text[pos:pos + 1000]
        times = re.findall(r"(?:[01]?\d|2[0-3]):[0-5]\d", chunk)
        out: list[str] = []
        for t in times:
            h, m = map(int, t.split(":"))
            norm = f"{h:02d}:{m:02d}"
            if norm not in out:
                out.append(norm)
            if len(out) == 12:
                break
        return out
    return _cached(f"deadlines:{day}:{jcd}", build)



def debug_race_structure(day: str, jcd: str, rno: int) -> dict:
    raw = fetch(official_url("racelist", day, jcd, rno))
    bodies = []
    for idx, body in enumerate(re.findall(r"<tbody\\b[^>]*>(.*?)</tbody>", raw, re.I | re.S)):
        cells = re.findall(r"<td\\b[^>]*>(.*?)</td>", body, re.I | re.S)
        txt = textify(body)
        lane_match = re.search(r"is-boatColor([1-6])", body)
        reg = re.search(r"(\\d{4})\\s*/\\s*(A1|A2|B1|B2)\\b", txt)
        if lane_match or reg:
            bodies.append({
                "index": idx,
                "lane": int(lane_match.group(1)) if lane_match else None,
                "registration": reg.group(1) if reg else None,
                "class": reg.group(2) if reg else None,
                "cell_count": len(cells),
                "cells": [textify(x)[:500] for x in cells],
                "text": txt[:1500],
            })
    return {"url": official_url("racelist", day, jcd, rno), "tbody_count": len(bodies), "bodies": bodies}

def parse_racelist_boats(day: str, jcd: str, rno: int) -> list[dict]:
    def build():
        raw = fetch(official_url("racelist", day, jcd, rno))
        boats = []
        for body in re.findall(r"<tbody\b[^>]*>(.*?)</tbody>", raw, re.I | re.S):
            lane_match = re.search(r"is-boatColor([1-6])", body)
            text = textify(body)
            registration = re.search(r"(\d{4})\s*/\s*(A1|A2|B1|B2)\b", text)
            if not lane_match or not registration:
                continue
            cells = re.findall(r"<td\b[^>]*>(.*?)</td>", body, re.I | re.S)
            if len(cells) < 8:
                continue
            start_text = textify(cells[3])
            fl = re.search(r"F\s*(\d+)\s*\nL\s*(\d+)\s*\n", start_text)
            if not fl:
                continue
            vals = [start_text[fl.end():].strip()]
            valid = True
            for cell in cells[4:8]:
                values = textify(cell).splitlines()
                if len(values) != 3:
                    valid = False
                    break
                vals.extend(values)
            if not valid:
                continue
            if any(not re.fullmatch(r"(?:\d+(?:\.\d+)?|[-－―—])", value) for value in vals):
                continue
            nums = [float(value) if re.fullmatch(r"\d+(?:\.\d+)?", value) else None for value in vals]
            lane = int(lane_match[1])
            boats.append({
                "lane": lane,
                "racer_id": registration[1],
                "current_class": registration[2],
                "name": re.sub(r"\s+", "", text[registration.end():].strip().split("\n")[0]),
                "avg_st": nums[0],
                "f_count": int(fl[1]),
                "l_count": int(fl[2]),
                "win_rate": nums[1],
                "top2_rate": nums[2],
                "top3_rate": nums[3],
                "local_win_rate": nums[4] if any(x is not None for x in nums[4:7]) else None,
                "local_top2_rate": nums[5] if any(x is not None for x in nums[4:7]) else None,
                "local_top3_rate": nums[6] if any(x is not None for x in nums[4:7]) else None,
                "motor_number": int(nums[7]) if nums[7] is not None else None,
                "motor_top2_rate": nums[8],
                "motor_top3_rate": nums[9],
            })
        if len(boats) == 6 and {b["lane"] for b in boats} == set(range(1, 7)):
            return sorted(boats, key=lambda x: x["lane"])
        return []
    return _cached(f"race:{day}:{jcd}:{rno}", build)


def race_rows(day: str, jcd: str, rno: int, deadline_override: str | None = None) -> list[list]:
    boats = parse_racelist_boats(day, jcd, rno)
    if not boats:
        return []
    if deadline_override is None:
        dls = deadlines(day, jcd)
        deadline = dls[rno - 1] if len(dls) >= rno else ""
    else:
        deadline = deadline_override
    rows = []
    for b in boats:
        materials = []
        if b["f_count"]:
            materials.append(f"F{b['f_count']}持ち")
        if b["l_count"]:
            materials.append(f"L{b['l_count']}持ち")
        if b["local_win_rate"] is not None:
            local_mark = "◎" if b["local_win_rate"] >= 6.5 else ("△" if b["local_win_rate"] < 4 else "")
            materials.append(f"当地勝率{b['local_win_rate']:.2f}{local_mark}")
        rows.append([
            day,
            VENUES[jcd],
            rno,
            deadline,
            b["lane"],
            b["racer_id"],
            b["current_class"],
            " / ".join(materials),
            b["f_count"],
            "" if b["local_win_rate"] is None else b["local_win_rate"],
            "" if b["win_rate"] is None else b["win_rate"],
            "" if b["avg_st"] is None else b["avg_st"],
            b["l_count"],
            "" if b["top2_rate"] is None else b["top2_rate"],
            "" if b["top3_rate"] is None else b["top3_rate"],
        ])
    return rows



def _start_value(value: str):
    value = textify(value).replace(" ", "")
    m = re.search(r"F(?:0)?\.(\d+)", value)
    if m:
        return -float("0." + m.group(1))
    m = re.search(r"(?<![A-Za-z0-9])(?:0)?\.(\d+)", value)
    if m:
        return float("0." + m.group(1))
    return ""


def parse_result(day: str, jcd: str, rno: int) -> dict:
    """Parse an official result page without importing prediction/delivery code."""
    def build():
        raw = fetch(official_url("raceresult", day, jcd, rno))
        text = textify(raw)
        finish_by_lane: dict[int, int] = {}
        racer_by_lane: dict[int, str] = {}
        name_by_lane: dict[int, str] = {}

        # The first result table has one tbody/row per finisher. Require an
        # explicit finish number in the first cell to avoid matching other tables.
        for body in re.findall(r"<tbody\b[^>]*>(.*?)</tbody>", raw, re.I | re.S):
            cells = re.findall(r"<td\b[^>]*>(.*?)</td>", body, re.I | re.S)
            if len(cells) < 3:
                continue
            first = textify(cells[0])
            if not re.fullmatch(r"[1-6]", first):
                continue
            lane_match = re.search(r"is-boatColor([1-6])", body)
            body_text = textify(body)
            reg = re.search(r"\b(\d{4})\b", body_text)
            if not lane_match or not reg:
                continue
            lane = int(lane_match[1])
            finish_by_lane[lane] = int(first)
            racer_by_lane[lane] = reg[1]
            # Best-effort name extraction; registration number is the canonical key.
            after_reg = body_text[reg.end():].strip().split("\n")
            if after_reg:
                candidate = re.sub(r"\s+", "", after_reg[0])
                if candidate and not re.fullmatch(r"(?:A1|A2|B1|B2|\d+(?:\.\d+)?)", candidate):
                    name_by_lane[lane] = candidate

        if len(finish_by_lane) < 3:
            return {}

        # Official start diagram appears in course order; number is boat/lane.
        start_by_lane: dict[int, dict] = {}
        starts = re.findall(
            r"table1_boatImage1Number[^>]*>\s*([1-6])\s*</span>.*?"
            r"table1_boatImage1Time[^>]*>(.*?)</span>",
            raw, re.I | re.S
        )
        if starts:
            for course, (lane_s, value) in enumerate(starts[:6], 1):
                lane = int(lane_s)
                start_by_lane[lane] = {"course": course, "st": _start_value(value)}

        methods = re.findall(r"決まり手\s*\n([^\n]+)", text)
        allowed = {"逃げ","差し","まくり","まくり差し","抜き","恵まれ"}
        method = next((m.strip() for m in methods if m.strip() in allowed), "")

        tri = ""
        tri_pay = ""
        m = re.search(
            r"3連単\s*\n\s*([1-6]\s*-\s*[1-6]\s*-\s*[1-6])\s*\n\s*[¥￥]?\s*([\d,]+)",
            text
        )
        if m:
            tri = re.sub(r"\s+", "", m[1])
            tri_pay = int(m[2].replace(",", ""))

        duo = ""
        duo_pay = ""
        m = re.search(
            r"2連単\s*\n\s*([1-6]\s*-\s*[1-6])\s*\n\s*[¥￥]?\s*([\d,]+)",
            text
        )
        if m:
            duo = re.sub(r"\s+", "", m[1])
            duo_pay = int(m[2].replace(",", ""))

        return {
            "finish_by_lane": finish_by_lane,
            "racer_by_lane": racer_by_lane,
            "name_by_lane": name_by_lane,
            "start_by_lane": start_by_lane,
            "method": method,
            "trifecta": tri,
            "trifecta_payout": tri_pay,
            "exacta": duo,
            "exacta_payout": duo_pay,
            "final": len(finish_by_lane) >= 3,
        }
    return _cached(f"result:{day}:{jcd}:{rno}", build)


def result_rows(day: str, jcd: str, rno: int) -> list[list]:
    result = parse_result(day, jcd, rno)
    if not result or not result.get("final"):
        return []
    rows = []
    for lane in sorted(result["finish_by_lane"]):
        start = result["start_by_lane"].get(lane, {})
        finish = result["finish_by_lane"][lane]
        rows.append([
            day,
            VENUES[jcd],
            rno,
            lane,
            result["racer_by_lane"].get(lane, ""),
            result["name_by_lane"].get(lane, ""),
            finish,
            start.get("course", lane),
            start.get("st", ""),
            result["method"] if finish == 1 else "",
            ("\u200b" + result.get("trifecta", "")) if result.get("trifecta") else "",
            result.get("trifecta_payout", ""),
            ("\u200b" + result.get("exacta", "")) if result.get("exacta") else "",
            result.get("exacta_payout", ""),
            "確定",
        ])
    return rows


def venue_result_rows(day: str, jcd: str) -> list[list]:
    rows: list[list] = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = [ex.submit(result_rows, day, jcd, rno) for rno in range(1, 13)]
        for future in as_completed(futures):
            try:
                rows.extend(future.result())
            except Exception:
                continue
    rows.sort(key=lambda r: (int(r[2]), int(r[3])))
    return rows


def assen_roster_rows(day: str, jcd: str) -> list[list]:
    """Fast venue roster from the official assignment page (single HTTP request)."""
    if jcd not in VENUES:
        return []
    def build():
        url = official_url("assen", day, jcd)
        raw = fetch(url)
        text = textify(raw)
        rows = []
        seen = set()
        pat = re.compile(r"(?:^|\n)(\d{4})\n([^\n]+)\n級別\s*[:：]?\s*(A1|A2|B1|B2)\b")
        for m in pat.finditer(text):
            reg = m.group(1)
            if reg in seen:
                continue
            seen.add(reg)
            name = re.sub(r"\s+", "", m.group(2)).strip()
            rows.append([reg, name, m.group(3)])
        return rows
    return _cached(f"assen-roster:{day}:{jcd}", build)


def race_roster_rows(day: str, jcd: str, rno: int) -> list[list]:
    """Six-boat roster for one race; intentionally small/fast for Sheets."""
    if jcd not in VENUES or not 1 <= int(rno) <= 12:
        return []
    rows = []
    for b in parse_racelist_boats(day, jcd, int(rno)):
        rows.append([
            str(b.get("racer_id") or ""),
            b.get("name",""),
            b.get("current_class",""),
            b.get("motor_number","") if b.get("motor_number") is not None else "",
            b.get("motor_top2_rate","") if b.get("motor_top2_rate") is not None else "",
            b.get("motor_top3_rate","") if b.get("motor_top3_rate") is not None else "",
        ])
    return rows


def section_roster_rows(day: str, jcd: str) -> list[list]:
    """Return a unique race-card roster for a venue/date, keyed by registration."""
    if jcd not in VENUES:
        return []
    found: dict[str, list] = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = [ex.submit(parse_racelist_boats, day, jcd, rno) for rno in range(1, 13)]
        for future in as_completed(futures):
            try:
                boats = future.result()
            except Exception:
                continue
            for b in boats:
                reg = str(b.get("racer_id") or "")
                if not reg:
                    continue
                row = [
                    reg,
                    b.get("name",""),
                    b.get("current_class",""),
                    b.get("motor_number","") if b.get("motor_number") is not None else "",
                    b.get("motor_top2_rate","") if b.get("motor_top2_rate") is not None else "",
                    b.get("motor_top3_rate","") if b.get("motor_top3_rate") is not None else "",
                ]
                found[reg] = row
    return sorted(found.values(), key=lambda r: int(r[0]) if str(r[0]).isdigit() else 99999)


def section_result_rows(start_day: str, end_day: str, jcd: str) -> list[list]:
    """Return all finalized result rows for one venue across a meeting date range."""
    from datetime import date, timedelta

    if jcd not in VENUES:
        return []
    try:
        start = datetime.strptime(start_day, "%Y%m%d").date()
        end = datetime.strptime(end_day, "%Y%m%d").date()
    except ValueError:
        return []
    today = datetime.now(JST).date()
    end = min(end, today)
    if end < start or (end - start).days > 10:
        return []

    days = []
    d = start
    while d <= end:
        days.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)

    rows: list[list] = []
    with ThreadPoolExecutor(max_workers=min(24, max(12, len(days) * 6))) as ex:
        futures = []
        for day in days:
            for rno in range(1, 13):
                futures.append(ex.submit(result_rows, day, jcd, rno))
        for future in as_completed(futures):
            try:
                rows.extend(future.result())
            except Exception:
                continue
    rows.sort(key=lambda r: (str(r[0]), int(r[2]), int(r[3])))
    return rows


def today_result_rows(day: str) -> list[list]:
    def build():
        venues = discover_venues(day)
        rows: list[list] = []
        work = []
        with ThreadPoolExecutor(max_workers=min(18, max(4, len(venues) * 2))) as ex:
            for jcd in venues:
                for rno in range(1, 13):
                    work.append(ex.submit(result_rows, day, jcd, rno))
            for future in as_completed(work):
                try:
                    rows.extend(future.result())
                except Exception:
                    continue
        order = {name: int(code) for code, name in VENUES.items()}
        rows.sort(key=lambda r: (order.get(r[1], 99), int(r[2]), int(r[3])))
        return rows
    return _cached(f"today-results:{day}", build)


def venue_rows(day: str, jcd: str) -> list[list]:
    rows: list[list] = []
    dls = deadlines(day, jcd)
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = []
        for rno in range(1, 13):
            deadline = dls[rno - 1] if len(dls) >= rno else ""
            futures.append(ex.submit(race_rows, day, jcd, rno, deadline))
        for future in as_completed(futures):
            try:
                rows.extend(future.result())
            except Exception:
                continue
    rows.sort(key=lambda r: (int(r[2]), int(r[4])))
    return rows


def today_rows(day: str) -> list[list]:
    def build():
        venues = discover_venues(day)
        rows: list[list] = []
        work = []
        with ThreadPoolExecutor(max_workers=min(18, max(4, len(venues) * 2))) as ex:
            for jcd in venues:
                for rno in range(1, 13):
                    work.append(ex.submit(race_rows, day, jcd, rno))
            for future in as_completed(work):
                try:
                    rows.extend(future.result())
                except Exception:
                    continue
        order = {name: int(code) for code, name in VENUES.items()}
        rows.sort(key=lambda r: (order.get(r[1], 99), int(r[2]), int(r[4])))
        return rows
    return _cached(f"today:{day}", build)


def to_csv(rows: list[list], include_header: bool = True, header: list[str] | None = None) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    if include_header:
        writer.writerow(header or CSV_HEADER)
    writer.writerows(rows)
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "BoatSheetFeed/1.0"

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        day = normalize_day((qs.get("date") or [None])[0])

        try:
            if parsed.path == "/health":
                payload = {
                    "ok": True,
                    "service": "boat-sheet-feed",
                    "mode": "isolated",
                    "prediction_delivery_touched": False,
                    "day_jst": day,
                }
                self._send(200, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")
                return

            if parsed.path == "/debug_race.json":
                jcd = (qs.get("jcd") or [""])[0]
                venue = (qs.get("venue") or [""])[0]
                if not jcd and venue:
                    jcd = VENUE_CODES.get(venue, "")
                try:
                    rno = int((qs.get("rno") or ["0"])[0])
                except ValueError:
                    rno = 0
                if jcd not in VENUES or not 1 <= rno <= 12:
                    self._send(400, b"bad request", "text/plain; charset=utf-8")
                    return
                payload = debug_race_structure(day, jcd, rno)
                self._send(200, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")
                return

            if parsed.path == "/venues.csv":
                rows = [[code, VENUES[code]] for code in discover_venues(day)]
                body = to_csv([["場コード", "場名"]] + rows, include_header=False)
                self._send(200, body, "text/csv; charset=utf-8")
                return

            if parsed.path == "/race.csv":
                jcd = (qs.get("jcd") or [""])[0]
                venue = (qs.get("venue") or [""])[0]
                if not jcd and venue:
                    jcd = VENUE_CODES.get(venue, "")
                try:
                    rno = int((qs.get("rno") or ["0"])[0])
                except ValueError:
                    rno = 0
                if jcd not in VENUES or not 1 <= rno <= 12:
                    self._send(400, b"bad request", "text/plain; charset=utf-8")
                    return
                self._send(200, to_csv(race_rows(day, jcd, rno)), "text/csv; charset=utf-8")
                return

            if parsed.path == "/result.csv":
                jcd = (qs.get("jcd") or [""])[0]
                venue = (qs.get("venue") or [""])[0]
                if not jcd and venue:
                    jcd = VENUE_CODES.get(venue, "")
                try:
                    rno = int((qs.get("rno") or ["0"])[0])
                except ValueError:
                    rno = 0
                if jcd not in VENUES or not 1 <= rno <= 12:
                    self._send(400, b"bad request", "text/plain; charset=utf-8")
                    return
                self._send(200, to_csv(result_rows(day, jcd, rno), header=RESULT_HEADER), "text/csv; charset=utf-8")
                return

            if parsed.path == "/venue_results.csv":
                jcd = (qs.get("jcd") or [""])[0]
                venue = (qs.get("venue") or [""])[0]
                if not jcd and venue:
                    jcd = VENUE_CODES.get(venue, "")
                if jcd not in VENUES:
                    self._send(400, b"bad request", "text/plain; charset=utf-8")
                    return
                self._send(200, to_csv(venue_result_rows(day, jcd), header=RESULT_HEADER), "text/csv; charset=utf-8")
                return

            if parsed.path == "/race_roster.csv":
                jcd = (qs.get("jcd") or [""])[0]
                venue = (qs.get("venue") or [""])[0]
                if not jcd and venue:
                    jcd = VENUE_CODES.get(venue, "")
                roster_day = (qs.get("date") or [""])[0]
                try:
                    rno = int((qs.get("rno") or ["0"])[0])
                except ValueError:
                    rno = 0
                if jcd not in VENUES or not re.fullmatch(r"20\d{6}", roster_day) or not 1 <= rno <= 12:
                    self._send(400, b"bad request", "text/plain; charset=utf-8")
                    return
                self._send(200, to_csv(race_roster_rows(roster_day, jcd, rno), header=RACE_ROSTER_HEADER), "text/csv; charset=utf-8")
                return

            if parsed.path == "/assen_roster.csv":
                jcd = (qs.get("jcd") or [""])[0]
                venue = (qs.get("venue") or [""])[0]
                if not jcd and venue:
                    jcd = VENUE_CODES.get(venue, "")
                roster_day = (qs.get("date") or [""])[0]
                if jcd not in VENUES or not re.fullmatch(r"20\d{6}", roster_day):
                    self._send(400, b"bad request", "text/plain; charset=utf-8")
                    return
                self._send(200, to_csv(assen_roster_rows(roster_day, jcd), header=BASIC_ROSTER_HEADER), "text/csv; charset=utf-8")
                return

            if parsed.path == "/section_roster.csv":
                jcd = (qs.get("jcd") or [""])[0]
                venue = (qs.get("venue") or [""])[0]
                if not jcd and venue:
                    jcd = VENUE_CODES.get(venue, "")
                roster_day = (qs.get("date") or [""])[0]
                if jcd not in VENUES or not re.fullmatch(r"20\d{6}", roster_day):
                    self._send(400, b"bad request", "text/plain; charset=utf-8")
                    return
                self._send(200, to_csv(section_roster_rows(roster_day, jcd), header=ROSTER_HEADER), "text/csv; charset=utf-8")
                return

            if parsed.path == "/section_results.csv":
                jcd = (qs.get("jcd") or [""])[0]
                venue = (qs.get("venue") or [""])[0]
                if not jcd and venue:
                    jcd = VENUE_CODES.get(venue, "")
                start = (qs.get("start") or [""])[0]
                end = (qs.get("end") or [""])[0]
                if jcd not in VENUES or not re.fullmatch(r"20\d{6}", start) or not re.fullmatch(r"20\d{6}", end):
                    self._send(400, b"bad request", "text/plain; charset=utf-8")
                    return
                self._send(200, to_csv(section_result_rows(start, end, jcd), header=RESULT_HEADER), "text/csv; charset=utf-8")
                return

            if parsed.path == "/today_results.csv":
                self._send(200, to_csv(today_result_rows(day), header=RESULT_HEADER), "text/csv; charset=utf-8")
                return

            if parsed.path == "/today_results.json":
                payload = [dict(zip(RESULT_HEADER, row)) for row in today_result_rows(day)]
                self._send(200, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")
                return

            if parsed.path == "/venue.csv":
                jcd = (qs.get("jcd") or [""])[0]
                venue = (qs.get("venue") or [""])[0]
                if not jcd and venue:
                    jcd = VENUE_CODES.get(venue, "")
                if jcd not in VENUES:
                    self._send(400, b"bad request", "text/plain; charset=utf-8")
                    return
                self._send(200, to_csv(venue_rows(day, jcd)), "text/csv; charset=utf-8")
                return

            if parsed.path == "/today.csv":
                self._send(200, to_csv(today_rows(day)), "text/csv; charset=utf-8")
                return

            if parsed.path == "/today.json":
                payload = [dict(zip(CSV_HEADER, row)) for row in today_rows(day)]
                self._send(200, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")
                return

            self._send(404, b"not found", "text/plain; charset=utf-8")
        except Exception as exc:
            payload = {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:300]}
            self._send(500, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")


def main():
    port = int(os.getenv("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"boat-sheet-feed listening on :{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
