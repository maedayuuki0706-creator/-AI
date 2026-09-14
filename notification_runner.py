"""Recheck scheduled notifications, or resend today's prediction log grouped by venue."""
from datetime import datetime
import json
import os
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

import detailed_discord_notify as app
import notification_audit as audit
from persist_notification_state import checkpoint

VENUES = {
    "01":"桐生","02":"戸田","03":"江戸川","04":"平和島","05":"多摩川","06":"浜名湖",
    "07":"蒲郡","08":"常滑","09":"津","10":"三国","11":"びわこ","12":"住之江",
    "13":"尼崎","14":"鳴門","15":"丸亀","16":"児島","17":"宮島","18":"徳山",
    "19":"下関","20":"若松","21":"芦屋","22":"福岡","23":"唐津","24":"大村",
}
LOG_PATH = Path("data/prediction_log.jsonl")


def race_hours():
    return 8 <= datetime.now(app.base.JST).hour < 22


def run(watch_seconds=0, *, attempt=app.main, clock=time.monotonic, pause=time.sleep, is_open=race_hours):
    end = clock() + max(0, min(int(watch_seconds), 1800))
    result = 0
    while is_open():
        try:
            result = max(result, int(attempt() or 0))
        except Exception as exc:
            print(f'Notification pass failed: {type(exc).__name__}', flush=True)
            audit.emit('analysis_failed',stage='runner',error_type=type(exc).__name__)
            result = 1
        try:
            checkpoint(required=True)
        except Exception:
            result = 1
        if end - clock() < 180:
            break
        pause(30)
    return result


def resend_prediction_summary(day: str = "20260913") -> int:
    from prediction_recap import main
    return main(day)


if __name__ == '__main__':
    if os.getenv("SUMMARY_ONLY") == "1":
        raise SystemExit(resend_prediction_summary(os.getenv("SUMMARY_DAY", "20260913")))
    raise SystemExit(run(os.getenv('NOTIFY_WATCH_SECONDS', '0')))
