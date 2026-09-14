"""Recheck scheduled notifications, or resend today's prediction log grouped by venue."""
from datetime import datetime
import json
import os
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

if os.getenv("SELECTED_DISCORD_WEBHOOK_URL") and not os.getenv("DISCORD_SELECTED_WEBHOOK_URL"):
    os.environ["DISCORD_SELECTED_WEBHOOK_URL"] = os.environ["SELECTED_DISCORD_WEBHOOK_URL"]

import channel_smoke_test
import detailed_discord_notify as app
import hit_alerts
import selection_scoring
import stake_tracking

selection_scoring.install(app)
stake_tracking.install(app)

VENUES = {
    "01":"桐生","02":"戸田","03":"江戸川","04":"平和島","05":"多摩川","06":"浜名湖",
    "07":"蒲郡","08":"常滑","09":"津","10":"三国","11":"びわこ","12":"住之江",
    "13":"尼崎","14":"鳴門","15":"丸亀","16":"児島","17":"宮島","18":"徳山",
    "19":"下関","20":"若松","21":"芦屋","22":"福岡","23":"唐津","24":"大村",
}
LOG_PATH = Path("data/prediction_log.jsonl")
SMOKE_MARKER = Path("data/channel_smoke_test_20260915.json")


def race_hours():
    return 8 <= datetime.now(app.base.JST).hour < 22


def run_channel_smoke_test_once() -> bool:
    """Run only on this push and journal success so normal schedules stay silent."""
    if os.getenv("GITHUB_EVENT_NAME") != "push" or SMOKE_MARKER.exists():
        return False
    channel_smoke_test.main()
    SMOKE_MARKER.parent.mkdir(parents=True, exist_ok=True)
    SMOKE_MARKER.write_text(
        json.dumps({"sent_at": datetime.now(app.base.JST).isoformat(), "selected": True, "hit": True}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return True


def run(watch_seconds=0, *, attempt=app.main, clock=time.monotonic, pause=time.sleep, is_open=race_hours):
    end = clock() + max(0, min(int(watch_seconds), 600))
    result = 0
    while is_open():
        try:
            result = attempt()
        except Exception as exc:
            print(f'Notification pass failed: {type(exc).__name__}', flush=True)
            result = 1
        try:
            hit_alerts.check_and_send()
        except Exception as exc:
            print(f'Hit alert pass failed: {type(exc).__name__}', flush=True)
        if end - clock() < 210:
            break
        pause(60)
    return result


def resend_prediction_summary(day: str = "20260913") -> int:
    from prediction_recap import main
    return main(day)


if __name__ == '__main__':
    run_channel_smoke_test_once()
    if os.getenv("SUMMARY_ONLY") == "1":
        raise SystemExit(resend_prediction_summary(os.getenv("SUMMARY_DAY", "20260913")))
    raise SystemExit(run(os.getenv('NOTIFY_WATCH_SECONDS', '0')))
