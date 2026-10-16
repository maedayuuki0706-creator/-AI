"""Four-venue research specialists. No production delivery, scraping, or calibrated odds.

V1 separates the common six-boat scenario hypothesis from seven venue-specific
observations and strictly gated historical residuals. Scores are research ranks,
NEVER probabilities or proof of a real-weather effect.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from itertools import permutations
import json
import math
from zoneinfo import ZoneInfo

from research.scenario_v2 import engine as scenario

JST = ZoneInfo("Asia/Tokyo")
VERSION = "venue-specialists-shadow-v1"
POLICY = {"points": 10, "unit_yen": 100, "heuristic_not_calibrated": True,
          "minimum_conditional_races": 200, "validated_effect_cap": 0.20,
          "standalone_research": True}
VENUES = {
    "16": {"name": "児島くん", "venue": "児島", "first_day": "20261017",
           "water_type": "海水", "tide_enabled": True},
    "03": {"name": "江戸川くん", "venue": "江戸川", "first_day": "20261017",
           "water_type": "汽水", "tide_enabled": True},
    "23": {"name": "唐津くん", "venue": "唐津", "first_day": "20261018",
           "water_type": "淡水", "tide_enabled": False},
    "06": {"name": "浜名湖くん", "venue": "浜名湖", "first_day": "20261021",
           "water_type": "汽水", "tide_enabled": True},
}


def digest(obj):
    return sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _number(value):
    if value is None or value == "":
        return None
    try:
        val = float(value)
        return val if math.isfinite(val) else None
    except (TypeError, ValueError):
        return None


def _clamp(value, cap=.20):
    return min(cap, max(-cap, value))


def _timestamp_before(value, captured):
    if not value:
        return False
    try:
        return datetime.fromisoformat(str(value).replace("/", "-")).date() <= captured.date()
    except ValueError:
        return False


def _mean(values):
    return sum(values) / len(values) if values else None


def _validated_residual(kind, course, env, captured, conditioned):
    """Apply only a historical out-of-time holdout-validated course-specific residual.

    A record must name its evidence window, 200+ races, observation match, and
    validation status. Missing or preliminary coefficients always remain zero.
    """
    trace = {"category": kind, "status": "no_validated_effect", "adjustment": 0.0}
    observed = env.get(kind)
    if observed is None:
        trace["status"] = "missing_observation"
        return trace
    for row in conditioned.get(kind, []):
        if int(row.get("course") or -1) != course:
            continue
        if row.get("validation_status") != "holdout_passed":
            continue
        if int(row.get("sample_races") or 0) < POLICY["minimum_conditional_races"]:
            continue
        if row.get("observed_bucket") != observed:
            continue
        if not _timestamp_before(row.get("training_end"), captured):
            continue
        if not _timestamp_before(row.get("validated_at"), captured):
            continue
        effect = _number(row.get("excess_log_score"))
        if effect is None:
            continue
        shrink = min(.5, int(row["sample_races"]) / (int(row["sample_races"]) + 500))
        trace.update(status="validated_research_residual",
                     adjustment=round(_clamp(effect * shrink), 5),
                     sample_races=int(row["sample_races"]),
                     evidence_id=str(row.get("evidence_id") or ""))
        return trace
    return trace


def _motor_score(boat, code, captured, motor_db):
    value = _number(boat.get("motor_top2_rate"))
    signals = [{"field": "motor_top2_rate", "value": value,
                "status": "observed" if value is not None else "missing"}]
    score = _clamp((value - 35) / 35 * .13) if value is not None else 0
    motor_no = boat.get("motor_number")
    data = motor_db.get(f"{code}:{motor_no}") if motor_no is not None else None
    if isinstance(data, dict) and _timestamp_before(data.get("as_of"), captured):
        grade = str(data.get("grade") or "").upper()
        if grade in {"S", "A", "B", "C", "D"}:
            score += {"S": .09, "A": .045, "B": 0, "C": -.045, "D": -.09}[grade]
            signals.append({"field": "current_motor_grade", "value": grade,
                            "status": "research_grade", "as_of": data["as_of"]})
        for attribute in ("launch", "stretch", "turn"):
            signals.append({"field": "motor_" + attribute,
                            "value": data.get(attribute), "status": "descriptive_only"})
    else:
        signals.append({"field": "motor_grade", "status": "missing_or_future"})
    return round(_clamp(score, .25), 5), signals


def analyze(snapshot, *, venues_db=None, motor_db=None, conditioned=None,
            mode="live", now=None):
    """Generate all-six-head causal hypotheses plus a separate 10-ticket venue card.

    Snapshot must be a frozen official pre-race payload. No results may enter it.
    """
    venues_db, motor_db, conditioned = venues_db or {}, motor_db or {}, conditioned or {}
    meta = snapshot["meta"]
    code = str(meta["jcd"]).zfill(2)
    if code not in VENUES:
        raise ValueError("Only 03 Edogawa, 06 Hamanako, 16 Kojima, 23 Karatsu")
    profile = VENUES[code]
    if str(meta["day"]) < profile["first_day"]:
        raise ValueError("Before selected specialist research start date")
    if now is None:
        now = datetime.now(JST).isoformat()
    base = scenario.generate(snapshot, mode=mode, now=now)
    captured = scenario.aware(meta["captured_at"])
    boats = sorted(base["lanes"], key=lambda b: b["predicted_course"])
    raw_stats = venues_db.get(code) or {}
    percentages = raw_stats.get("course_win")
    if not isinstance(percentages, list) or len(percentages) != 6:
        percentages = None
    else:
        percentages = [_number(x) for x in percentages]
        if any(x is None or x <= 0 or x >= 100 for x in percentages):
            percentages = None
    env = dict(snapshot.get("environment") or {})
    if not profile["tide_enabled"]:
        env.pop("tide", None)  # Never infer a tide effect at Karatsu.
    env_display = {name: env.get(name) for name in ("wind_speed", "wind_direction", "wave_cm", "tide")}
    # Bucketed studies may be supplied later only after out-of-time validation.
    env_buckets = dict(env.get("validated_buckets") or {})
    for k in ("wind", "tide", "water"):
        if k not in env_buckets:
            env_buckets[k] = None
    ranked_times = [_number(b["evidence"].get("exhibition_time")) for b in boats]
    st_times = [_number(b["evidence"].get("avg_st")) for b in boats]
    exhibition_mean = _mean(ranked_times) if all(x is not None for x in ranked_times) else None
    st_mean = _mean(st_times) if all(x is not None for x in st_times) else None

    scores, audits = {}, []
    for item in boats:
        b = item["evidence"]
        lane, course = item["lane"], item["predicted_course"]
        s = 0.0
        additions = {}
        if percentages is not None:
            # The course rate is the *venue prior*, not a probability estimate.
            # Deliberately do not also add national course rates.
            s += math.log(percentages[course-1] / 100)
            additions["venue_course_prior_log"] = round(s, 5)
        else:
            additions["venue_course_prior_log"] = None
        motor, motor_log = _motor_score(b, code, captured, motor_db)
        s += motor
        additions["motor_residual"] = motor
        st = _number(b.get("avg_st"))
        st_part = (_clamp((st_mean - st) / .05 * .10)
                   if st_mean is not None and st is not None else 0)
        s += st_part
        additions["historical_st_formation"] = round(st_part, 5)
        exhibition = _number(b.get("exhibition_time"))
        exhibition_part = (_clamp((exhibition_mean - exhibition) / .10 * .12)
                           if exhibition_mean is not None and exhibition is not None else 0)
        s += exhibition_part
        additions["exhibition_time_relative"] = round(exhibition_part, 5)
        for key, category in (("wind", "wind_conditions"),
                              ("tide", "tidal_conditions"),
                              ("water", "water_surface")):
            if key == "tide" and not profile["tide_enabled"]:
                trace = {"category": "tide", "status": "freshwater_excluded",
                         "adjustment": 0.0}
            else:
                trace = _validated_residual(key, course, env_buckets, captured, conditioned)
            s += trace["adjustment"]
            additions[category] = trace
        # Actual exhibition course is the axis of the prior; do not double-add
        # a separate front-entry bonus just because the course differs from lane.
        additions["entry_course"] = course
        additions["entry_changed"] = course != lane
        additions["exhibition_st"] = b.get("exhibition_st")  # diagnostic only
        scores[lane] = s
        audits.append({"lane": lane, "course": course, "score": round(s, 5),
                       "components": additions, "motor_evidence": motor_log,
                       "win_paths": item["win_paths"],
                       "loss_paths": item["loss_paths"],
                       "hypotheses": [{"tactic": h.get("tactic"), "attack_origin": h.get("origin_lane"),
                                      "formation_count": len(h.get("formations") or [])}
                                     for h in item["hypotheses"]]})
    coverage = set(base["formation_candidates"])
    card = []
    if percentages is not None:
        # Distinct roles for head, second and third; never directly use a
        # course top-two percentage as the first-place probability.
        rankings = []
        for first, second, third in permutations(range(1, 7), 3):
            combo = f"{first}-{second}-{third}"
            score = scores[first] + .35 * scores[second] + .15 * scores[third]
            if combo in coverage:
                score += .10  # common v2 scenario coverage, not an actual probability
            rankings.append((round(score, 8), combo, combo in coverage))
        rankings.sort(key=lambda item: (-item[0], item[1]))
        card = [{"combination": combo, "research_rank_score": value,
                 "v2_scenario_supported": supported}
                for value, combo, supported in rankings[:POLICY["points"]]]
    record = {"model": profile["name"], "venue": profile["venue"], "jcd": code,
              "version": VERSION, "start_day": profile["first_day"],
              "race_id": base["meta"]["race_id"], "research_only": True,
              "status": "prospective_uncheckpointed" if mode == "live" else "retrospective_replay",
              "created_at": now, "captured_at": base["meta"]["captured_at"],
              "deadline_at": base["meta"]["deadline_at"], "snapshot_digest": digest(snapshot),
              "common_v2_digest": base["digest"],
              "input_sources": snapshot.get("source", {}),
              "environment": env_display, "water_type": profile["water_type"],
              "tide_eligible": profile["tide_enabled"],
              "seven_features": {"course": "research_venue_prior" if percentages else "missing",
                  "motor": "observed_or_missing", "wind": "validated_only",
                  "tide": "validated_only" if profile["tide_enabled"] else "not_applicable",
                  "entry": "observed_exhibition_course", "st": "historical_avg_only",
                  "water": "validated_only"},
              "lane_audits": sorted(audits, key=lambda a: a["lane"]),
              "formation_candidates": base["formation_candidates"],
              "virtual_card": card, "card_status": "research_10_points" if card else "missing_course_prior",
              "unit_yen": 100, "stake_yen": len(card) * 100,
              "probabilities_calibrated": False,
              "limitations": ["Research scores are not win rates, fair odds, EV or proof of a weather/tide effect.",
                  "Course prior source is provisional and must receive count/date validation.",
                  "Exhibition ST does not predict actual ST; it was not used as a score.",
                  "Unvalidated weather, tide, wave and missing data add zero.",
                  "Actual tactics and six-boat positional reactions require video review.",
                  "Not a delivered prediction and not a remotely confirmed Git freeze."]}
    record["digest"] = digest(record)
    return record
