"""Short production pass. Cron is a wake-up signal, never a delivery clock."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from delivery_v2 import receipts
from delivery_v2.integration import ERRORS, adopt_legacy, notify_failure, stalled
from delivery_v2.store import Conflict, default_store
from delivery_v2.watchdog import audit, generate_expected

JST = ZoneInfo('Asia/Tokyo')
SUMMARY = Path('data/delivery_v2_recovery/dispatcher.json')


def jsonl(path, day):
    if not Path(path).exists():
        return []
    rows = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        if row.get('day') == day:
            rows.append(row)
    return rows


def legacy_state(day):
    """Read existing journals without rewriting any prediction or result."""
    import prototype3_delivery as yuuki
    import delivery_guard_runner as main_pipeline
    proof, conditional = {}, []
    for stream, path in [('main', 'data/prediction_log.jsonl'),
                         ('selected', 'data/selected_prediction_deliveries.jsonl'),
                         (None, 'data/opportunity_alert_deliveries.jsonl')]:
        for row in jsonl(path, day):
            if row.get('status') == 'sniper_skip':
                continue
            name = stream or ('mid_odds_selected' if row.get('selected') and row.get('stream') == 'mid_odds' else row.get('stream'))
            if not name:
                continue
            key = receipts.identity(name, day, row['jcd'], row['rno'], row.get('phase') or 'final')
            proof[key] = row
            if name != 'main':
                conditional.append({**row, 'stream': name})
            elif main_pipeline.runner.app._is_selected_record(row):
                conditional.append({**row, 'stream':'selected'})
    for path in (yuuki.ROOT / 'predictions').glob(day+'_*.json'):
        record = yuuki.read(path)
        for stream, receipt in [('yuuki', yuuki.receipt_path(record['key'])),
                                ('yuuki_selected', yuuki.selected_receipt_path(record['key']))]:
            if receipt.exists():
                proof[receipts.identity(stream, day, record['jcd'], record['rno'])] = yuuki.read(receipt)
        if (record.get('selection') or {}).get('selected'):
            conditional.append({**record, 'stream': 'yuuki_selected'})
    return proof, conditional


def discover(day, previous=None):
    import direct_discord_notify as base
    base.fetch.cache_clear()
    # A saved schedule prevents a transient index failure forgetting a known venue.
    previous = previous or {}
    errors = []
    try:
        venues = set(base.discover_venues(day)) | set(previous)
    except Exception as exc:
        if not previous:
            raise
        errors.append({'jcd':'index', 'error_type':type(exc).__name__})
        venues = set(previous)
    if not venues:
        return {}, []
    def one(jcd):
        try:
            times = base.deadlines(day, jcd)
            if not times:
                raise RuntimeError('Official schedule unavailable')
            return jcd, times
        except Exception as exc:
            errors.append({'jcd': jcd, 'error_type': type(exc).__name__})
            return jcd, previous.get(jcd, [])
    with ThreadPoolExecutor(max_workers=8) as pool:
        schedules = dict(pool.map(one, sorted(venues)))
    return schedules, errors


def yuuki_engine(day, schedules, store, *, clock, budget_seconds=150, recheck_seconds=0,
                 monotonic=time.monotonic, sleep=time.sleep):
    """Use the unchanged Yuuki builder/formatter and shared transport guard."""
    import direct_discord_notify as base
    import prototype3_delivery as yuuki
    started = monotonic()
    done, waiting, passes = set(), {}, 0

    def process(args):
        _, jcd, rno, deadline = args
        key = yuuki.key_for(day, jcd, rno)
        if monotonic()-started >= budget_seconds:
            return key, 'budget_exhausted'
        if not yuuki.trial.before_deadline(day, deadline, clock()):
            return key, None
        # Repair reporting files from the exact durable prediction after main push loss.
        saved, _ = store.read(receipts.identity('yuuki', day, jcd, rno))
        if saved and saved.get('record') and saved['status'] == 'sent':
            receipts.atomic_write(yuuki.prediction_path(key), saved['record'])
        # Adopt old proof before parallel producers can start sending this race.
        record_path = yuuki.prediction_path(key)
        if record_path.exists():
            record = yuuki.read(record_path)
            for stream, path in [('yuuki', yuuki.receipt_path(key)), ('yuuki_selected', yuuki.selected_receipt_path(key))]:
                if path.exists():
                    adopt_legacy(stream, record, yuuki.read(path), store=store)
        yuuki.process_race(*args)
        status_path = yuuki.ROOT / 'status' / (key+'.json')
        state = yuuki.read(status_path).get('state') if status_path.exists() else None
        return key, state

    while monotonic()-started < budget_seconds:
        tasks = []
        for jcd, times in schedules.items():
            for rno, deadline in enumerate(times, 1):
                key = yuuki.key_for(day, jcd, rno)
                close = datetime.strptime(day+' '+deadline, '%Y%m%d %H:%M').replace(tzinfo=JST)
                if key not in done and 0 < (close-clock()).total_seconds() <= 30*60:
                    tasks.append((day, jcd, rno, deadline))
        if not tasks:
            break
        # Check new exhibition data on each bounded pass, with earlier deadlines first.
        base.fetch.cache_clear()
        ordered = sorted(tasks, key=lambda args: args[3])
        if recheck_seconds > 0:
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(process, ordered))
        else:
            results = [process(args) for args in ordered]
        passes += 1
        waiting = {}
        for key, state in results:
            if state in {'waiting_for_exhibition', 'official_unavailable',
                         'hiyori_feature_unavailable', 'data_error', 'budget_exhausted'}:
                waiting[key] = state
            else:
                done.add(key)
        remaining = budget_seconds-(monotonic()-started)
        if recheck_seconds <= 0 or not waiting or remaining <= 0:
            break
        sleep(min(recheck_seconds, remaining))
    return {'passes': passes, 'waiting': waiting}


def main_engine(day, schedules, store, *, clock):
    """Call the existing main, selected and opportunity pipeline once."""
    import delivery_guard_runner as legacy
    app = legacy.runner.app
    app.base.displayed_picks = app.displayed_picks_variable
    app.base.make_analysis_message = app.analysis_message_with_virtual
    app.base.log_prediction = app.log_prediction_with_virtual
    # Reuse this pass's official schedules, preserving all AI selection gates.
    original_discover, original_deadlines = app.base.discover_venues, app.base.deadlines
    app.base.discover_venues = lambda current_day: sorted(schedules)
    app.base.deadlines = lambda current_day, jcd: schedules.get(jcd, [])
    try:
        result = app.base.run_once(now=clock())
        if result:
            ERRORS['main_engine'] = 'engine_error'
    finally:
        app.base.discover_venues, app.base.deadlines = original_discover, original_deadlines
        legacy.runner.x_post_delivery.flush_pending()


def verify_yuuki(day, durable, *, store=None, previous=()):
    """Report exact production proof separately from probes and imported history."""
    import prototype3_delivery as yuuki
    from delivery_v2.guard import deliver_once
    prior = {row['key']:row for row in previous}
    checked = []
    for row in durable.values():
        if row.get('stream') not in {'yuuki','yuuki_selected'} or row.get('status') != 'sent':
            continue
        if row.get('source') == 'legacy_receipt':
            continue
        record = row['record']
        close = datetime.strptime(day+' '+record['deadline'], '%Y%m%d %H:%M').replace(tzinfo=JST)
        if not str(row.get('message_id','')).isdigit() or datetime.fromisoformat(row['sent_at']) >= close:
            raise ValueError('Production acknowledgement invalid or after deadline')
        path = yuuki.receipt_path(record['key']) if row['stream']=='yuuki' else yuuki.selected_receipt_path(record['key'])
        if not path.exists() or not yuuki.prediction_path(record['key']).exists():
            continue
        mirror = yuuki.read(path)
        if str(mirror.get('message_id')) != row['message_id'] or mirror.get('prediction_digest') != record['digest']:
            raise ValueError('Yuuki report receipt differs from durable receipt')
        if yuuki.read(yuuki.prediction_path(record['key'])) != record:
            raise ValueError('Yuuki report prediction differs from delivered record')
        valid_content = [yuuki.selected_message(record)] if row['stream']=='yuuki_selected' else [yuuki.message(record)]
        if row['stream']=='yuuki' and (record.get('selection') or {}).get('selected'):
            valid_content.append(yuuki.selected_message(record))
        if row.get('content') not in valid_content:
            raise ValueError('Yuuki payload differs from existing prediction formatter')
        old = prior.get(row['key'], {})
        replay_verified = (old.get('message_id') == row['message_id'] and old.get('digest') == record['digest']
                           and bool(old.get('restart_duplicate_guard_verified')))
        if not replay_verified and store is not None:
            def forbidden(_):
                raise AssertionError('Verified prediction attempted another Discord POST')
            replay = deliver_once(row['stream'], day, row['jcd'], row['rno'], row['content'], forbidden,
                row['phase'], store=store, record=record, expires_at=close)
            if replay['status'] != 'already_sent' or replay['message_id'] != row['message_id']:
                raise ValueError('Production receipt replay did not prevent duplicate delivery')
            replay_verified = True
        checked.append({'key':row['key'],'message_id':row['message_id'],'digest':record['digest'],
                        'sent_at':row['sent_at'],'deadline':close.isoformat(), 'verified':True,
                        'restart_duplicate_guard_verified':replay_verified})
    return checked


def run_once(*, store=None, clock=None, schedules=None, engine=None, active=('yuuki', 'yuuki_selected'), budget_seconds=150, recheck_seconds=0, activation_at=None):
    clock = clock or (lambda: datetime.now(JST))
    now = clock()
    if now.tzinfo is None:
        raise ValueError('Dispatcher requires an aware current time')
    activation_at = activation_at or datetime.fromisoformat(os.getenv('DISCORD_DELIVERY_V2_ACTIVE_SINCE', now.isoformat()))
    if activation_at.tzinfo is None:
        raise ValueError('Stream activation requires an aware timestamp')
    day = now.astimezone(JST).strftime('%Y%m%d')
    store = store or default_store()
    ERRORS.clear()
    checkpoint_key = receipts.identity('dispatcher', day, '01', 1, 'check')
    previous, checkpoint_sha = store.read(checkpoint_key)
    errors = []
    if schedules is None:
        schedules, errors = discover(day, (previous or {}).get('schedules'))
    # Do not preload the entire day's growing receipt tree before generation.
    # Each live candidate is checked against its exact durable receipt by the
    # delivery guard; the full pinned snapshot is only needed for the audit
    # after the time-critical delivery pass. This keeps late races from being
    # crowded out by hundreds of historical receipts.
    generation = {}
    if engine is not None:
        engine(day, schedules, store, clock=clock)
    elif 'yuuki' in active:
        generation = yuuki_engine(day, schedules, store, clock=clock,
                                  budget_seconds=budget_seconds, recheck_seconds=recheck_seconds)
    if engine is None and 'main' in active:
        main_engine(day, schedules, store, clock=clock)
    legacy, conditional = legacy_state(day)
    durable = store.list_day(day)
    for row in durable.values():
        if row.get('stream') in {'selected','mid_odds','mid_odds_selected','longshot','yuuki_selected'} and row.get('record'):
            conditional.append({**row['record'], 'stream': row['stream']})
    expected = generate_expected(day, schedules, records=conditional)
    rows = audit(expected, now=clock(), durable=durable, legacy=legacy)
    counts = dict(Counter(row['status'] for row in rows))
    verification = verify_yuuki(day, durable, store=store,
        previous=(previous or {}).get('production_verification', ()))
    active_since = dict((previous or {}).get('active_since', {}))
    for stream in active:
        active_since.setdefault(stream, activation_at.isoformat())
    active_missed = [row for row in rows if row['stream'] in active and row['status']=='missed'
                    and datetime.fromisoformat(row['deadline']) >= datetime.fromisoformat(active_since[row['stream']])]
    for row in active_missed:
        notify_failure(row['stream'], row, row, store)
    for row in rows:
        if row['stream'] in active and row['status'] in {'failed','uncertain','sending'}:
            state = durable.get(row['key'], row)
            if stalled(state):
                notify_failure(row['stream'], {'day':day,'jcd':row['jcd'],'rno':row['rno']}, state, store)
    report = {'key':checkpoint_key, 'status':'checked' if not errors and not ERRORS and not active_missed else 'degraded',
              'day':day, 'stream':'dispatcher', 'jcd':'01', 'rno':1, 'phase':'check',
              'started_at':now.isoformat(), 'checked_at':clock().isoformat(),
              'previous_successful_check':(previous or {}).get('last_successful_check'),
              'last_successful_check':clock().isoformat() if not errors and not ERRORS and not active_missed else (previous or {}).get('last_successful_check'),
              'active_streams':list(active), 'schedules':schedules, 'counts':counts,
              'schedule_errors':errors, 'delivery_errors':dict(ERRORS), 'deliveries':rows}
    report['production_verification'] = verification
    report['generation'] = generation
    report['trigger_event'] = os.getenv('GITHUB_EVENT_NAME', '')
    report['workflow_run_id'] = os.getenv('GITHUB_RUN_ID', '')
    report['wake_reason'] = os.getenv('DISCORD_DELIVERY_V2_WAKE_REASON', '')
    report['active_since'] = active_since
    report['active_missed'] = active_missed
    receipts.atomic_write(SUMMARY, report)
    # Cursor is diagnostic. Eligibility always scans every current unexpired race.
    try:
        store.write(checkpoint_key, report, checkpoint_sha)
    except Conflict:
        raise RuntimeError('Another dispatcher updated this checkpoint') from None
    print('Dispatcher '+json.dumps({k:report[k] for k in ['day','status','active_streams','counts','previous_successful_check']}, ensure_ascii=False), flush=True)
    summary = os.getenv('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as handle:
            handle.write('### Discord Delivery V2\n\n'+json.dumps(counts, ensure_ascii=False)+'\n\n')
            handle.write('Live streams: '+', '.join(active)+'; other streams are audited through existing receipts.\n')
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--streams', default=os.getenv('DISCORD_DELIVERY_V2_STREAMS', 'yuuki,yuuki_selected'))
    parser.add_argument('--budget-seconds', type=int, default=150)
    parser.add_argument('--recheck-seconds', type=int, default=20)
    args = parser.parse_args()
    active = tuple(x.strip() for x in args.streams.split(',') if x.strip())
    allowed = {'yuuki','yuuki_selected','main','selected','mid_odds','mid_odds_selected','longshot'}
    if not set(active).issubset(allowed) or ('yuuki_selected' in active and 'yuuki' not in active):
        parser.error('Unsupported stream set; selected Yuuki requires Yuuki')
    os.environ['DISCORD_DELIVERY_V2_STREAMS'] = ','.join(active)
    try:
        report = run_once(active=active, budget_seconds=args.budget_seconds,
                          recheck_seconds=args.recheck_seconds)
        return 0 if report['status'] == 'checked' else 1
    except Exception as exc:
        print(f'::error::Production dispatcher failed ({type(exc).__name__})', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
