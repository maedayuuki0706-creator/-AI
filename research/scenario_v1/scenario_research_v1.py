"""Standalone six-boat race-flow hypotheses. Research only; zero delivery/wager API.

Uses a pre-race snapshot only. No probabilities, odds, or ticket recommendations.
Results are processed separately and cannot change a frozen forecast.
"""
from __future__ import annotations

from datetime import datetime
from itertools import permutations
from math import isfinite

VERSION = "yuuki-scenario-research-v1"
TACTICS = {
    1: ("逃げ",),
    2: ("差し", "まくり"),
    3: ("まくり", "まくり差し", "差し"),
    4: ("まくり", "まくり差し", "差し"),
    5: ("まくり差し", "まくり"),
    6: ("まくり差し", "まくり"),
}
OUTCOME_KEYS = {"result", "finish", "actual_st", "actual_course", "payout", "payout_per_100", "winning_method"}


def numeric(value):
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if isfinite(x) else None


def _metadata(meta):
    if not isinstance(meta, dict):
        raise ValueError("meta must be an object")
    day = str(meta.get("day") or "")
    try:
        datetime.strptime(day, "%Y%m%d")
        jcd, rno = int(meta["jcd"]), int(meta["rno"])
        deadline = datetime.strptime(day + " " + str(meta["deadline"]), "%Y%m%d %H:%M")
        captured = datetime.fromisoformat(str(meta["captured_at"]))
        if captured.tzinfo is None or captured.utcoffset() is None:
            raise ValueError("Capture time must include timezone")
        from zoneinfo import ZoneInfo
        captured_local = captured.astimezone(ZoneInfo("Asia/Tokyo")).replace(tzinfo=None)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Need valid day/jcd/rno/deadline/captured_at with timezone") from exc
    if not (1 <= jcd <= 24 and 1 <= rno <= 12):
        raise ValueError("Invalid venue/race number")
    if captured_local.date() != deadline.date() or not captured_local < deadline:
        raise ValueError("Forecast must be captured on race day, before the deadline")
    if (deadline - captured_local).total_seconds() < 180:
        raise ValueError("Research capture requires >=3 minutes before deadline")
    return {"day": day, "jcd": f"{jcd:02}", "rno": rno, "deadline": meta["deadline"], "captured_at": captured.isoformat(), "race_id": f"{day}_{jcd:02}_{rno:02}"}


def _boats(analysis):
    if not isinstance(analysis, dict) or not isinstance(analysis.get("inputs"), list):
        raise ValueError("Analysis requires six pre-race inputs")
    if OUTCOME_KEYS.intersection(analysis):
        raise ValueError("Outcome fields forbidden in a pre-race snapshot")
    rows = {}
    for src in analysis["inputs"]:
        if not isinstance(src, dict) or OUTCOME_KEYS.intersection(src):
            raise ValueError("Non-boat or outcome field in input")
        try:
            lane = int(src["lane"])
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError("All six lanes are required") from exc
        if lane in rows or lane not in range(1, 7):
            raise ValueError("Duplicate/invalid lane")
        course = src.get("predicted_course") or src.get("course") or lane
        try:
            course = int(course)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid predicted course") from exc
        motor2 = numeric(src.get("motor_top2_rate"))
        if motor2 is not None and not (0 <= motor2 <= 100):
            raise ValueError("Invalid motor percentage")
        avg = numeric(src.get("avg_st"))
        if avg is None:
            avg = numeric(src.get("average_st"))
        exhibition = numeric(src.get("exhibition_st"))
        rows[lane] = {
            "lane": lane, "course": course, "avg_st": avg,
            "exhibition_st": exhibition, "motor_top2_rate": motor2,
            "racer_id": str(src.get("racer_id") or ""),
        }
    if set(rows) != set(range(1, 7)) or set(x["course"] for x in rows.values()) != set(range(1, 7)):
        raise ValueError("Six unique lanes and courses required")
    return rows


def _evidence(boat):
    observations = []
    if boat["avg_st"] is not None:
        observations.append({"source_field": "avg_st", "observed": boat["avg_st"], "note": "average, not a guaranteed race start"})
    if boat["exhibition_st"] is not None:
        observations.append({"source_field": "exhibition_st", "observed": boat["exhibition_st"], "note": "exhibition only; weak predictor of race ST"})
    if boat["motor_top2_rate"] is not None:
        observations.append({"source_field": "motor_top2_rate", "observed": boat["motor_top2_rate"], "note": "historical rate; not foot-category proof"})
    return observations


def _conditions(tactic, course):
    if tactic == "逃げ":
        return "1コースが先マイでき、旋回出口の加速を保つ"
    if tactic == "差し":
        return "内艇の先マイで内側に差し場ができ、出足で届く"
    if tactic == "まくり":
        return "内側より先行する隊形を作り、外から攻め切る"
    return "内側の攻め合いやターン流れで艇間が開き、外から差し込む"


def _failure(tactic):
    if tactic == "逃げ":
        return "先マイ前に攻められる、またはターンが膨らみ内差しを許す"
    if tactic == "差し":
        return "差し場が開かない、またはターン出口の押しが足りず届かない"
    if tactic == "まくり":
        return "内艇の抵抗で攻めが止まり、ターンが流れて後続に差される"
    return "艇間が開かず、内艇が残るか外の艇に先行される"


def _reactions(head, tactic, boats):
    own = boats[head]["course"]
    result = []
    for lane in sorted(boats):
        if lane == head:
            continue
        relative = boats[lane]["course"] - own
        if tactic == "逃げ":
            role = "差しに構える可能性" if relative == 1 else "外から追走・攻める可能性"
        elif relative < 0:
            role = "内側で抵抗・残り目を狙う可能性" if tactic == "まくり" else "先マイして残る可能性"
        elif relative == 1:
            role = "攻めに連動して展開を拾う可能性"
        else:
            role = "外から展開を拾う可能性"
        result.append({"lane": lane, "hypothesis": role})
    return result


def _formations(head, tactic, boats, count=3):
    """Plausibility ordering only: course proximity + tactical interaction; NOT probabilities."""
    order = {lane: boat["course"] for lane, boat in boats.items()}
    own = order[head]
    others = [x for x in sorted(boats) if x != head]
    def rank(lane):
        dist = order[lane] - own
        if tactic == "まくり":
            return (0 if dist == 1 else 1 if dist < 0 else 2, abs(dist), order[lane])
        if tactic in ("差し", "まくり差し"):
            return (0 if dist < 0 else 1, abs(dist), order[lane])
        return (abs(order[lane] - 2), order[lane], 0)
    ranked = sorted(others, key=rank)
    combos = []
    for pair in permutations(ranked[:4], 2):
        combo = f"{head}-{pair[0]}-{pair[1]}"
        if combo not in combos:
            combos.append(combo)
        if len(combos) == count:
            break
    return combos


def generate(analysis, meta):
    """Accept an immutable pre-race official-analysis snapshot; return research hypotheses."""
    metadata = _metadata(meta)
    boats = _boats(analysis)
    preview = analysis.get("preview") or {}
    if not isinstance(preview, dict) or OUTCOME_KEYS.intersection(preview):
        raise ValueError("Outcome in race preview")
    wind, wave = numeric(preview.get("wind_speed")), numeric(preview.get("wave_cm"))
    context = {"wind_speed_mps": wind, "wave_cm": wave,
               "wind_direction": preview.get("wind_direction"),
               "notes": "Environment observations are context only; no unverified venue-specific adjustment"}
    rows = []
    for lane in range(1, 7):
        boat = boats[lane]
        course = boat["course"]
        hypotheses = []
        for tactic in TACTICS[course]:
            hypotheses.append({
                "id": f"{metadata['race_id']}_{lane}_{tactic}",
                "tactic": tactic,
                "trigger_hypothesis": _conditions(tactic, course),
                "win_path": f"{lane}号艇が{tactic}で先行し、その後の出口加速を保つ",
                "loss_path": _failure(tactic),
                "reactions": _reactions(lane, tactic, boats),
                "possible_trifectas": _formations(lane, tactic, boats),
                "trifecta_probability": None,
                "calibration_status": "not_calibrated",
            })
        rows.append({"lane": lane, "predicted_course": course, "evidence": _evidence(boat),
                     "hypotheses": hypotheses})
    return {"version": VERSION, "status": "research_only", "meta": metadata,
            "environment": context, "lanes": rows,
            "limitations": ["Hypotheses, not verified predictions or betting recommendations",
                            "No calibrated probabilities, EV, or order certainty",
                            "Exhibition ST does not predict the actual race ST",
                            "Unknown foot condition is not inferred from motor 2-ren-rate",
                            "Weather/course comments must be checked with matched historical data",
                            "Accident/F/L/unsettled outcomes are excluded from normal failure study"]}


def review(frozen, result):
    """Separate post-race report. Never mutate the frozen pre-race record."""
    if frozen.get("version") != VERSION or frozen.get("status") != "research_only":
        raise ValueError("Not a frozen v1 prediction")
    if result.get("race_id") != frozen.get("meta", {}).get("race_id"):
        raise ValueError("Race identity mismatch")
    if result.get("status") in {"unsettled", "pending", "refund", "cancelled", "accident", "f", "l"}:
        return {"race_id": result["race_id"], "status": "excluded", "reason": result["status"]}
    if result.get("status") != "settled":
        raise ValueError("Result must have explicit settled/excluded status")
    actual = str(result.get("trifecta") or "")
    valid = {"-".join(map(str, p)) for p in permutations(range(1, 7), 3)}
    if actual not in valid:
        raise ValueError("Invalid finish order")
    head = int(actual.split("-")[0])
    matched = [x["id"] for row in frozen["lanes"] for x in row["hypotheses"] if actual in x["possible_trifectas"]]
    return {"race_id": result["race_id"], "status": "reviewed", "actual_trifecta": actual,
            "actual_head": head, "head_covered": any(x["lane"] == head for x in frozen["lanes"]),
            "formation_matches": matched, "formation_match": bool(matched),
            "error_category": None if matched else "formation_not_covered",
            "interpretation": "Coverage diagnostic only; does not prove the predicted tactical mechanism"}
