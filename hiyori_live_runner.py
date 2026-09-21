"""Independent Biyori-enriched prediction delivery."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
import time
import direct_discord_notify as base
import detailed_discord_notify as cards
import hiyori_parallel as stream

def schedule(args):
    day, jcd = args
    try:
        return jcd, base.deadlines(day, jcd)
    except Exception as exc:
        print(f'Hiyori schedule {jcd}: {type(exc).__name__}', flush=True)
        return jcd, []

def deliver(args):
    day, jcd, rno, deadline = args
    key = stream.key_for(day, jcd, rno)
    if (stream.ROOT/'deliveries'/f'{key}.json').exists():
        return
    state = stream.ROOT/'status'/f'{key}.json'
    if state.exists() and stream.read(state).get('state') == 'delivery_unconfirmed':
        return
    try:
        official = base.analyze_official(day, jcd, rno)
        if not official or official.get('preview', {}).get('exhibition_count', 0) < 6:
            stream.status(key, 'waiting_for_exhibition')
            return
        request = dict(day=day, jcd=jcd, rno=rno, deadline=deadline,
                       captured_at=datetime.now(base.JST).isoformat(), official=official,
                       baseline_rows=cards.displayed_picks_variable(official, True))
        stream.save(stream.ROOT/'requests'/f'{key}.json', request)
        stream.process(request)
    except Exception as exc:
        stream.status(key, 'analysis_error', error_type=type(exc).__name__)
        print(f'Hiyori analysis {key}: {type(exc).__name__}', flush=True)

def main():
    if not os.getenv('HIYORI_DISCORD_WEBHOOK_URL'):
        raise RuntimeError('HIYORI_DISCORD_WEBHOOK_URL is not configured')
    now = datetime.now(base.JST)
    if not 8 <= now.hour <= 23:
        return
    day = now.strftime('%Y%m%d')
    with ThreadPoolExecutor(max_workers=8) as pool:
        schedules = dict(pool.map(schedule, [(day, j) for j in base.discover_venues(day)]))
    end = time.monotonic() + 180
    while True:
        now = datetime.now(base.JST)
        due = [(day,j,n,d) for j,times in schedules.items() for n,d in enumerate(times,1)
               if 2 <= base.minutes_until(now,d) <= 18]
        print(f'Hiyori eligible races: {len(due)}', flush=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(deliver,due))
        if time.monotonic() >= end:
            break
        time.sleep(20)
    stream.settle_available()

if __name__ == '__main__':
    main()
