"""Update all 24 venue tabs from confirmed official race results.

Reporting only: does not post to Discord/X, generate predictions, or edit
existing completed meetings. New meetings are inserted at row 3, above history.
"""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import json
import os
import re
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
import direct_discord_notify as official

JST = ZoneInfo("Asia/Tokyo")
VENUES = official.VENUES
ID = os.getenv("BOAT_SHEET_ID", "1dbUPyfxjIRaT-G8F_LlGMX7Ld_ZB951UmF4HpW_PYJo")
MAX_NEW_MEETINGS = max(0, min(3, int(os.getenv("VENUE_NEW_MEETINGS_CAP", "2"))))
DRY_RUN = os.getenv("VENUE_SYNC_DRY_RUN", "0") == "1"
MAX_RUNS = 6  # Existing native venue tab schema; do not alter columns/layout.
RUN_COLS = 6
CLASS_ORDER = {"A1": 0, "A2": 1, "B1": 2, "B2": 3}


def at(row, idx):
    return str(row[idx]).strip() if len(row) > idx and row[idx] is not None else ""


def day(value):
    text = re.sub(r"[^0-9]", "", str(value or ""))[:8]
    return text if re.fullmatch(r"20\d{6}", text) else ""


def section_window(today, raw):
    text = official.textify(raw)
    matches = []
    for word in ("初日", "最終日"):
        m = re.search(r"(\d{1,2})月(\d{1,2})日\s*" + word, text)
        if not m:
            return None
        this = datetime.strptime(today, "%Y%m%d").date()
        candidate = this.replace(month=int(m[1]), day=int(m[2]))
        if (candidate - this).days > 30:
            candidate = candidate.replace(year=candidate.year - 1)
        if (this - candidate).days > 330:
            candidate = candidate.replace(year=candidate.year + 1)
        matches.append(candidate.strftime("%Y%m%d"))
    start, end = matches
    if not (start <= today <= end and 1 <=
            (datetime.strptime(end, "%Y%m%d") - datetime.strptime(start, "%Y%m%d")).days <= 9):
        return None
    return start, end


def series_title(raw):
    for pat in (
        r'heading2_titleName[^>]*>(.*?)</[^>]+>',
        r"""class=["'][^"']*(?:titleName|raceTitle|eventTitle)[^"']*["'][^>]*>(.*?)</[^>]+>""",
    ):
        match = re.search(pat, raw, re.I | re.S)
        if match:
            value = official.textify(match[1]).strip()
            if 2 <= len(value) <= 120:
                return value
    text = official.textify(raw)
    # Standard BOAT RACE race heading: "本日のレース / <event> / 出走表".
    m = re.search(r"本日のレース\n([^\n]{2,120})\n出走表(?:\n|$)", text)
    if m:
        value = m.group(1).strip()
        if value not in {"本日のレース", "出走表"}:
            return value
    return ""


def series_grade(title):
    """Read a grade from the verified event title, NOT from the site's G1/G2 nav."""
    upper = re.sub(r"\\s+", "", title or "").upper()
    if re.search(r"(?<![A-Z])SG(?![A-Z])", upper):
        return "SG"
    if re.search(r"(?<![A-Z])(?:PG1|G1|GI)(?![A-Z])", upper):
        return "G1"
    if re.search(r"(?<![A-Z])(?:G2|GII)(?![A-Z])", upper):
        return "G2"
    if re.search(r"(?<![A-Z])(?:G3|GIII)(?![A-Z])", upper):
        return "G3"
    if "オールレディース" in title or "マスターズリーグ" in title:
        return "G3"
    return "一般"


def official_result_records(foot, raw):
    """Use vetted settled results only; ST RAW wins over exhibition-side log."""
    races = {}
    for row in foot[1:]:
        venue, start, dt, rid = at(row, 0), day(at(row, 1)), day(at(row, 2)), at(row, 4)
        rno, lane, st, finish, course = (at(row, i) for i in (9, 11, 16, 17, 36))
        if (venue not in VENUES.values() or not start or not dt or not rid.isdigit()
                or not rno.isdigit() or not lane.isdigit() or not course.isdigit()
                or not finish or not st):
            continue
        if not start <= dt:
            continue
        key = (venue, dt, int(rno), rid)
        races[key] = dict(start=start, day=dt, rno=int(rno), rid=rid,
                          lane=lane, course=course, st=st, finish=finish,
                          method=at(row, 42))
    for row in raw[1:]:
        dt, venue, rno, lane, rid = (at(row, i) for i in range(5))
        finish, course, st, method, settled = (at(row, i) for i in (6, 7, 8, 9, 14))
        if (venue not in VENUES.values() or not day(dt) or not rno.isdigit()
                or not rid.isdigit() or not lane.isdigit() or not course.isdigit()
                or not st or not finish or settled != "1"):
            continue
        key = (venue, day(dt), int(rno), rid)
        previous = races.get(key, {})
        races[key] = dict(start=previous.get("start", ""), day=day(dt), rno=int(rno),
                          rid=rid, lane=lane, course=course, st=st,
                          finish=finish, method=method)
    by_venue = defaultdict(lambda: defaultdict(list))
    for (venue, dt, rno, rid), row in races.items():
        by_venue[venue][rid].append(row)
    for racers in by_venue.values():
        for items in racers.values():
            items.sort(key=lambda v: (v["day"], v["rno"]))
    return by_venue


def valid_runs(records, start, end):
    seen = set()
    out = []
    for row in records:
        if not start <= row["day"] <= end:
            continue
        key = (row["day"], row["rno"])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def calculated_cells(existing, runs):
    """Build N:BC without discarding any manually entered slots."""
    cells = (list(existing[13:55]) + [""] * 42)[:42]
    count = len(runs)
    if not count:
        return None, False
    current_count = int(at(existing, 18)) if at(existing, 18).isdigit() else 0
    if current_count > count:
        return None, False  # Our source is less complete than manual history.
    starts = []
    courses = []
    for item in runs:
        try:
            st = float(item["st"])
            if 0 <= st <= 1:
                starts.append(st)
        except (TypeError, ValueError):
            pass
        if item["course"].isdigit():
            courses.append(int(item["course"]))
    summary = [
        f"{sum(starts) / len(starts):.2f}" if starts else "",
        f"{sum(courses) / len(courses):.2f}" if courses else "",
        sum(item["finish"] == "1" for item in runs),
        sum(item["finish"] == "2" for item in runs),
        sum(item["finish"] == "3" for item in runs),
        count,
    ]
    # Existing manually recorded slots must match their chronological entries.
    for index, item in enumerate(runs[:MAX_RUNS]):
        offset = 6 + index * RUN_COLS
        proposed = [item["rno"], int(item["lane"]), int(item["course"]),
                    item["st"], item["finish"],
                    item["method"] if item["finish"] == "1" else ""]
        for shift, value in enumerate(proposed):
            current = str(cells[offset + shift]).strip()
            if current and current != str(value).strip():
                # Some legacy tabs format ST with a different number of decimals.
                if shift == 3:
                    try:
                        if abs(float(current) - float(value)) < 0.00001:
                            continue
                    except ValueError:
                        pass
                return None, True
    changed = False
    for i, value in enumerate(summary):
        if str(cells[i]) != str(value):
            cells[i] = value
            changed = True
    for index, item in enumerate(runs[:MAX_RUNS]):
        offset = 6 + index * RUN_COLS
        proposed = [item["rno"], int(item["lane"]), int(item["course"]),
                    item["st"], item["finish"],
                    item["method"] if item["finish"] == "1" else ""]
        for shift, value in enumerate(proposed):
            if str(cells[offset + shift]).strip() == "" and value != "":
                cells[offset + shift] = value
                changed = True
    return cells if changed else None, False


def build_new_roster(today, code, start, end, title, grade, motor_map, player_map):
    """Only adopt a complete official field; never create a partial/fake section."""
    roster = {}
    def one(rno):
        return official.parse_racelist_boats(today, code, rno)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(one, rno): rno for rno in range(1, 13)}
        for future in as_completed(futures):
            try:
                boats = future.result()
            except Exception:
                return []
            if len(boats) != 6:
                return []
            for boat in boats:
                rid = str(boat["racer_id"])
                if rid in roster:
                    old = roster[rid]
                    if (old.get("motor_number") != boat.get("motor_number")
                            or old.get("name") != boat.get("name")):
                        return []
                else:
                    roster[rid] = boat
    if not (35 <= len(roster) <= 70):
        return []
    out = []
    for rid, boat in sorted(roster.items(),
                            key=lambda pair: (CLASS_ORDER.get(pair[1]["current_class"], 9), int(pair[0]))):
        motor_num = str(boat.get("motor_number") or "")
        motor = motor_map.get((code, motor_num), {})
        two = boat.get("motor_top2_rate")
        three = boat.get("motor_top3_rate")
        def pct(value):
            if value is None or value == "":
                return ""
            try:
                v = float(str(value).replace("%", ""))
                return f"{v:.1f}%"
            except ValueError:
                return ""
        out.append([
            boat["name"], rid,
            f"{start[:4]}/{start[4:6]}/{start[6:]}", f"{end[:4]}/{end[4:6]}/{end[6:]}",
            title, grade, boat["current_class"], player_map.get(rid, ""),
            motor_num, motor.get("win", ""),
            pct(two), pct(three), motor.get("grade", ""),
            "", "", 0, 0, 0, 0,
        ])
    return out


def main():
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    book = gspread.authorize(creds).open_by_key(ID)
    foot = book.worksheet("足回り推移").get_all_values()
    st = book.worksheet("ST節間結果_RAW").get_all_values()
    source = official_result_records(foot, st)
    today = datetime.now(JST).strftime("%Y%m%d")
    players = book.worksheet("選手データ").get("A2:D1800")
    player_map = {at(row, 0): at(row, 3) for row in players if at(row, 0)}
    motor_rows = book.worksheet("モーターデータ").get("A2:U1800")
    motor_map = {
        (at(row, 0).zfill(2), at(row, 2)): {
            "win": at(row, 5), "grade": at(row, 20),
        }
        for row in motor_rows if at(row, 0).isdigit() and at(row, 2).isdigit()
    }
    try:
        active = set(official.discover_venues(today))
    except Exception:
        active = set()
    stats = {"day": today, "dry_run": DRY_RUN, "active": len(active), "updated_venues": {},
             "new_meetings": [], "conflicts": [], "skipped": [], "source_records": sum(
                 len(records) for venue in source.values() for records in venue.values())}
    additions = 0
    for code, venue in VENUES.items():
        if code not in active:
            continue
        ws = book.worksheet(venue)
        rows = ws.get_all_values()
        if len(rows) < 2 or at(rows[1], 0) != "選手名" or at(rows[1], 1) != "登録番号":
            stats["skipped"].append(f"{venue}: schema mismatch")
            continue
        # For an already-established current meeting, trust the sheet's
        # verified start/end dates. Official event headings are inconsistent
        # between venues and must not block settled result updates.
        known = [(day(at(row, 2)), day(at(row, 3)))
                 for row in rows[2:]
                 if at(row, 1).isdigit() and
                 day(at(row, 2)) <= today <= day(at(row, 3))]
        raw = ""
        if known:
            start, end = max(known)
        else:
            try:
                raw = official.fetch(official.official_url("racelist", today, code, 1))
            except Exception:
                stats["skipped"].append(f"{venue}: official meeting unavailable")
                continue
            window = section_window(today, raw)
            if not window:
                stats["skipped"].append(f"{venue}: official start/end not verified")
                if code in {"01", "04"}:
                    print("Venue heading diagnostics " + venue + ": " +
                          repr(official.textify(raw)[:700]), flush=True)
                continue
            start, end = window
        present = [row for row in rows[2:] if day(at(row, 2)) == start
                   and at(row, 1).isdigit()]
        latest = max((day(at(row, 2)) for row in rows[2:] if day(at(row, 2))), default="")
        if not present and start > latest:
            if additions >= MAX_NEW_MEETINGS:
                stats["skipped"].append(f"{venue}: new-series quota; next run")
                continue
            title = series_title(raw)
            if not title:
                stats["skipped"].append(f"{venue}: no verified official series title")
                continue
            grade = series_grade(title)
            new_rows = build_new_roster(today, code, start, end, title, grade, motor_map, player_map)
            if not new_rows:
                stats["skipped"].append(f"{venue}: incomplete official roster")
                continue
            # Insert new section above history; never sort or rewrite old entries.
            if not DRY_RUN:
                ws.insert_rows(new_rows, row=3, value_input_option="RAW", inherit_from_before=False)
            additions += 1
            stats["new_meetings"].append(f"{venue} {start} ({len(new_rows)} racers)")
            rows = (ws.get_all_values() if not DRY_RUN else rows[:2] + new_rows + rows[2:])
            present = [row for row in rows[2:] if day(at(row, 2)) == start
                       and at(row, 1).isdigit()]
        if not present:
            stats["skipped"].append(f"{venue}: no verified current roster")
            continue
        edits = []
        updated = 0
        # Correct only two explicitly verified general-class meetings that a
        # prior release mistakenly tagged G1 after reading site-wide menus.
        verified_grade_fixes = {
            ("01", "20261007"): ("日本一しょうゆ杯", "一般"),
            ("07", "20261007"): ("幸田町長杯", "一般"),
        }
        fix = verified_grade_fixes.get((code, start))
        if fix:
            for idx, row in enumerate(rows[2:], start=3):
                if (day(at(row, 2)) == start and fix[0] in at(row, 4)
                        and at(row, 5) == "G1"):
                    if not DRY_RUN:
                        edits.append({"range": f"F{idx}", "values": [[fix[1]]]})
                    stats.setdefault("grade_corrections", []).append(f"{venue} F{idx}")

        for index, row in enumerate(rows[2:], start=3):
            if day(at(row, 2)) != start or not at(row, 1).isdigit():
                continue
            records = source.get(venue, {}).get(at(row, 1), [])
            valid = valid_runs(records, start, end)
            payload, conflict = calculated_cells(row, valid)
            if conflict:
                stats["conflicts"].append(f"{venue} row {index} racer {at(row, 1)}")
            if payload is not None:
                edits.append({"range": f"N{index}:BC{index}", "values": [payload]})
                updated += 1
        if edits and not DRY_RUN:
            for i in range(0, len(edits), 80):
                ws.batch_update(edits[i:i+80], value_input_option="RAW")
        stats["updated_venues"][venue] = updated
    print(json.dumps(stats, ensure_ascii=False))
    if stats["conflicts"]:
        print("::warning::Some existing manual race slots disagreed; left untouched", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
