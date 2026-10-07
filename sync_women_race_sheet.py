"""Auto-append women-only meeting results to the 女子戦 sheet.

Source: BOAT RACE official race pages. The job scans recent JST days,
detects women-only series by official meeting title, appends only settled
races, and skips existing day/venue/race keys.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
import re
import unicodedata
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

import direct_discord_notify as base
from race_context import parse_result

JST = ZoneInfo("Asia/Tokyo")
SID = os.getenv("BOAT_SHEET_ID", "1dbUPyfxjIRaT-G8F_LlGMX7Ld_ZB951UmF4HpW_PYJo")
SHEET = os.getenv("WOMEN_SHEET", "女子戦")
BACKFILL_DAYS = max(1, int(os.getenv("WOMEN_BACKFILL_DAYS", "3")))

KEYWORDS = (
    "ヴィーナスシリーズ",
    "オールレディース",
    "レディースチャンピオン",
    "レディースオールスター",
    "クイーンズクライマックス",
    "女子王座",
    "プリンセスカップ",
)

def norm(s: str) -> str:
    return unicodedata.normalize("NFKC", str(s or "")).replace("\u3000", " ").strip()

def extract_title(raw: str) -> str:
    patterns = [
        r'heading2_titleName[^>]*>(.*?)</[^>]+>',
        r'class=["\'][^"\']*(?:titleName|raceTitle|eventTitle)[^"\']*["\'][^>]*>(.*?)</[^>]+>',
    ]
    for pat in patterns:
        m = re.search(pat, raw, re.I | re.S)
        if m:
            title = norm(base.textify(m.group(1)))
            if title:
                return title
    lines = [norm(x) for x in base.textify(raw).splitlines()]
    hits = [x for x in lines if any(k in x for k in KEYWORDS)]
    if hits:
        hits.sort(key=lambda x: (len(x), x))
        return hits[0]
    return ""

def classify(title: str, grade: str | None) -> tuple[str, str] | None:
    t = norm(title)
    if "ヴィーナスシリーズ" in t:
        return "ヴィーナスシリーズ", grade or "一般"
    if "オールレディース" in t:
        return "オールレディース", grade or "G3"
    if not any(k in t for k in KEYWORDS[2:]):
        return None
    if grade == "G1":
        return "女子G1", "G1"
    if grade == "G2":
        return "女子G2", "G2"
    if grade == "G3":
        return "女子G3", "G3"
    return "女子戦", grade or "一般"

def day_label(raw: str) -> str:
    text = norm(base.textify(raw))
    m = re.search(r"(最終日|初日|[2-9]日目)", text)
    return m.group(1) if m else ""

def existing_keys(values: list[list[str]]) -> set[tuple[str, str, int]]:
    out = set()
    for row in values[4:]:
        if len(row) < 8:
            continue
        day = str(row[0] or "").replace("/", "").replace("-", "").strip()
        jcd = str(row[1] or "").strip().zfill(2)
        try:
            rno = int(float(row[7]))
        except Exception:
            continue
        if len(day) == 8 and jcd.isdigit():
            out.add((day, jcd, rno))
    return out

def row_for(day: str, jcd: str, venue: str, category: str, grade: str,
            title: str, section_day: str, result: dict) -> list:
    combo = str(result["trifecta"])
    lanes = [int(x) for x in combo.split("-")]
    payout = int(result["payout_per_100"])
    head = lanes[0]
    url = result["source_url"]
    return [
        f"{day[:4]}/{day[4:6]}/{day[6:]}",
        int(jcd),
        venue,
        category,
        grade,
        title,
        section_day,
        int(result["rno"]),
        lanes[0], lanes[1], lanes[2],
        combo,
        payout,
        "○" if head == 1 else "",
        "○" if head != 1 else "",
        "○" if head >= 4 else "",
        "○" if payout >= 10000 else "",
        "○" if payout >= 30000 else "",
        "○" if payout >= 100000 else "",
        "",
        url,
        "BOAT RACE公式自動取得",
        "",
    ]

def main() -> int:
    raw_secret = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw_secret:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON secret is required")
    creds = Credentials.from_service_account_info(
        json.loads(raw_secret),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    book = gspread.authorize(creds).open_by_key(SID)
    ws = book.worksheet(SHEET)
    values = ws.get_all_values()
    keys = existing_keys(values)

    now = datetime.now(JST).date()
    start = now - timedelta(days=BACKFILL_DAYS - 1)
    new_rows = []
    detected = []

    day = start
    while day <= now:
        ds = day.strftime("%Y%m%d")
        try:
            venues = base.discover_venues(ds)
        except Exception:
            venues = []
        for jcd in venues:
            venue = base.VENUES.get(jcd, jcd)
            try:
                raw = base.fetch(base.official_url("racelist", ds, jcd, 1))
            except Exception:
                continue
            title = extract_title(raw)
            grade = base.detect_event_grade(raw)
            kind = classify(title, grade)
            if not kind:
                continue
            category, out_grade = kind
            section_day = day_label(raw)
            detected.append(f"{ds}:{jcd}:{category}:{title}")
            for rno in range(1, 13):
                k = (ds, jcd, rno)
                if k in keys:
                    continue
                try:
                    result_raw = base.fetch(base.official_url("raceresult", ds, jcd, rno))
                    result = parse_result(result_raw, ds, jcd, rno)
                except Exception:
                    continue
                result["rno"] = rno
                new_rows.append(row_for(
                    ds, jcd, venue, category, out_grade, title, section_day, result
                ))
                keys.add(k)
        day += timedelta(days=1)

    if not new_rows:
        print(json.dumps({
            "detected_meetings": len(set(detected)),
            "rows_appended": 0,
        }, ensure_ascii=False))
        return 0

    last_nonempty = 4
    for idx, row in enumerate(values, start=1):
        if any(str(v or "").strip() for v in row[:23]):
            last_nonempty = idx
    start_row = last_nonempty + 1
    end_row = start_row + len(new_rows) - 1
    if end_row > ws.row_count:
        ws.add_rows(max(200, end_row - ws.row_count + 50))

    ws.update(new_rows, f"A{start_row}:W{end_row}", raw=True)

    # Match the existing result-table appearance without copying values.
    book.batch_update({
        "requests": [{
            "copyPaste": {
                "source": {
                    "sheetId": ws.id,
                    "startRowIndex": 435,
                    "endRowIndex": 436,
                    "startColumnIndex": 0,
                    "endColumnIndex": 23,
                },
                "destination": {
                    "sheetId": ws.id,
                    "startRowIndex": start_row - 1,
                    "endRowIndex": end_row,
                    "startColumnIndex": 0,
                    "endColumnIndex": 23,
                },
                "pasteType": "PASTE_FORMAT",
                "pasteOrientation": "NORMAL",
            }
        }]
    })

    print(json.dumps({
        "detected_meetings": len(set(detected)),
        "rows_appended": len(new_rows),
        "range": f"A{start_row}:W{end_row}",
    }, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
