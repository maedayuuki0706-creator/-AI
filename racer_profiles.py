"""Persistent racer profile features for BOAT RACE predictions."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

PROFILE_PATH = Path("data/racer_profiles.json")

# Conservative prior percentages used only to shrink small samples.
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


def _smoothed_rate(successes: int, starts: int, prior_pct: float, prior_n: int = 12) -> float:
    if starts <= 0:
        return float(prior_pct)
    return 100.0 * (successes + prior_n * prior_pct / 100.0) / (starts + prior_n)


def profile_for(racer_id: object) -> dict | None:
    rid = str(racer_id or "")
    return (load_profiles().get("racers") or {}).get(rid)


def apply_profile(boat: dict, jcd: str | None = None) -> dict:
    """Attach stable learned racer tendencies without overpowering live data."""
    profile = profile_for(boat.get("racer_id"))
    if not profile:
        boat["racer_profile_samples"] = 0
        return boat

    course = int(boat.get("predicted_course") or boat.get("course") or boat.get("lane") or 0)
    course_row = (profile.get("courses") or {}).get(str(course), {})
    starts = int(course_row.get("starts") or 0)
    wins = int(course_row.get("wins") or 0)
    top2 = int(course_row.get("top2") or 0)

    # Learned course form is used only with some actual history and always
    # shrunk strongly toward a conservative course prior.
    if course in COURSE_PRIORS and starts >= 3:
        prior = COURSE_PRIORS[course]
        if boat.get("course_win_rate") is None:
            boat["course_win_rate"] = round(_smoothed_rate(wins, starts, prior["win"]), 2)
        if boat.get("course_top2_rate") is None:
            boat["course_top2_rate"] = round(_smoothed_rate(top2, starts, prior["top2"]), 2)

    venue_row = (profile.get("venues") or {}).get(str(jcd or "").zfill(2), {})
    boat["racer_profile_samples"] = int(profile.get("starts") or 0)
    boat["racer_profile_course_samples"] = starts
    boat["racer_profile_venue_samples"] = int(venue_row.get("starts") or 0)
    boat["racer_profile_win_methods"] = dict(profile.get("win_methods") or {})
    boat["racer_profile_avg_st"] = profile.get("avg_st")
    return boat
