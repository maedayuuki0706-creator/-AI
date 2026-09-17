"""Notification entry point with missed-race delivery guard enabled."""
from __future__ import annotations

import os
import sys

import delivery_guard
import notification_runner as runner


delivery_guard.install(
    runner.app,
    runner.opportunity_alerts,
    runner._FULL_ANALYZE_OFFICIAL,
)


def run_continuous(total_seconds: int) -> int:
    """Keep the existing tested 18-minute runner chunks, but bridge longer gaps."""
    total = max(0, int(total_seconds))
    if total == 0:
        return runner.run(0)

    result = 0
    remaining = total
    while remaining > 0 and runner.race_hours():
        chunk = min(1080, remaining)
        result = max(result, int(runner.run(chunk) or 0))
        remaining -= chunk
    return result


def main() -> int:
    runner.run_channel_smoke_test_once()
    runner.run_opportunity_smoke_test_once()
    if os.getenv("SUMMARY_ONLY") == "1":
        return runner.resend_prediction_summary(os.getenv("SUMMARY_DAY", "20260913"))
    return run_continuous(int(os.getenv("NOTIFY_WATCH_SECONDS", "0")))


if __name__ == "__main__":
    sys.exit(main())
