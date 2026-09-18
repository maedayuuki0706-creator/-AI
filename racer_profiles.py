"""Persistent racer profile features for BOAT RACE predictions."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

PROFILE_PATH = Path("data/racer_profiles.json")

# Conservative course priors used only to shrink small historical samples.
COURSE_PRIORS = {
    1: {"win": 55.0, "top2": 72.0},
    2: {"win": 15.0, "top2": 39.0},
    3: {"win": 13.0, "top2": 36.0},
    4: {"win": 11.0, "top2": 32.0},
    5: {"win": 5.0, "top2": 22.0},
    6: {"win": 2.0, "top2": 14.0},
}


@lru_cache(maxsize=1)
def load_profiles() -> dict:
    if not PROFILE_PATH.exists():
        return {"racers": {}, "processed_races": []}
    try:
        value = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"racers": {}, "processed_races": []}
    except Exception:
        return {"racers": {}, "processed_races": []}


def clear_cache() -> None:
    load_profiles.cache_clear()


def _smoothed_rate(successes: float, starts: float, prior_pct: float, prior_n: float = 12.0) -> float:
    if starts <= 0:
        return float(prior_pct)
    return 100.0 * (successes + prior_n * prior_pct / 100.0) / (starts + prior_n)


def profile_for(racer_id: object) -> dict | None:
    rid = str(racer_id or "")
    return (load_profiles().get("racers") or {}).get(rid)


def _weighted_counts(row: dict) -> tuple[float, float, float]:
    starts = float(row.get("weighted_starts") or row.get("starts") or 0.0)
    wins = float(row.get("weighted_wins") or row.get("wins") or 0.0)
    top2 = float(row.get("weighted_top2") or row.get("top2") or 0.0)
    return starts, wins, top2


def _relative_course_strength(profile: dict) -> list[dict]:
    ranked = []
    for course in range(1, 7):
        row = (profile.get("courses") or {}).get(str(course), {})
        raw_starts = int(row.get("starts") or 0)
        if raw_starts < 6:
            continue
        starts, wins, top2 = _weighted_counts(row)
        prior = COURSE_PRIORS[course]
        win_rate = _smoothed_rate(wins, starts, prior["win"])
        top2_rate = _smoothed_rate(top2, starts, prior["top2"])
        # Compare with the normal difficulty of that course instead of letting
        # course 1 automatically win every "best course" ranking.
        relative = (win_rate / max(prior["win"], 1.0)) * 0.65 + (top2_rate / prior["top2"]) * 0.35
        ranked.append({
            "course": course,
            "samples": raw_starts,
            "win_rate": round(win_rate, 2),
            "top2_rate": round(top2_rate, 2),
            "relative_strength": round(relative, 3),
        })
    return sorted(ranked, key=lambda row: row["relative_strength"], reverse=True)


def apply_profile(boat: dict, jcd: str | None = None) -> dict:
    """Attach learned tendencies while keeping live/official inputs dominant."""
    profile = profile_for(boat.get("racer_id"))
    if not profile:
        boat["racer_profile_samples"] = 0
        return boat

    course = int(boat.get("predicted_course") or boat.get("course") or boat.get("lane") or 0)
    course_row = (profile.get("courses") or {}).get(str(course), {})
    raw_starts = int(course_row.get("starts") or 0)
    starts, wins, top2 = _weighted_counts(course_row)

    # Historical course form only fills fields that live parsing does not have.
    # It is strongly shrunk and needs actual samples before it can affect score.
    if course in COURSE_PRIORS and raw_starts >= 3:
        prior = COURSE_PRIORS[course]
        if boat.get("course_win_rate") is None:
            boat["course_win_rate"] = round(_smoothed_rate(wins, starts, prior["win"]), 2)
        if boat.get("course_top2_rate") is None:
            boat["course_top2_rate"] = round(_smoothed_rate(top2, starts, prior["top2"]), 2)

    # Current official average ST is preferred. Historical ST is fallback only.
    if boat.get("avg_st") is None and profile.get("avg_st") is not None:
        boat["avg_st"] = profile.get("avg_st")

    venue_row = (profile.get("venues") or {}).get(str(jcd or "").zfill(2), {})
    best_courses = _relative_course_strength(profile)
    course_methods = (profile.get("course_win_methods") or {}).get(str(course), {})

    boat["racer_profile_samples"] = int(profile.get("starts") or 0)
    boat["racer_profile_course_samples"] = raw_starts
    boat["racer_profile_venue_samples"] = int(venue_row.get("starts") or 0)
    boat["racer_profile_win_methods"] = dict(profile.get("win_methods") or {})
    boat["racer_profile_course_win_methods"] = dict(course_methods)
    boat["racer_profile_avg_st"] = profile.get("avg_st")
    boat["racer_profile_best_courses"] = best_courses[:3]
    boat["racer_profile_years"] = dict(profile.get("years") or {})
    return boat
