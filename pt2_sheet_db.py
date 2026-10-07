"""PT2 adapter for the Google Sheets-backed boat-race database snapshot.

Live BOAT RACE inputs remain authoritative. Spreadsheet history refines only
PT2's existing-model probabilities before the PT3-consensus compression step.
"""
from __future__ import annotations
from copy import deepcopy
from functools import lru_cache
import json
from math import isfinite
from pathlib import Path

ROOT = Path("data/sheet_db")
GRADE_SCORE = {"S": 1.00, "A": 0.86, "B": 0.72, "C": 0.57, "D": 0.42}

def _clip(value, lo, hi):
    return max(lo, min(hi, value))

def _number(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None

@lru_cache(maxsize=1)
def load_database():
    def load(name, default):
        path = ROOT / name
        if not path.exists():
            return default
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, type(default)) else default
        except Exception:
            return default
    return {
        "players": load("players.json", {}),
        "motors": load("motors.json", {}),
        "venues": load("venues.json", {}),
        "meta": load("meta.json", {}),
    }

def clear_cache():
    load_database.cache_clear()

def _grade_average(motor):
    values = []
    for key in ("launch", "run", "turn", "stretch", "exhibition", "grade"):
        value = str(motor.get(key) or "").strip().upper()
        if value in GRADE_SCORE:
            values.append(GRADE_SCORE[value])
    return sum(values) / len(values) if values else None

def _method_factor(player, venue, course):
    if not player or not venue:
        return 1.0
    if course == 1:
        p = _number(player.get("escape"))
        v = _number(venue.get("escape"))
    else:
        pvals = [_number(player.get(k)) for k in ("sashi", "makuri", "makurisashi")]
        vvals = [_number(venue.get(k)) for k in ("sashi", "makuri", "makurisashi")]
        pvals = [x for x in pvals if x is not None and x > 0]
        vvals = [x for x in vvals if x is not None and x > 0]
        p = max(pvals) if pvals else None
        v = max(vvals) if vvals else None
    if p is None or v is None or p <= 0 or v <= 0:
        return 1.0
    return _clip(((p + 5.0) / (v + 5.0)) ** 0.10, 0.96, 1.05)

def _boat_factor(boat, venue, players, motors, jcd):
    rid = str(boat.get("racer_id") or "")
    motor_no = boat.get("motor_number")
    course = int(boat.get("predicted_course") or boat.get("course") or boat.get("lane") or 0)
    player = players.get(rid) or {}
    motor = motors.get(f"{jcd}:{int(motor_no)}") if motor_no is not None else None
    motor = motor or {}
    factor = 1.0
    reasons = []
    player_used = False
    motor_used = False

    course_rates = player.get("course_win") or []
    venue_rates = venue.get("course_win") or []
    if 1 <= course <= 6 and len(course_rates) >= course and len(venue_rates) >= course:
        p = _number(course_rates[course - 1])
        v = _number(venue_rates[course - 1])
        if p is not None and v is not None and p > 0 and v > 0:
            relative = _clip(((p + 8.0) / (v + 8.0)) ** 0.30, 0.87, 1.14)
            factor *= relative
            player_used = True
            reasons.append(f"course={p:.1f}/{v:.1f}")

    method = _method_factor(player, venue, course)
    if abs(method - 1.0) > 1e-9:
        factor *= method
        player_used = True
        reasons.append(f"method={method:.3f}")

    tuning = [
        _number(player.get("maintenance_grade")),
        _number(player.get("propeller_grade")),
    ]
    tuning = [value for value in tuning if value is not None]
    if tuning:
        tuning_avg = sum(tuning) / len(tuning)
        tuning_factor = _clip(1.0 + (tuning_avg - 2.5) * 0.01, 0.985, 1.025)
        factor *= tuning_factor
        player_used = True
        reasons.append(f"tuning={tuning_avg:.2f}")

    grade = _grade_average(motor)
    if grade is not None:
        motor_factor = _clip(1.0 + (grade - 0.72) * 0.18, 0.94, 1.06)
        factor *= motor_factor
        motor_used = True
        reasons.append(f"motor_grade={grade:.3f}")

    sheet_top2 = _number(motor.get("top2"))
    live_top2 = _number(boat.get("motor_top2_rate"))
    if sheet_top2 is not None and live_top2 is not None and live_top2 > 0:
        motor_rate_factor = _clip(((sheet_top2 + 15.0) / (live_top2 + 15.0)) ** 0.12, 0.97, 1.03)
        factor *= motor_rate_factor
        motor_used = True
        reasons.append(f"motor_rate={sheet_top2:.1f}/{live_top2:.1f}")

    return _clip(factor, 0.82, 1.20), player_used, motor_used, reasons

def enhance_analysis(analysis, jcd, database=None):
    copied = deepcopy(analysis)
    database = database or load_database()
    players = database.get("players") or {}
    motors = database.get("motors") or {}
    venues = database.get("venues") or {}
    meta = database.get("meta") or {}
    jcd = str(jcd).zfill(2)
    venue = venues.get(jcd) or {}

    factors = {}
    detail = {}
    player_matches = 0
    motor_matches = 0
    for boat in copied.get("inputs") or []:
        lane = int(boat.get("lane") or 0)
        if not 1 <= lane <= 6:
            continue
        factor, p_used, m_used, reasons = _boat_factor(boat, venue, players, motors, jcd)
        factors[lane] = factor
        detail[str(lane)] = {
            "factor": round(factor, 5),
            "racer_id": str(boat.get("racer_id") or ""),
            "motor_number": boat.get("motor_number"),
            "signals": reasons,
        }
        player_matches += int(p_used)
        motor_matches += int(m_used)

    rows = copied.get("trifecta") or []
    if player_matches == 0 and motor_matches == 0:
        copied["sheet_database"] = {
            "enabled": False,
            "reason": "snapshot_has_no_matching_individual_signals",
            "source": meta.get("source") or "Google Sheets 競艇AI データベース",
            "snapshot_at": meta.get("snapshot_at"),
            "spreadsheet_id": meta.get("spreadsheet_id"),
            "schema_version": meta.get("schema_version"),
            "snapshot_player_count": meta.get("player_count"),
            "snapshot_motor_count": meta.get("motor_count"),
            "snapshot_venue_count": meta.get("venue_count"),
            "player_matches": 0,
            "motor_matches": 0,
            "player_coverage_pct": 0.0,
            "motor_coverage_pct": 0.0,
            "venue_match": bool(venue),
            "venue_volatility": venue.get("volatility"),
            "lane_factors": detail,
        }
        return copied
    if len(factors) != 6 or not rows:
        copied["sheet_database"] = {
            "enabled": False,
            "reason": "insufficient_snapshot_coverage",
            "source": meta.get("source") or "Google Sheets 競艇AI データベース",
            "snapshot_at": meta.get("snapshot_at"),
            "spreadsheet_id": meta.get("spreadsheet_id"),
            "schema_version": meta.get("schema_version"),
            "snapshot_player_count": meta.get("player_count"),
            "snapshot_motor_count": meta.get("motor_count"),
            "snapshot_venue_count": meta.get("venue_count"),
            "player_matches": player_matches,
            "motor_matches": motor_matches,
            "player_coverage_pct": round(player_matches / 6 * 100, 1),
            "motor_coverage_pct": round(motor_matches / 6 * 100, 1),
            "venue_match": bool(venue),
            "venue_volatility": venue.get("volatility"),
            "lane_factors": detail,
        }
        return copied

    weighted = []
    for row in rows:
        try:
            first, second, third = map(int, str(row["combination"]).split("-"))
            base_p = float(row["probability"])
        except (KeyError, TypeError, ValueError):
            continue
        mult = factors[first] * (factors[second] ** 0.45) * (factors[third] ** 0.20)
        weighted.append((row, max(0.0, base_p) * mult))

    total = sum(value for _, value in weighted)
    if total <= 0 or len(weighted) != len(rows):
        return copied

    rebuilt = []
    for row, value in weighted:
        item = dict(row)
        p = value / total
        item["probability"] = p
        item["fair_odds"] = round(1.0 / p, 2) if p > 0 else None
        odd = _number(item.get("odds"))
        item["expected_value"] = round(p * odd, 3) if odd is not None else None
        rebuilt.append(item)
    rebuilt.sort(key=lambda item: (-float(item["probability"]), item["combination"]))
    copied["trifecta"] = rebuilt

    heads = {
        lane: sum(float(row["probability"]) for row in rebuilt
                  if row["combination"].startswith(f"{lane}-"))
        for lane in range(1, 7)
    }
    copied["heads"] = heads
    ranking = sorted(heads, key=heads.get, reverse=True)
    top = heads[ranking[0]]
    gap = top - heads[ranking[1]]
    copied["grade"] = "A" if top >= .45 and gap >= .20 else "B" if top >= .30 and gap >= .08 else "C"
    copied["sheet_database"] = {
        "enabled": True,
        "source": meta.get("source") or "Google Sheets 競艇AI データベース",
        "snapshot_at": meta.get("snapshot_at"),
        "spreadsheet_id": meta.get("spreadsheet_id"),
        "schema_version": meta.get("schema_version"),
        "snapshot_player_count": meta.get("player_count"),
        "snapshot_motor_count": meta.get("motor_count"),
        "snapshot_venue_count": meta.get("venue_count"),
        "player_matches": player_matches,
        "motor_matches": motor_matches,
        "player_coverage_pct": round(player_matches / 6 * 100, 1),
        "motor_coverage_pct": round(motor_matches / 6 * 100, 1),
        "matched_lanes": [
            lane for lane, item in detail.items() if item.get("signals")
        ],
        "venue_match": bool(venue),
        "venue_volatility": venue.get("volatility"),
        "lane_factors": detail,
    }
    return copied
