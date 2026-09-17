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
import bridge_learning
import hit_alerts
import hit_alerts_fast
import mid_value_selection
import opportunity_alerts
import opportunity_character
import opportunity_scenario_commentary
import selection_scoring
import sokuhou_character
import stake_tracking
import water_affinity

bridge_learning.install(app)
# Install before selection scoring so same-day venue form can be logged and may
# add only a tiny confidence bonus after a race already clears the 75 border.
water_affinity.install(app)
selection_scoring.install(app)
stake_tracking.install(app)
opportunity_scenario_commentary.install(opportunity_alerts)
opportunity_character.install(opportunity_alerts)
# Middle-odds selection stays evidence-first: market price can widen the usable
# range, but odds splitting/favourite rank never creates a bet by itself.
mid_value_selection.install(opportunity_alerts)
opportunity_alerts.install(app)
sokuhou_character.install(hit_alerts)

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
_LIVE_DISCOVER_VENUES = app.base.discover_venues
_FULL_ANALYZE_OFFICIAL = app.base.analyze_official


def race_hours():
    return 8 <= datetime.now(app.base.JST).hour <= 23


def _jsonl_rows(path: Path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def sticky_discover_venues(day: str) -> list[str]:
    """Never forget a venue already seen today if live discovery briefly drops it."""
    found = set()
    try:
        found.update(_LIVE_DISCOVER_VENUES(day))
    except Exception as exc:
        print(f'Live venue discovery failed: {type(exc).__name__}', flush=True)

    for row in _jsonl_rows(LOG_PATH):
        if str(row.get("day") or "") == day:
            jcd = str(row.get("jcd") or "").zfill(2)
            if jcd in VENUES:
                found.add(jcd)

    notice_path = Path("data/race_status_log.jsonl")
    for row in _jsonl_rows(notice_path):
        if str(row.get("day") or "") == day:
            jcd = str(row.get("jcd") or "").zfill(2)
            if jcd in VENUES:
                found.add(jcd)

    # Omura is a midnight venue today. If the official index is transiently stale,
    # explicitly keep 24 in the live set whenever its same-day racelist exists.
    try:
        if app.base.deadlines(day, "24"):
            found.add("24")
    except Exception:
        pass
    return sorted(found)


def fast_live_analysis(day: str, jcd: str, rno: int):
    """Avoid expensive odds/form work while a final race is still exhibition-waiting."""
    try:
        racelist_raw = app.base.fetch(app.base.official_url("racelist", day, jcd, rno))
        if app.base.withdrawal_lanes(racelist_raw):
            return _FULL_ANALYZE_OFFICIAL(day, jcd, rno)
        boats = app.base.parse_racelist_boats(day, jcd, rno)
        if len(boats) != 6:
            return _FULL_ANALYZE_OFFICIAL(day, jcd, rno)
        preview = app.base.parse_beforeinfo(app.base.fetch(app.base.official_url("beforeinfo", day, jcd, rno)))
        if preview.get("exhibition_count", 0) < 6:
            for boat in boats:
                boat.update(preview.get("boats", {}).get(boat["lane"], {}))
            return {"inputs": boats, "preview": preview, "delivery_wait_reasons": []}
    except Exception:
        return _FULL_ANALYZE_OFFICIAL(day, jcd, rno)
    return _FULL_ANALYZE_OFFICIAL(day, jcd, rno)


def final_only_due_phase(policy, now, jcd, deadline, delivered, rno):
    day=now.strftime('%Y%m%d')
    lead=app.base.minutes_until(now,deadline)
    if lead<policy['final_min_lead_minutes']:
        return None
    if lead<=policy['final_max_lead_minutes']:
        return None if (day,jcd,rno,'final') in delivered else 'final'
    return None


def all_current_venues_required(policy, day, jcd):
    return True


app.base.discover_venues = sticky_discover_venues
app.base.analyze_official = fast_live_analysis
app.base.due_phase = final_only_due_phase
app.base.required_venue = all_current_venues_required
app.morning.run_once = lambda: 0


def run_channel_smoke_test_once() -> bool:
    if os.getenv("GITHUB_EVENT_NAME") != "push" or SMOKE_MARKER.exists():
        return False
    channel_smoke_test.main()
    SMOKE_MARKER.parent.mkdir(parents=True, exist_ok=True)
    SMOKE_MARKER.write_text(json.dumps({"sent_at": datetime.now(app.base.JST).isoformat(), "selected": True, "hit": True}, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def run_opportunity_smoke_test_once() -> bool:
    if os.getenv("GITHUB_EVENT_NAME") != "push" or OPPORTUNITY_SMOKE_MARKER.exists():
        return False
    try:
        opportunity_alerts.smoke_test()
    except Exception as exc:
        print(f'Opportunity channel smoke test failed: {type(exc).__name__}', flush=True)
        return False
    OPPORTUNITY_SMOKE_MARKER.parent.mkdir(parents=True, exist_ok=True)
    OPPORTUNITY_SMOKE_MARKER.write_text(json.dumps({"sent_at": datetime.now(app.base.JST).isoformat(), "mid_odds": True, "longshot": True}, ensure_ascii=False) + "\n", encoding="utf-8")
    print('Opportunity channel smoke test sent', flush=True)
    return True


def run(watch_seconds=0, *, attempt=app.main, clock=time.monotonic, pause=time.sleep, is_open=race_hours):
    duration = max(0, min(int(watch_seconds), 1080))
    end = clock() + duration
    result = 0
    while is_open():
        try:
            result = attempt()
        except Exception as exc:
            print(f'Notification pass failed: {type(exc).__name__}', flush=True)
            result = 1
        try:
            hit_alerts_fast.check_and_send()
        except Exception as exc:
            print(f'Hit alert pass failed: {type(exc).__name__}', flush=True)
        remaining = end - clock()
        if duration == 0 or remaining <= 0:
            break
        # Recheck every 30 seconds. This is important for midnight races where
        # complete exhibition data can appear only a few minutes before deadline.
        pause(min(30, max(1, remaining)))
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
