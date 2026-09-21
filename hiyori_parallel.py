"""A separate acknowledged Hiyori stream sharing the baseline's race snapshot."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
import gzip
import json
import os
from pathlib import Path
import time
import urllib.parse
import urllib.request

import direct_discord_notify as base
import hiyori_model
import hiyori_smoke_test as discord
import hiyori_source
from ticket_compression import compression_snapshot, format_support_note

ROOT = Path('data/hiyori')
POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix='hiyori')
ACTIVE = {}
SETTLEMENT = None
LAST_SETTLEMENT = 0.0


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def key_for(day, jcd, rno):
    return f'{day}_{str(jcd).zfill(2)}_{int(rno):02d}'


def status(key, state, **extra):
    save(ROOT / 'status' / f'{key}.json',
         {'state': state, 'updated_at': datetime.now(base.JST).isoformat(), **extra})


def before_deadline(request, now=None):
    now = now or datetime.now(base.JST)
    return (now.strftime('%Y%m%d') == request['day']
            and base.minutes_until(now, request['deadline']) >= 1)


def capture(day, jcd, rno, deadline, analysis, baseline_rows):
    key = key_for(day, jcd, rno)
    path = ROOT / 'requests' / f'{key}.json'
    if path.exists() or (ROOT / 'deliveries' / f'{key}.json').exists():
        return
    request = {'day': day, 'jcd': str(jcd).zfill(2), 'rno': int(rno),
               'deadline': deadline, 'captured_at': datetime.now(base.JST).isoformat(),
               'official': deepcopy(analysis), 'baseline_rows': deepcopy(baseline_rows)}
    if not before_deadline(request):
        return
    save(path, request)
    status(key, 'queued')


def install(app):
    if getattr(app, '_hiyori_parallel_installed', False):
        return
    original = app.analysis_message_with_virtual

    def with_hiyori(day, jcd, rno, deadline, phase, analysis, rows, required):
        message = original(day, jcd, rno, deadline, phase, analysis, rows, required)
        if phase == 'final' and os.getenv('HIYORI_DISCORD_WEBHOOK_URL'):
            try:
                capture(day, jcd, rno, deadline, analysis, rows)
                tick()
            except Exception as exc:
                print(f'Hiyori capture failed: {type(exc).__name__}', flush=True)
        return message

    app.analysis_message_with_virtual = with_hiyori
    app._hiyori_parallel_installed = True


def make_payload(request, analysis, rows):
    combos = [row['combination'] for row in rows]
    head = max(analysis['heads'], key=analysis['heads'].get)
    lead = next(feature for feature in analysis['features'] if feature['lane'] == int(head))
    rate = lead.get('course_win_rate')
    explanation = f"{head}号艇を軸候補。"
    if rate is not None:
        explanation += f"日和の{lead['course']}コース1着率 {rate*100:.1f}%（{int(lead['course_samples'])}走）。"
    if lead.get('course_st') is not None:
        explanation += f"コース別平均ST {lead['course_st']:.2f}。"
    text = (f"🧪 **日和AI・比較テスト｜{base.VENUES[request['jcd']]} {request['rno']}R**\n"
            f"締切 {request['deadline']}｜日和データ追加版\n"
            f"**買い目 {len(combos)}点**\n" + ' ／ '.join(combos) + '\n'
            + explanation + '\n'
            + '**同時点の既存予想**\n' + ' ／ '.join(r['combination'] for r in request['baseline_rows'])
            + format_support_note(analysis)
            + '\n※検証用。表示確率・期待値は未校正の参考値です。\n'
            + analysis['source_url'])
    if len(text.encode('utf-16-le')) // 2 > 2000:
        raise ValueError('Hiyori card exceeds Discord text limit')
    return {'content': text, 'allowed_mentions': {'parse': []}, 'flags': 4096}


def process(request):
    from detailed_discord_notify import displayed_picks_variable
    key = key_for(request['day'], request['jcd'], request['rno'])
    receipt_path = ROOT / 'deliveries' / f'{key}.json'
    if receipt_path.exists():
        return
    if not before_deadline(request):
        status(key, 'missed_deadline')
        return
    try:
        source = hiyori_source.fetch_race(request['day'], request['jcd'], request['rno'])
        source['fetched_at'] = datetime.now(base.JST).isoformat()
        analysis = hiyori_model.analyze(request['official'], source, request['day'], request['jcd'], request['rno'])
        rows = displayed_picks_variable(analysis, True)
        if not rows:
            status(key, 'pass', reason='no_selected_combinations')
            return
        payload = make_payload(request, analysis, rows)
        archive = ROOT / 'snapshots' / f'{key}.json.gz'
        archive.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(archive, 'wt', encoding='utf-8') as handle:
            json.dump({'request': request, 'source': source, 'analysis': analysis,
                       'compression': compression_snapshot(analysis), 'payload': payload}, handle, ensure_ascii=False)
    except Exception as exc:
        status(key, 'data_error', error_type=type(exc).__name__)
        print(f'Hiyori data error {key}: {type(exc).__name__}', flush=True)
        return
    # Data collection may take time: recheck against the wall clock before POST.
    if not before_deadline(request):
        status(key, 'missed_deadline')
        return
    try:
        parts = discord.webhook()
        query = dict(urllib.parse.parse_qsl(parts.query))
        query['wait'] = 'true'
        target = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
        message = discord.request_json(target, payload)
        if not str(message.get('id', '')).isdigit() or not str(message.get('channel_id', '')).isdigit():
            raise RuntimeError('No Discord message acknowledgement')
        receipt = {k: request[k] for k in ('day', 'jcd', 'rno', 'deadline', 'captured_at')}
        receipt.update(stream='hiyori', model_version=analysis['model_version'],
                       all_picks=[r['combination'] for r in rows], heads=analysis['heads'],
                       point_count=len(rows), odds={r['combination']: r.get('odds') for r in rows},
                       source_fetched_at=source['fetched_at'],
                       message_id=str(message['id']), channel_id=str(message['channel_id']),
                       sent_at=datetime.now(base.JST).isoformat())
        save(receipt_path, receipt)
        status(key, 'sent', message_id=receipt['message_id'])
        print(f"Hiyori prediction confirmed {key} message_id={receipt['message_id']}", flush=True)
    except Exception as exc:
        # A timeout after POST may still have delivered; do not duplicate it.
        status(key, 'delivery_unconfirmed', error_type=type(exc).__name__)
        print(f'Hiyori delivery unconfirmed {key}: {type(exc).__name__}', flush=True)


def settle_available():
    import daily_report
    settled = 0
    attempted = 0
    for path in sorted((ROOT / 'deliveries').glob('*.json')):
        target = ROOT / 'results' / path.name
        if target.exists():
            continue
        receipt = read(path)
        now = datetime.now(base.JST)
        close = datetime.strptime(receipt['day'] + ' ' + receipt['deadline'], '%Y%m%d %H:%M').replace(tzinfo=base.JST)
        if (now - close).total_seconds() < 120:
            continue
        if attempted >= 3:
            break
        attempted += 1
        try:
            url = base.official_url('raceresult', receipt['day'], receipt['jcd'], receipt['rno'])
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': base.UA}), timeout=8) as response:
                result = daily_report.parse_payout(response.read().decode('utf-8'))
            if result.get('status') != 'settled':
                continue
            payouts = result.get('payouts') or {}
            refunds = set(map(int, result.get('refund_lanes') or []))
            def returns(picks):
                return sum(100 if set(map(int, p.split('-'))) & refunds else int(payouts.get(p) or 0) for p in picks)
            winning = [p for p in receipt['all_picks'] if p in payouts]
            record = dict(receipt, result=result, hit=bool(winning), winning_picks=winning,
                          stake_yen=100*len(receipt['all_picks']), return_yen=returns(receipt['all_picks']),
                          settled_at=now.isoformat(), hit_alert_sent=False)
            record['roi'] = record['return_yen'] / record['stake_yen'] * 100
            with gzip.open(ROOT/'snapshots'/f'{path.stem}.json.gz', 'rt', encoding='utf-8') as handle:
                snapshot = json.load(handle)
            record['compression'] = {n: {'picks': picks, 'hit': any(p in payouts for p in picks),
                                         'stake_yen': 100*len(picks), 'return_yen': returns(picks)}
                                     for n, picks in snapshot['compression']['levels'].items()}
            save(target, record)
            status(path.stem, 'settled', hit=bool(winning), message_id=receipt['message_id'])
            settled += 1
        except Exception as exc:
            print(f'Hiyori result pending {path.stem}: {type(exc).__name__}', flush=True)
        if settled >= 3:
            break


def tick():
    global SETTLEMENT, LAST_SETTLEMENT
    if not os.getenv('HIYORI_DISCORD_WEBHOOK_URL'):
        return
    for key, future in list(ACTIVE.items()):
        if future.done():
            try:
                future.result()
            except Exception as exc:
                status(key, 'worker_error', error_type=type(exc).__name__)
            del ACTIVE[key]
    pending = [(path, read(path)) for path in (ROOT/'requests').glob('*.json')]
    pending.sort(key=lambda pair: (pair[1]['day'], pair[1]['deadline'], pair[0].name))
    for path, request in pending:
        key = path.stem
        if key in ACTIVE or (ROOT/'deliveries'/path.name).exists():
            continue
        state = read(ROOT/'status'/path.name) if (ROOT/'status'/path.name).exists() else {}
        if state.get('state') in {'pass', 'missed_deadline', 'delivery_unconfirmed'}:
            continue
        if not before_deadline(request):
            status(key, 'missed_deadline')
            continue
        if len(ACTIVE) < 2:
            ACTIVE[key] = POOL.submit(process, request)
    if time.monotonic() - LAST_SETTLEMENT >= 60 and (SETTLEMENT is None or SETTLEMENT.done()):
        if SETTLEMENT is not None:
            try:
                SETTLEMENT.result()
            except Exception as exc:
                print(f'Hiyori settlement error: {type(exc).__name__}', flush=True)
        SETTLEMENT = POOL.submit(settle_available)
        LAST_SETTLEMENT = time.monotonic()


def finish():
    POOL.shutdown(wait=True)
