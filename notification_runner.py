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
import opportunity_alerts
import selection_scoring
import stake_tracking

selection_scoring.install(app)
stake_tracking.install(app)
opportunity_alerts.install(app)

# The old 万舟警報 is retired. Longshot ideas now go only through the dedicated
# 穴AI stream, while the normal prediction feed itself stays unchanged.
app._longshot_message = lambda record: None

VENUES = {
    "01":"桐生","02":"戸田","03":"江戸川","04":"平和島","05":"多摩川","06":"浜名湖",
    "07":"蒲郡","08":"常滑","09":"津","10":"三国","11":"びわこ","12":"住之江",
    "13":"尼崎","14":"鳴門","15":"丸亀","16":"児島","17":"宮島","18":"徳山",
    "19":"下関","20":"若松","21":"芦屋","22":"福岡","23":"唐津","24":"大村",
}
LOG_PATH = Path("data/prediction_log.jsonl")
SMOKE_MARKER = Path("data/channel_smoke_test_20260915.json")
OPPORTUNITY_SMOKE_MARKER = Path("data/opportunity_channel_smoke_test_20260916.json")


def race_hours():
    return 8 <= datetime.now(app.base.JST).hour < 22


def final_only_due_phase(policy, now, jcd, deadline, delivered, rno):
    """Only allow the final near-deadline prediction; suppress morning/preliminary cards."""
    day = now.strftime('%Y%m%d')
    lead = app.base.minutes_until(now, deadline)
    if lead < policy['final_min_lead_minutes']:
        return None
    if lead <= policy['final_max_lead_minutes']:
        return None if (day, jcd, rno, 'final') in delivered else 'final'
    return None


# The user only wants the race prediction close to post time. Keep all-race final
# coverage, selected alerts and hit alerts, but silence the morning all-race
# briefing and preliminary prediction phase.
app.base.due_phase = final_only_due_phase
app.morning.run_once = lambda: 0


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


def run_opportunity_smoke_test_once() -> bool:
    """Verify the new 中穴AI and 穴AI webhooks once, without touching normal prediction."""
    if os.getenv("GITHUB_EVENT_NAME") != "push" or OPPORTUNITY_SMOKE_MARKER.exists():
        return False
    try:
        opportunity_alerts.smoke_test()
    except Exception as exc:
        print(f'Opportunity channel smoke test failed: {type(exc).__name__}', flush=True)
        return False
    OPPORTUNITY_SMOKE_MARKER.parent.mkdir(parents=True, exist_ok=True)
    OPPORTUNITY_SMOKE_MARKER.write_text(
        json.dumps({"sent_at": datetime.now(app.base.JST).isoformat(), "mid_odds": True, "longshot": True}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print('Opportunity channel smoke test sent', flush=True)
    return True


def run(watch_seconds=0, *, attempt=app.main, clock=time.monotonic, pause=time.sleep, is_open=race_hours):
    # Scheduled Actions can start late. Keep one serialized watcher alive long
    # enough to make a second final-data pass when the first pass only sees
    # "展示待ち", instead of depending on the next cron launch arriving on time.
    end = clock() + max(0, min(int(watch_seconds), 840))
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
    run_opportunity_smoke_test_once()
    if os.getenv("SUMMARY_ONLY") == "1":
        raise SystemExit(resend_prediction_summary(os.getenv("SUMMARY_DAY", "20260913")))
    raise SystemExit(run(os.getenv('NOTIFY_WATCH_SECONDS', '0')))
