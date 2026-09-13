"""Discord entry point for Boat AI Navi.

The existing near-deadline notifier remains the stable core. This wrapper now
also sends one all-race morning briefing per day and appends odds-aware virtual
betting allocations to the normal race messages.

Live prediction cards use a variable 6-14 point width. The original six picks
remain the core; extra points are used mainly to widen second/third-place ties
so near-miss races caused by a missing supporting boat are covered more often.
"""
import sys

import direct_discord_notify as base
import morning_all_races_discord as morning
from virtual_betting import allocate_virtual_bets, compact_virtual_text


_ORIGINAL_ANALYSIS_MESSAGE = base.make_analysis_message
_ORIGINAL_LOG_PREDICTION = base.log_prediction
_ORIGINAL_DISPLAYED_PICKS = base.displayed_picks
_VIRTUAL = {}


def _position_gap(analysis, position):
    """Return the gap between the two most likely boats at one finish position."""
    totals = {lane: 0.0 for lane in range(1, 7)}
    for row in analysis.get("trifecta", []):
        try:
            lane = int(row["combination"].split("-")[position])
            totals[lane] += float(row.get("probability") or 0.0)
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    ranked = sorted(totals.values(), reverse=True)
    return (ranked[0] - ranked[1]) if len(ranked) >= 2 else 1.0


def _target_point_count(analysis):
    """Choose 6-14 points, expanding when the predicted order is less certain."""
    grade = analysis.get("grade")
    head_gap = _position_gap(analysis, 0)
    second_gap = _position_gap(analysis, 1)
    third_gap = _position_gap(analysis, 2)

    # Start compact for strong races, then add points where the supporting
    # positions are close. This is intentionally aimed at the day's common
    # failure mode: correct head / near-correct pair with one missing tie boat.
    target = 6 if grade == "A" else 8 if grade == "B" else 10
    if head_gap < 0.10:
        target += 2
    if second_gap < 0.08:
        target += 2
    if third_gap < 0.07:
        target += 2
    return max(6, min(14, target))


def displayed_picks_variable(analysis, required):
    """Keep the original six as the core and widen ties up to 14 points."""
    core = list(_ORIGINAL_DISPLAYED_PICKS(analysis, required))
    if not required or len(core) < 6:
        return core

    target = _target_point_count(analysis)
    if target <= len(core):
        return core[:target]

    selected = list(core)
    seen = {row.get("combination") for row in selected}
    rows = analysis.get("trifecta", [])

    # Expand the likely winner side first, so extra points mostly widen the
    # second/third-place ties instead of spraying many unrelated winners.
    ranked_heads = sorted(
        (analysis.get("heads") or {}).items(),
        key=lambda item: item[1],
        reverse=True,
    )
    core_heads = {str(item[0]) for item in ranked_heads[:2]}

    for row in rows:
        combo = row.get("combination")
        if not combo or combo in seen:
            continue
        if combo.split("-")[0] not in core_heads:
            continue
        selected.append(row)
        seen.add(combo)
        if len(selected) >= target:
            return selected

    # If the race is genuinely wide-open, fill the remainder by model
    # probability rather than forcing all extra points under the same heads.
    for row in rows:
        combo = row.get("combination")
        if not combo or combo in seen:
            continue
        selected.append(row)
        seen.add(combo)
        if len(selected) >= target:
            break
    return selected


def analysis_message_with_virtual(day, jcd, rno, deadline, phase, analysis, rows, required):
    message = _ORIGINAL_ANALYSIS_MESSAGE(day, jcd, rno, deadline, phase, analysis, rows, required)

    # Widening the prediction card must not automatically widen the money at
    # risk. Preserve the previous virtual-bet behavior by evaluating only the
    # original six core picks; extra 7-14th points are prediction coverage.
    allocation = allocate_virtual_bets(rows[:6])
    _VIRTUAL[(day, jcd, int(rno), phase)] = allocation
    extra = "\n\n**仮想投票（1口=100円）**\n" + compact_virtual_text(allocation)
    extra += "\n日次集計は締切前の最新配信で差替え（追加投票なし）。"

    # Discord webhooks cap a normal content message at 2,000 characters.
    # Prefer retaining the exact formation and stakes over the long input table.
    if len(message) + len(extra) > 1950:
        lines = message.splitlines()
        if lines and lines[-1].startswith("http"):
            message = "\n".join(lines[:-1])
    if len((message + extra).encode('utf-16-le')) // 2 > 1950:
        start = message.find('**判断材料（6艇）**')
        end = message.find('風速 ', start)
        if start >= 0 and end > start:
            message = message[:start] + message[end:]
    if len((message + extra).encode('utf-16-le')) // 2 > 2000:
        raise ValueError('Prediction and exact allocation exceed Discord limit')
    return message + extra


def log_prediction_with_virtual(record):
    key = (record.get("day"), str(record.get("jcd")), int(record.get("rno", 0)), record.get("phase", "final"))
    allocation = _VIRTUAL.get(key)
    if allocation is not None:
        record = dict(record)
        record["virtual_bets"] = allocation.get("bets", [])
        record["virtual_total_units"] = allocation.get("total_units", 0)
        record["virtual_min_return_units"] = allocation.get("min_return_units")
        record["virtual_status"] = allocation.get("status")
        record["virtual_unit_yen"] = 100
        record["virtual_selection_rule"] = "latest_pre_deadline_per_race"
        record["prediction_point_policy"] = "variable_6_to_14_tie_expansion"
    _ORIGINAL_LOG_PREDICTION(record)


def main():
    base.displayed_picks = displayed_picks_variable
    base.make_analysis_message = analysis_message_with_virtual
    base.log_prediction = log_prediction_with_virtual
    # Finish time-sensitive updates before retrying the remaining full card.
    result = base.main()
    if "--test" not in sys.argv and "--dry-run" not in sys.argv:
        morning.run_once()
    return result


if __name__ == "__main__":
    sys.exit(main())
