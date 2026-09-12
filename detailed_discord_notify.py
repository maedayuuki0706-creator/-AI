"""Detailed Discord notifier wrapper.

Keeps the stable delivery runner intact while enriching independent-AI messages
with model probabilities and source data.
"""
import sys

import direct_discord_notify as base
from discord_detail_formatter import format_detailed_message
from prediction_engine import analyze_race

_ANALYSIS = {}


def detailed_engine_picks(day, jcd, rno):
    boats = base.parse_racelist_boats(day, jcd, rno)
    if len(boats) != 6:
        _ANALYSIS[(jcd, rno)] = (None, [])
        return [], None
    result = analyze_race({
        "race": {"venue": base.VENUES.get(jcd, jcd), "boats": boats},
        "boats": boats,
    })
    _ANALYSIS[(jcd, rno)] = (result, boats)
    picks = [row["combination"] for row in result.get("trifecta", [])[:8]]
    return picks, result.get("confidence")


def detailed_message(jcd, rno, deadline, picks, exhibition, source, confidence):
    result, boats = _ANALYSIS.get((jcd, rno), (None, []))
    if source != "独自AI":
        result, boats = None, []
    return format_detailed_message(
        base.VENUES.get(jcd, jcd), rno, deadline, picks, exhibition,
        source, confidence, result, boats,
    )


base.engine_picks = detailed_engine_picks
base.make_message = detailed_message

if __name__ == "__main__":
    sys.exit(base.main())
