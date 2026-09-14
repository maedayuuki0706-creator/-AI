"""Record send-time trifecta odds and an exact 3,000-yen allocation plan.

This module is installed around the notifier at runtime. It does not change the
published picks. Every disclosed pick stays alive with at least 100 yen, then
remaining 100-yen units are assigned to the combination with the lowest current
gross return so the payout is spread as evenly as possible.
"""
from __future__ import annotations

BUDGET_YEN = 3000
UNIT_YEN = 100
TOTAL_UNITS = BUDGET_YEN // UNIT_YEN


def disclosed_picks(record):
    values = []
    for key in ("main", "cover", "outsiders", "all_picks"):
        for combo in record.get(key) or []:
            if combo and combo not in values:
                values.append(combo)
    return values


def clean_pick_odds(picks, odds):
    out = {}
    for combo in picks:
        try:
            value = float((odds or {}).get(combo))
        except (TypeError, ValueError):
            continue
        if value > 0:
            out[combo] = value
    return out


def allocate_3000(picks, odds):
    """Return units, mode and projected minimum gross return at snapshot odds."""
    picks = list(dict.fromkeys(picks))
    if not picks:
        return {}, "none", None
    if len(picks) > TOTAL_UNITS:
        raise ValueError(f"Too many picks for {BUDGET_YEN} yen budget: {len(picks)}")

    units = {combo: 1 for combo in picks}
    remaining = TOTAL_UNITS - len(picks)
    complete = all(combo in odds and odds[combo] > 0 for combo in picks)

    if complete:
        for _ in range(remaining):
            target = min(
                picks,
                key=lambda combo: (units[combo] * odds[combo], odds[combo], combo),
            )
            units[target] += 1
        minimum = min(units[combo] * odds[combo] * UNIT_YEN for combo in picks)
        return units, "send_time_odds_dutch", round(minimum)

    # Missing odds should never be invented. Keep every point alive and spread
    # the remaining units evenly so the record remains reproducible.
    for i in range(remaining):
        units[picks[i % len(picks)]] += 1
    return units, "equal_fallback_missing_send_odds", None


def _snapshot_odds(app, record, picks):
    """Use the same cached BOAT RACE odds page used to build the prediction."""
    try:
        day = str(record["day"])
        jcd = str(record["jcd"]).zfill(2)
        rno = int(record["rno"])
        raw = app.base.fetch(app.base.official_url("odds3t", day, jcd, rno))
        return clean_pick_odds(picks, app.base.parse_odds(raw))
    except Exception:
        return {}


def install(app):
    """Attach odds/allocation recording without changing prediction selection."""
    original_log = app.log_prediction_with_virtual

    def tracked_log(record):
        record = dict(record)
        picks = disclosed_picks(record)
        odds = _snapshot_odds(app, record, picks)
        units, mode, minimum = allocate_3000(picks, odds)

        record["send_odds"] = odds
        record["send_odds_point_count"] = len(odds)
        record["send_odds_complete"] = bool(picks) and len(odds) == len(picks)
        record["send_odds_source"] = "boatrace_odds3t_cached_prediction_snapshot"
        record["stake_3000_units"] = units
        record["stake_3000_yen"] = {combo: count * UNIT_YEN for combo, count in units.items()}
        record["stake_3000_total_yen"] = sum(units.values()) * UNIT_YEN
        record["stake_3000_allocation_mode"] = mode
        record["stake_3000_min_projected_return_yen"] = minimum
        record["stake_3000_torigami_risk_at_send"] = minimum is not None and minimum < BUDGET_YEN
        record["stake_3000_version"] = "send-odds-dutch-v1"
        return original_log(record)

    app.log_prediction_with_virtual = tracked_log
