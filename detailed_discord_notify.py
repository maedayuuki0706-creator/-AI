"""Discord entry point for Boat AI Navi.

The existing near-deadline notifier remains the stable core. This wrapper now
also sends one all-race morning briefing per day and appends odds-aware virtual
betting allocations to the normal race messages.
"""
import sys

import direct_discord_notify as base
import morning_all_races_discord as morning
from virtual_betting import allocate_virtual_bets, compact_virtual_text


_ORIGINAL_ANALYSIS_MESSAGE = base.make_analysis_message
_ORIGINAL_LOG_PREDICTION = base.log_prediction
_VIRTUAL = {}


def analysis_message_with_virtual(day, jcd, rno, deadline, phase, analysis, rows, required):
    message = _ORIGINAL_ANALYSIS_MESSAGE(day, jcd, rno, deadline, phase, analysis, rows, required)
    allocation = allocate_virtual_bets(rows)
    _VIRTUAL[(day, jcd, int(rno), phase)] = allocation
    extra = "\n\n**仮想投票（1口=100円）**\n" + compact_virtual_text(allocation)
    extra += "\n日次集計は締切前の最新配信で差替え（追加投票なし）。"

    # Discord webhooks cap a normal content message at 2,000 characters.
    # Prefer retaining the data-rich prediction and use a compact allocation
    # line if the full version would cross the safe margin.
    if len(message) + len(extra) > 1950:
        lines = message.splitlines()
        if lines and lines[-1].startswith("http"):
            message = "\n".join(lines[:-1])
    if len((message + extra).encode('utf-16-le')) // 2 > 1950:
        # Keep exact formations and stakes; trim the input table if necessary.
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
    _ORIGINAL_LOG_PREDICTION(record)


def main():
    base.make_analysis_message = analysis_message_with_virtual
    base.log_prediction = log_prediction_with_virtual
    # Finish time-sensitive updates before retrying the remaining full card.
    result = base.main()
    if "--test" not in sys.argv and "--dry-run" not in sys.argv:
        morning.run_once()
    return result


if __name__ == "__main__":
    sys.exit(main())
