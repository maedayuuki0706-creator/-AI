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

    # Discord webhooks cap a normal content message at 2,000 characters.
    # Prefer retaining the data-rich prediction and use a compact allocation
    # line if the full version would cross the safe margin.
    if len(message) + len(extra) > 1950:
        lines = message.splitlines()
        if lines and lines[-1].startswith("http"):
            message = "\n".join(lines[:-1])
    if len(message) + len(extra) > 1950:
        if allocation.get("status") == "bet":
            extra = (
                f"\n\n仮想投票：計{allocation['total_units']}口 / "
                f"最低払戻{allocation['min_return_units']:.1f}口相当"
            )
        else:
            extra = "\n\n仮想投票：見送り 0口"
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
    _ORIGINAL_LOG_PREDICTION(record)


base.make_analysis_message = analysis_message_with_virtual
base.log_prediction = log_prediction_with_virtual


def main():
    # Test/dry-run modes should behave exactly like the underlying notifier.
    if "--test" not in sys.argv and "--dry-run" not in sys.argv:
        sent = morning.run_once()
        # If the morning batch used this scheduled run, leave the next 5-minute
        # run to the near-deadline notifier so one Actions job stays short.
        if sent > 0:
            return 0
    return base.main()


if __name__ == "__main__":
    sys.exit(main())
