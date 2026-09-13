"""Recheck during a scheduled job so late exhibitions need not wait for cron."""
from datetime import datetime
import os
import time

import detailed_discord_notify as app


def race_hours():
    return 8 <= datetime.now(app.base.JST).hour < 22


def run(watch_seconds=0, *, attempt=app.main, clock=time.monotonic, pause=time.sleep, is_open=race_hours):
    end = clock() + max(0, min(int(watch_seconds), 600))
    result = 0
    while is_open():
        try:
            result = attempt()
        except Exception as exc:
            print(f'Notification pass failed: {type(exc).__name__}', flush=True)
            result = 1
        # Reserve time for one full official-data collection and persistence.
        if end - clock() < 210:
            break
        pause(60)
    return result


if __name__ == '__main__':
    raise SystemExit(run(os.getenv('NOTIFY_WATCH_SECONDS', '0')))
