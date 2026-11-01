"""ULTIMATE BOAT LAB: independent evidence and scenario *research* engine.

The three named data sites inspire independently derived features. This file
does not fetch, copy, login to, or reuse predictions from any third-party site.
It also does not send notifications, place bets, or change production AI.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from hashlib import sha256
from itertools import permutations
import json
import math
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
VERSION = "ultimate-fusion-research-v0.1"
COMBOS = tuple("-".join(map(str, p)) for p in permutations(range(1, 7), 3))
VENUE_CODES = frozenset(f"{n:02d}" for n in range(1, 25))
OUTCOME_KEYS = frozenset(("finish", "actual_st", "actual_course", "method", "payout", "trifecta", "result"))
PRE_RACE_KEYS = frozenset((
    "lane", "racer_id", "name", "exhibition_course", "exhibition_time",
    "exhibition_st", "tilt", "motor_number", "boat_number", "current_class",
    "wind_m", "wave_cm", "weight_kg", "parts_exchange",
))
IDEAS = {
    "boaters": ("venue_lane_results", "entry_change", "leader_conditional_follower"),
    "frontier": ("course_vs_course", "course_start_profile", "finish_given_leader"),
    "biyori": ("outer_exhibition_gap", "front_entry", "tilt_jump", "st_gap"),
    "owned_research": ("original_exhibition", "motor_cycle", "weather", "odds"),
}


def aware(value):
    if isinstance(value, datetime):
        dt = value
    elif value:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        raise ValueError("Missing timestamp")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Timezone-aware timestamps required")
    return dt.astimezone(JST)


def identity(day, code, rno):
    datetime.strptime(str(day), "%Y%m%d")
    code = str(code).zfill(2)
    if code not in VENUE_CODES or not 1 <= int(rno) <= 12:
        raise ValueError("Unknown venue or race")
    return f"{day}_{code}_{int(rno):02d}"


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(raw.encode()).hexdigest()


def number(value, lo, hi):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return round(n, 4) if math.isfinite(n) and lo <= n <= hi else None


def boats_six(boats):
    if not isinstance(boats, list) or len(boats) != 6:
        raise ValueError("Exactly six boats required")
    lanes = [int(b["lane"]) for b in boats]
    ids = [str(b.get("racer_id") or "") for b in boats]
    if sorted(lanes) != [1, 2, 3, 4, 5, 6] or not all(ids) or len(set(ids)) != 6:
        raise ValueError("Invalid six-boat identity")


def _deadline(day, hhmm):
    return aware(datetime.strptime(f"{day} {hhmm}", "%Y%m%d %H:%M").replace(tzinfo=JST))


def prepare_live(raw, observed_at=None, minimum_lead_s=180):
    """Strict as-of snapshot. Never treat a post-result record as live input."""
    day, code, rno = raw["day"], str(raw["jcd"]).zfill(2), int(raw["rno"])
    key = identity(day, code, rno)
    taken = aware(raw["captured_at"])
    deadline = _deadline(day, raw["deadline"])
    observed = aware(observed_at) if observed_at else taken
    if raw.get("settled") or any(
        b.get(k) is not None for b in raw.get("rows", []) for k in OUTCOME_KEYS
    ):
        raise ValueError("Current-race result leakage")
    if not taken <= observed <= deadline - timedelta(seconds=minimum_lead_s):
        raise ValueError("Not a predeadline and timely snapshot")
    if (observed - taken).total_seconds() > 180:
        raise ValueError("Stale source: older than 180 seconds")
    if taken.date() != deadline.date():
        raise ValueError("Wrong local racing day")
    boats_six(raw["rows"])
    rows = []
    for b in sorted(raw["rows"], key=lambda b: int(b["lane"])):
        course = b.get("exhibition_course")
        if course is not None and int(course) not in range(1, 7):
            raise ValueError("Invalid entry course")
        rows.append({
            k: (number(b.get(k), -0.3, 3) if k == "exhibition_st"
                else number(b.get(k), 4, 10) if k == "exhibition_time"
                else number(b.get(k), -1, 3) if k == "tilt"
                else b.get(k))
            for k in PRE_RACE_KEYS
        })
    return {
        "race_id": key, "day": day, "venue_code": code, "race_no": rno,
        "snapshot_at": taken.isoformat(), "deadline_at": deadline.isoformat(),
        "race_status": "predeadline", "boats": rows,
        "sha256": digest({"race_id": key, "captured_at": taken.isoformat(), "boats": rows}),
    }


def historical_evidence(records, target_day, venue_code, *, min_leader_races=30):
    """Exclude target day and all future dates. Nothing from 1M replay is used live."""
    venue_code = str(venue_code).zfill(2)
    identity(target_day, venue_code, 1)
    leaders = Counter()
    triples = Counter()
    totals = Counter()
    accepted_races = set()
    for raw in records:
        try:
            day = raw["day"]
            code = str(raw["jcd"]).zfill(2)
            if day >= target_day or code != venue_code or not raw.get("settled"):
                continue
            key = identity(day, code, raw["rno"])
            if key in accepted_races:
                continue
            boats_six(raw["rows"])
            result = {}
            for b in raw["rows"]:
                if not isinstance(b.get("finish"), int):
                    raise ValueError("Missing official finish")
                if b["finish"] in result:
                    raise ValueError("Duplicate finishing place")
                result[b["finish"]] = int(b["lane"])
            if sorted(result) != [1, 2, 3, 4, 5, 6]:
                continue
            lead = result[1]
            follow = (result[2], result[3])
            leaders[lead] += 1
            triples[(lead, *follow)] += 1
            totals["finished_races"] += 1
            accepted_races.add(key)
        except (TypeError, KeyError, ValueError):
            continue
    models = {}
    for head in range(1, 7):
        observed = leaders[head]
        models[str(head)] = {
            "leader_races": observed,
            "status": "observed_research_only" if observed >= min_leader_races
                      else "insufficient_leader_sample",
            "top_followers": [
                {"second": second, "third": third, "count": n,
                 "conditional_frequency": round(n / observed, 4) if observed >= min_leader_races else None}
                for (h, second, third), n in triples.most_common()
                if h == head
            ][:10] if observed >= min_leader_races else [],
        }
    return {
        "target_day": target_day, "venue_code": venue_code,
        "training_scope": "dates_strictly_before_target",
        "race_count": totals["finished_races"],
        "outcome_source": "owned_official_historical_results",
        "models": models, "is_calibrated_120_probability_model": False,
    }


def derive_alerts(snapshot):
    """Rebuild the *ideas* behind Biyori alerts from owned observations."""
    boats = sorted(snapshot["boats"], key=lambda b: b["lane"])
    alerts = []
    for b in boats:
        lane = b["lane"]
        lane_entry = b.get("exhibition_course")
        if lane_entry is not None and int(lane_entry) != lane:
            alerts.append({
                "kind": "entry_changed", "lane": lane,
                "shown_course": int(lane_entry),
                "status": "observed_from_official_exhibition",
            })
        tilt = b.get("tilt")
        if tilt is not None and tilt >= 0.5:
            alerts.append({
                "kind": "tilt_jump", "lane": lane,
                "tilt": tilt, "status": "threshold_not_validated",
            })
        t = b.get("exhibition_time")
        if t is None:
            continue
        inside = [x["exhibition_time"] for x in boats[:lane - 1]
                  if x.get("exhibition_time") is not None]
        if inside and min(inside) - t >= 0.07:
            alerts.append({
                "kind": "outer_exhibition_advantage", "lane": lane,
                "ahead_of_fastest_inner_seconds": round(min(inside) - t, 3),
                "status": "hypothesis_only_not_makuri_probability",
            })
    return alerts


def original_exhibition(foot, snapshot):
    """Only first-party provenance whose publication and capture precede deadline.

    Existing retro-mirror material deliberately fails the prospective gate.
    """
    if not foot or foot.get("race_id") != snapshot["race_id"]:
        return {"status": "missing", "measurements": None}
    acq = foot.get("acquisition") or {}
    try:
        captured = aware(acq["retrieved_at"])
        published = aware(acq["published_at"])
        deadline = aware(snapshot["deadline_at"])
        if (acq.get("source_family") != "venue_official_verified" or
            captured > deadline or published > captured or
            foot.get("status") != "ok"):
            raise ValueError("Source not prospectively verified")
        boats_six(foot.get("rows"))
        known_ids = {int(b["lane"]): str(b["racer_id"]) for b in snapshot["boats"]}
        if any(str(b["racer_id"]) != known_ids[int(b["lane"])] for b in foot["rows"]):
            raise ValueError("Identity mismatch")
    except (ValueError, KeyError, TypeError):
        return {"status": "retrospective_or_unverified_not_used", "measurements": None}
    return {
        "status": "verified_predeadline",
        "source_url": acq.get("url"),
        "record_digest": digest(foot),
        "measurements": [
            {k: b.get(k) for k in ("lane", "racer_id", "lap_time", "half_lap_time", "turn_time", "straight_time")}
            for b in sorted(foot["rows"], key=lambda b: int(b["lane"]))
        ],
    }


def research_report(snapshot, history=None, foot=None):
    """Explain signals; no artificial 120-combo probabilities or fake EV."""
    profile = history if history is not None else historical_evidence([], snapshot["day"], snapshot["venue_code"])
    if profile["venue_code"] != snapshot["venue_code"] or profile["target_day"] != snapshot["day"]:
        raise ValueError("Wrong venue or future evidence")
    speed = {str(b["lane"]): b["exhibition_time"] for b in snapshot["boats"]}
    return {
        "version": VERSION,
        "race_id": snapshot["race_id"],
        "source_families": {
            "boaters_inspired": "derived_from_own_official",
            "frontier_inspired": "derived_from_own_official",
            "biyori_inspired": "derived_from_own_official",
            "third_party_site_api_integrated": False,
        },
        "features": {"exhibition_time_by_lane": speed, "alerts": derive_alerts(snapshot)},
        "conditional_history": profile,
        "original_foot": original_exhibition(foot, snapshot),
        "result_consulted": False,
        "ready_for_betting": False,
        "estimated_hit_probability": None,
        "estimated_trifecta_distribution": None,
        "ev": None,
        "not_ready_reason": "Requires out-of-time 120-way model calibration and official odds snapshot",
        "snapshot_sha256": snapshot["sha256"],
    }


def ev_only_after_validation(probabilities, odds, validated):
    """Do not manufacture EV from uncalibrated rankings."""
    if not validated:
        return {"status": "uncalibrated", "ev": None}
    if set(probabilities) != set(COMBOS) or len(probabilities) != 120:
        raise ValueError("120 separate combo probabilities required")
    vals = [float(probabilities[k]) for k in COMBOS]
    if not all(math.isfinite(v) and v >= 0 for v in vals) or abs(sum(vals) - 1.0) > 1e-6:
        raise ValueError("Invalid trifecta probability distribution")
    ev = {}
    for combo, p in probabilities.items():
        decimal = number(odds.get(combo), 1, 100000)
        if decimal is not None:
            ev[combo] = round(p * decimal, 4)
    return {"status": "research_estimate_not_guarantee", "ev": ev}
