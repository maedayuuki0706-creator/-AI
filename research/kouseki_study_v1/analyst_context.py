"""Descriptive historical race analysis; no live model or notification changes."""
from __future__ import annotations
import json
import math
from collections import Counter
from datetime import timedelta
from pathlib import Path
from analytics import as_day, is_six, wilson

METHODS = ("逃げ", "差し", "まくり", "まくり差し", "抜き", "恵まれ")


def valid_number(x, lo, hi):
    return type(x) in (int, float) and math.isfinite(x) and lo <= x <= hi


def read_history(archive, target_day):
    """Only complete, normal six-finisher races from strictly earlier days."""
    cutoff = as_day(target_day)
    audit = Counter()
    races = []
    for p in sorted(Path(archive).glob("[0-9]" * 8 + "/[0-9][0-9]_[0-9][0-9].json")):
        try:
            day = as_day(p.parent.name)
            if not cutoff - timedelta(days=365) <= day < cutoff:
                continue
            race = json.loads(p.read_text(encoding="utf-8"))
            code, number = str(race["jcd"]).zfill(2), int(race["rno"])
            rows = race["rows"]
            if (race.get("settled") is not True or str(race["day"]) != p.parent.name
                or code not in [f"{i:02}" for i in range(1, 25)] or not 1 <= number <= 12
                or p.stem != f"{code}_{number:02}" or not is_six(rows)
                or any(str(b.get("day",race["day"]))!=p.parent.name or str(b.get("jcd",code)).zfill(2)!=code or b.get("rno",number)!=number for b in rows)
                or any(type(b.get("finish")) is not int or type(b.get("actual_course")) is not int for b in rows)
                or sorted(b["finish"] for b in rows) != list(range(1, 7))
                or sorted(b["actual_course"] for b in rows) != list(range(1, 7))):
                audit["excluded_incomplete_or_invalid"] += 1
                continue
            winner = next(b for b in rows if b["finish"] == 1)
            method = winner.get("method")
            if method not in METHODS:
                method = None
                audit["missing_method"] += 1
            races.append({"day": str(race["day"]), "venue": code, "race_no": number,
                          "rows": rows, "winning_course": winner["actual_course"],
                          "method": method, "source": str(p.relative_to(archive))})
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            audit["excluded_unreadable"] += 1
    audit["included_races"] = len(races)
    return races, dict(audit)


def rate(k, n):
    return {"count": k, "n": n, "pct": round(100*k/n, 1) if n else None,
            "wilson95_pct": wilson(k, n)}


def method_table(races):
    known = [r for r in races if r["method"] is not None]
    return {"races": len(races), "known_method": len(known),
            "method_rates": {m: rate(sum(r["method"] == m for r in known), len(known)) for m in METHODS}}


def racer_course(races, racer_id, course):
    matched = [(r, b) for r in races for b in r["rows"]
               if str(b["racer_id"]) == str(racer_id) and b["actual_course"] == course]
    wins = [(r, b) for r, b in matched if b["finish"] == 1]
    known_wins = [r for r, _ in wins if r["method"] is not None]
    known = [(r,b) for r,b in matched if r["method"] is not None]
    losses_known = [r for r,b in known if b["finish"] != 1]
    return {"starts_normal": len(matched), "first": rate(len(wins), len(matched)),
            "known_wins": len(known_wins),
            "winning_methods": {m: rate(sum(r["method"] == m for r in known_wins), len(known_wins)) for m in METHODS},
            "loss_race_winning_methods": {m: rate(sum(r["method"] == m for r in losses_known),len(losses_known)) for m in METHODS},
            "other_course1_escape": rate(sum(r["winning_course"] == 1 and r["method"] == "逃げ" for r,b in known),len(known)) if course == 2 else None,
            "source_paths": [r["source"] for r,b in matched]}


def venue_patterns(races):
    # Counts are historical observations, not forecasts.
    groups = []
    for course in range(1,7):
        sample = [r for r in races if r["winning_course"] == course]
        pairs = Counter(tuple(b["actual_course"] for b in sorted(r["rows"],key=lambda b:b["finish"])[1:3]) for r in sample)
        groups.append({"winning_course": course, "frequency": rate(len(sample),len(races)),
                       "methods": method_table(sample),
                       "second_third_course_counts": [{"courses":list(k),"count":v} for k,v in sorted(pairs.items())]})
    return groups


def pre_race_exhibition(target):
    """Use only explicit exhibition fields; never inspect target finish or actual ST."""
    rows = sorted(target["rows"], key=lambda b:b["lane"])
    times = [b.get("exhibition_time") for b in rows]
    valid = [float(x) for x in times if valid_number(x, 4, 10)]
    def common_context(key, lo, hi):
        values = [b.get(key) for b in rows]
        return values[0] if all(valid_number(v,lo,hi) for v in values) and len(set(values)) == 1 else None
    return {"captured_at":target.get("captured_at"),"deadline":target.get("deadline"),
            "timestamp_validation":"not_validated_for_forward_use",
            "wind_m":common_context("wind_m",0,40),"wave_cm":common_context("wave_cm",0,200),
            "boats":[{"lane":b["lane"],"motor_number":b.get("motor_number"),
                      "tilt":b.get("tilt"),"exhibition_time":float(t) if valid_number(t,4,10) else None,
                      "exhibition_rank":1+sum(v<float(t) for v in valid) if len(valid)==6 else None}
                      for b,t in zip(rows,times)],
            "missing":["wind_direction","tide","motor_cycle","original_exhibition_split_times"]}


def build_context(archive, target):
    if not is_six(target.get("rows")):
        raise ValueError("invalid target lineup")
    code = str(target["jcd"]).zfill(2)
    if code not in [f"{i:02}" for i in range(1,25)]:
        raise ValueError("invalid venue")
    races,audit = read_history(archive,str(target["day"]))
    local = [r for r in races if r["venue"] == code]
    return {"schema":"boat-analyst-context-v0.2","history_audit":audit,
            "source":"data/exhibition_log / settled historical records",
            "earliest_day":min((r["day"] for r in races),default=None),
            "latest_day":max((r["day"] for r in races),default=None),
            "venue":{"code":code,"methods":method_table(local),"patterns":venue_patterns(local)},
            "racers":[{"lane":b["lane"],"racer_id":str(b["racer_id"]),
                       "courses":[{"course":c,"national":racer_course(races,b["racer_id"],c),
                                   "local":racer_course(local,b["racer_id"],c)} for c in range(1,7)]}
                      for b in sorted(target["rows"],key=lambda b:b["lane"])],
            "exhibition":pre_race_exhibition(target),
            "limitations":["normal completed races only; excludes F/disqualification and other incomplete races",
                           "winning method is a race-level label; losing method counts are associations, not causal evidence",
                           "historical archive coverage is incomplete; no motor-number aggregation without cycle ID",
                           "historical frequencies and exhibition ranks are not calibrated future probabilities"]}
