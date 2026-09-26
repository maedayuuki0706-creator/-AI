"""Continuously collect and settle the five-way prospective shadow experiment."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
import os
import time
import urllib.request

import direct_discord_notify as base
import daily_report
import hiyori_model
import hiyori_source
import four_way_prototype as trial


def now_jst():
    return datetime.now(trial.JST)


def status(day, jcd, rno, state, **details):
    key = trial.identity(day, jcd, rno)
    trial.write_json(trial.ROOT/day/'status'/f'{key}.json',
                     {'key': key, 'state': state, 'updated_at': now_jst().isoformat(), **details})


def _delivery_path(record, stream):
    return trial.ROOT/record['day']/'deliveries'/stream/f"{record['key']}.json"


def _prototype_message(record, stream):
    model = record['models'][stream]
    if stream == 'prototype3':
        main = ' / '.join(model.get('main_picks') or [])
        cover = ' / '.join(model.get('cover_picks') or [])
        return (
            f"🏆 **新人予想家 ゆうき｜日和本線＋中穴抑え**\n"
            f"🏁 **{record['venue']} {record['rno']}R**｜締切 {record['deadline']}\n"
            f"🎯 **本線・日和（{len(model.get('main_picks') or [])}点）**\n"
            f"`{main}`\n"
            f"🔥 **抑え・中穴くん＋日和（{len(model.get('cover_picks') or [])}点）**\n"
            f"`{cover or 'なし'}`\n"
            f"📊 計{model['point_count']}点｜Grade {model['grade']}｜本番配信"
        )
    weight = model['weights']
    picks = ' / '.join(model['picks'])
    title = 'プロトタイプ1｜既存AI優先' if stream == 'prototype1' else 'プロトタイプ2｜日和AI優先'
    return (
        f"🧪 **{title}**\n"
        f"🏁 **{record['venue']} {record['rno']}R**｜締切 {record['deadline']}\n"
        f"⚖️ 既存 {int(weight['existing']*100)}% / 日和 {int(weight['hiyori']*100)}%\n"
        f"🎯 **買い目 {model['point_count']}点**\n"
        f"`{picks}`\n"
        f"📊 Grade {model['grade']}｜比較テスト配信"
    )


def _post_webhook(url, payload):
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(
        url, data=body,
        headers={'Content-Type': 'application/json', 'User-Agent': base.UA},
        method='POST')
    with urllib.request.urlopen(request, timeout=10) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f'Discord HTTP {response.status}')


def deliver_prototypes(record, now=None):
    """Deliver prototype 1/2/3 exactly once, retrying only unconfirmed streams."""
    if os.getenv("PROTOTYPE_DELIVERY_DISABLED", "").strip() == "1":
        return
    now = now or now_jst()
    start_day = os.getenv('PROTOTYPE_DELIVERY_START_DAY', '').strip()
    if start_day and record['day'] < start_day:
        return
    # Predictions are useful only before the race. Do not create late Discord noise.
    if not trial.before_deadline(record['day'], record['deadline'], now):
        return
    mapping = {
        'prototype1': ('PROTO1_DISCORD_WEBHOOK_URL', 'プロトタイプ1'),
        'prototype2': ('PROTO2_DISCORD_WEBHOOK_URL', 'プロトタイプ2'),
        'prototype3': ('PT3_DISCORD_WEBHOOK_URL', '新人予想家 ゆうき'),
    }
    for stream, (env_name, username) in mapping.items():
        receipt = _delivery_path(record, stream)
        if receipt.exists():
            continue
        url = os.getenv(env_name, '').strip()
        if stream == 'prototype3' and not url:
            # Promotion compatibility: keep delivery alive until the new
            # production channel webhook is configured on Render.
            url = os.getenv('PROTO3_DISCORD_WEBHOOK_URL', '').strip()
        if not url:
            raise RuntimeError(f'{env_name} is not configured')
        try:
            _post_webhook(url, {'username': username, 'content': _prototype_message(record, stream)})
            trial.write_json(receipt, {
                'key': record['key'], 'stream': stream, 'delivered_at': now_jst().isoformat(),
                'prediction_digest': record['digest'],
            })
            print(f"prototype delivery confirmed {record['key']} {stream}", flush=True)
        except Exception as exc:
            print(f"prototype delivery pending {record['key']} {stream}: {type(exc).__name__}", flush=True)


def deliver_pending(day, now=None):
    """Retry any recorded race whose Discord receipt is still missing."""
    now = now or now_jst()
    root = trial.ROOT/day/'predictions'
    if not root.exists():
        return
    for path in sorted(root.glob('*.json')):
        record = trial.read(path)
        if trial.before_deadline(record['day'], record['deadline'], now):
            deliver_prototypes(record, now)


def collect_race(day, jcd, rno, deadline, clock=now_jst):
    key = trial.identity(day, jcd, rno)
    path = trial.ROOT/day/'predictions'/f'{key}.json'
    if path.exists():
        return 'recorded'
    started = clock()
    if not trial.before_deadline(day, deadline, started):
        status(day, jcd, rno, 'missed_deadline', deadline=deadline)
        return 'missed_deadline'
    try:
        official = base.analyze_official(day, jcd, rno)
        if not official:
            status(day, jcd, rno, 'official_unavailable', deadline=deadline)
            return 'official_unavailable'
        if official.get('preview', {}).get('exhibition_count') != 6:
            status(day, jcd, rno, 'waiting_for_exhibition', deadline=deadline)
            return 'waiting_for_exhibition'
        request = {'day': day, 'jcd': jcd, 'rno': rno, 'deadline': deadline,
                   'captured_at': started.isoformat(), 'official': official}
        source = hiyori_source.fetch_race(day, jcd, rno)
        source['fetched_at'] = clock().isoformat()
        hy = hiyori_model.analyze(official, source, day, jcd, rno)
        finished = clock()
        if not trial.before_deadline(day, deadline, finished):
            status(day, jcd, rno, 'missed_deadline', deadline=deadline)
            return 'missed_deadline'
        bundle = trial.build_bundle(request, hy, source, finished)
        if not trial.before_deadline(day, deadline, clock()):
            status(day, jcd, rno, 'missed_deadline', deadline=deadline)
            return 'missed_deadline'
        trial.persist(bundle, request, source, hy)
        deliver_prototypes(bundle, clock())
        status(day, jcd, rno, 'recorded', deadline=deadline, digest=bundle['digest'])
        print(f'five-way recorded {key}: P1/P2 fixed 10; P3 Hiyori main + mid cover cap16', flush=True)
        return 'recorded'
    except Exception as exc:
        status(day, jcd, rno, 'data_error', deadline=deadline, error_type=type(exc).__name__)
        print(f'four-way pending {key}: {type(exc).__name__}', flush=True)
        return 'data_error'


def get_schedule(day, jcd):
    try:
        times = base.deadlines(day, jcd)
        if not times:
            raise ValueError('No race deadlines')
        return jcd, times, None
    except Exception as exc:
        return jcd, [], type(exc).__name__


def fetch_result(day, jcd, rno):
    request = urllib.request.Request(base.official_url('raceresult', day, jcd, rno),
                                    headers={'User-Agent': base.UA})
    with urllib.request.urlopen(request, timeout=8) as response:
        return daily_report.parse_payout(response.read().decode('utf-8'))


def settle_one(path):
    record = trial.read(path)
    target = path.parent.parent/'results'/path.name
    if target.exists():
        return
    try:
        official = fetch_result(record['day'], record['jcd'], record['rno'])
        result = trial.evaluate(record, official)
        if result is not None:
            import json
            trial.write_once(target, (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode())
            print(f"five-way settled {record['key']} comparable={result['comparable']}", flush=True)
    except Exception as exc:
        print(f"five-way result pending {record['key']}: {type(exc).__name__}", flush=True)


def settle_available(now=None):
    now = now or now_jst()
    # Separate result fetching: one blocked race must not starve the later ones.
    paths = []
    for path in sorted(trial.ROOT.glob('20*/predictions/*.json')):
        record = trial.read(path)
        if (path.parent.parent/'results'/path.name).exists():
            continue
        if now - trial.close_time(record['day'], record['deadline']) >= timedelta(minutes=3):
            paths.append(path)
    # Rotate older pending results across invocations instead of always retrying the first few.
    if paths:
        offset = (int(now.timestamp()) // 60 * 24) % len(paths)
        paths = (paths[offset:] + paths[:offset])[:24]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(settle_one, paths))


def coverage(day, schedules, errors, now, started_at):
    counts = {}
    rows = []
    for jcd, times in sorted(schedules.items()):
        for rno, deadline in enumerate(times, 1):
            key = trial.identity(day, jcd, rno)
            path = trial.ROOT/day/'predictions'/f'{key}.json'
            state_path = trial.ROOT/day/'status'/f'{key}.json'
            if path.exists():
                state = 'recorded'
            elif trial.close_time(day, deadline) <= trial.aware(started_at):
                state = 'closed_before_trial_start'
            elif not trial.before_deadline(day, deadline, now):
                state = 'missed_deadline'
            elif state_path.exists():
                state = trial.read(state_path)['state']
            else:
                state = 'scheduled'
            counts[state] = counts.get(state, 0) + 1
            rows.append({'key': key, 'deadline': deadline, 'state': state})
    result = {'day': day, 'version': trial.VERSION, 'as_of': now.isoformat(),
              'started_at': started_at, 'expected': len(rows),
              'schedule_errors': errors, 'counts': counts, 'races': rows}
    trial.write_json(trial.ROOT/day/'coverage.json', result)
    return result


def run(watch_seconds=0):
    end = time.monotonic() + max(0, watch_seconds)
    # The monotonic clock may start close to zero on a fresh Actions runner.
    # The first pass must still fetch schedules and settle pending results.
    schedules, errors, schedule_at, result_at, active_day = {}, {}, float('-inf'), float('-inf'), None
    touched = set()
    while True:
        now = now_jst()
        day = now.strftime('%Y%m%d')
        if day != active_day:
            schedules, errors, schedule_at = {}, {}, float('-inf')
            active_day = day
        start_path = trial.ROOT/day/'start.json'
        import json
        trial.write_once(start_path, json.dumps({'started_at': now.isoformat()}).encode())
        started_at = trial.read(start_path)['started_at']
        touched.add(day)
        base.fetch.cache_clear()
        if 8 <= now.hour <= 23 and time.monotonic() - schedule_at >= 120:
            try:
                venues = base.discover_venues(day)
                if not venues:
                    raise ValueError('No venues discovered')
                with ThreadPoolExecutor(max_workers=8) as pool:
                    responses = list(pool.map(lambda j: get_schedule(day, j), venues))
                errors = {}
                for jcd, times, error in responses:
                    if error:
                        errors[jcd] = error
                    else:
                        schedules[jcd] = times
            except Exception as exc:
                errors['discovery'] = type(exc).__name__
            schedule_at = time.monotonic()
        now = now_jst()
        due = [(day, jcd, rno, deadline) for jcd, times in schedules.items()
               for rno, deadline in enumerate(times, 1)
               if 1 <= base.minutes_until(now, deadline) <= 18
               and not (trial.ROOT/day/'predictions'/f'{trial.identity(day,jcd,rno)}.json').exists()]
        due.sort(key=lambda item: item[3])
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda args: collect_race(*args), due))
        # A Discord/network hiccup must not turn into a permanent delivery miss.
        deliver_pending(day, now_jst())
        if time.monotonic() - result_at >= 60:
            settle_available()
            result_at = time.monotonic()
        now = now_jst()
        c = coverage(day, schedules, errors, now, started_at)
        report = trial.summarize(day)
        print(f"five-way coverage {c['counts']} pending_results={report['pending']} judged={len(report['cohort'])}", flush=True)
        if time.monotonic() >= end:
            break
        time.sleep(min(20, max(0, end-time.monotonic())))
    # Settlements can include yesterday's races.
    for directory in trial.ROOT.glob('20*'):
        if directory.is_dir() and (directory/'predictions').exists():
            trial.summarize(directory.name)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--watch-seconds', type=int, default=int(os.getenv('PROTOTYPE_WATCH_SECONDS', '0')))
    args = parser.parse_args()
    return run(args.watch_seconds)


if __name__ == '__main__':
    raise SystemExit(main())
