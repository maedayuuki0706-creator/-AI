"""Independent, bounded live producer; never imports an outcome reader.

Writes only the dedicated research state branch. The existing collectors,
delivered cards, Discord/X, production settings and Secrets are untouched.
"""
import argparse
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request

from .application import build, markdown, clock
from .prepared import PreparedMaterials
from research.capture_v1 import parsers
from research.materials_v1.collector import (Store, now, aware, stamp, encode, read,
    once, url, deadline, program, preview, parse_odds, VENUES)
from research.materials_v1.supplement import collect_live_karatsu

STATE_BRANCH = 'research-materials-applied-state-v1'
REPO = 'maedayuuki0706-creator/-AI'
STAGES = {'T10': (600, 665), 'T5': (300, 365), 'T4': (240, 285)}
ALLOWED = {'README.md', 'policy.json', 'raw', 'cache', 'acquisitions', 'programs',
           'previews', 'original_foot', 'inputs', 'forecasts', 'reports', 'attempts',
           'receipts', 'grades', 'results', 'errors', 'preinspection'}
SERIES = {'06': ('20261021', '20261026', 'SUZUKI',
    'https://www.boatrace-hamanako.jp/modules/raceinfo/?page=index_timerank'),
    '23': ('20261018', '20261023', '全日本王者決定戦',
    'https://www.boatrace-karatsu.jp/modules/raceinfo/?page=index_timerank')}


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE)


def preinspection(store, existing, snapshot):
    m = snapshot['meta']; code = str(m['jcd']).zfill(2); day = m['day']
    if code not in SERIES:
        return {'status': 'first_day_not_in_current_scope', 'required': False}
    first, last, title, source = SERIES[code]
    if not first <= day <= last:
        raise ValueError('Current series identity needs review before this venue resumes')
    if day != first:
        return {'status': 'not_first_day', 'first_day': first, 'required': False}
    old = Path(existing) / 'phase1/preinspection' / first / (code + '.json')
    doc = read(old) if old.is_file() else None
    if doc:
        if doc.get('source_url') != source or doc.get('first_day') != first:
            raise ValueError('Preinspection archived source/series differs')
        raw = doc['raw_html']
        if sha256(raw.encode()).hexdigest() != doc['sha256']:
            raise ValueError('Preinspection archive hash differs')
        observed = doc['observed_at']
    else:
        acquisition = store.get(source, ttl=600)
        if acquisition['status'] != 'ok':
            raise ValueError('First-day preinspection source unavailable; hold')
        raw = store.body(acquisition); observed = acquisition['retrieved_at']
        doc = {'first_day': first, 'source_url': source, 'raw_html': raw,
               'sha256': acquisition['sha256'], 'observed_at': observed}
    header = raw[raw.find('com-racetitle_group'):raw.find('com-racetitle_group') + 6000]
    month = re.search(r'schedule-area__month[^>]*>\s*(\d+)/', header)
    start = re.search(r'item-day[^>]*>\s*(\d+)', header)
    if (not month or not start or (int(month[1]), int(start[1])) != (int(first[4:6]), int(first[6:]))
            or title not in parsers.clean(header) or aware(observed) > now()
            or not datetime.strptime(first, '%Y%m%d').date() - timedelta(days=1)
                <= aware(observed).date() <= datetime.strptime(first, '%Y%m%d').date()):
        raise ValueError('First-day series date/title/time not verified; hold')
    indexed = {}
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', raw, re.S | re.I):
        cells = [parsers.clean(c) for c in re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.S | re.I)]
        if len(cells) != 10 or not re.fullmatch(r'\d{4}', cells[1]):
            continue
        match = re.search(r'toban=(\d{4})', row)
        if not match or match[1] != cells[1] or not 5 < float(cells[9]) < 10 or cells[1] in indexed:
            raise ValueError('Preinspection row identity or timing invalid')
        indexed[cells[1]] = {'racer_id': cells[1], 'motor_number': int(cells[4]),
                            'preinspection_time': float(cells[9])}
    rows = []
    for b in snapshot['boats']:
        r = indexed.get(str(b['racer_id']))
        if not r or r['motor_number'] != b['motor_number']:
            raise ValueError('First-day six racer/motor identities not verified; hold')
        rows.append(r)
    store.record('preinspection', first + '_' + code, doc)
    return {'status': 'six_racer_motor_identities_match', 'required': True,
            'first_day': first, 'source_url': source, 'source_sha256': doc['sha256'],
            'observed_at': observed, 'rows': rows, 'numeric_grade_invented': False}


def fresh_snapshot(store, day, code, rno, *, expected_deadline=None):
    docs = []
    # Force an ordered, fresh pair; a cached preview older than the current
    # roster cannot honestly assert a simultaneous six-boat identity.
    for kind in ('racelist', 'beforeinfo'):
        d = store.get(url(kind, day, code, rno), ttl=0)
        if d['status'] != 'ok':
            raise ValueError('Fresh official ' + kind + ' unavailable')
        docs.append(d)
    card, before = docs
    raw = store.body(card); bh = store.body(before)
    hhmm = deadline(raw, rno)
    if expected_deadline and hhmm != expected_deadline:
        raise ValueError('Official deadline changed; refresh schedule on next pass')
    boats = program(raw); pr = preview(bh)
    if len(boats) != 6 or pr['exhibition_count'] != 6 or not pr['entry_observed']:
        raise ValueError('Six current exhibition boats and entry required')
    for b in boats:
        b.update(pr['boats'][b['lane']])
        b.update(course=b['predicted_course'], exhibition_st=b.get('exhibition_st_timing'))
    captured = stamp()
    if max((aware(captured) - aware(d['retrieved_at'])).total_seconds() for d in docs) > 90:
        raise ValueError('Official pair became stale during acquisition')
    return {'meta': {'day': day, 'jcd': code, 'rno': rno, 'deadline': hhmm, 'captured_at': captured},
            'boats': boats, 'environment': {k: v for k, v in pr.items() if k != 'boats'},
            'official_originals': {kind: {'html': store.body(d), 'url': d['url'],
                'sha256': d['sha256'], 'observed_at': d['retrieved_at']}
                for kind, d in zip(('racelist', 'beforeinfo'), docs)}}


def freeze(store, source, existing, materials, day, code, rno, stage, hhmm):
    key = f'{day}_{code}_{rno:02}_{stage}'
    destination = store.root / 'forecasts' / (key + '.json')
    if destination.exists():
        # A prior partial write must be detected rather than overwritten.
        snapshot = read(store.root / 'inputs' / (key + '.json'))
        from research.scenario_v2.engine import verify, digest
        forecast = read(destination); verify(forecast)
        if forecast['source_input_digest'] != digest(snapshot):
            raise ValueError('Immutable input/forecast mismatch')
        return {'key': key, 'status': 'already_frozen'}
    snapshot = fresh_snapshot(store, day, code, rno, expected_deadline=hhmm)
    snapshot['source'] = {'preinspection': preinspection(store, existing, snapshot)}
    # Measured foot is collected in this isolated store *before* generation.
    if code == '23':
        collect_live_karatsu(store, snapshot)
    odds_doc = store.get(url('odds3t', day, code, rno), ttl=0)
    market = {'status': 'unavailable', 'acquisition': odds_doc}
    if odds_doc['status'] == 'ok':
        try:
            market.update(status='complete', odds=parse_odds(store.body(odds_doc)))
        except ValueError as exc:
            market.update(status='incomplete_excluded', reason=str(exc))
    snapshot['market'] = market
    snapshot['meta']['captured_at'] = stamp()
    if max((now() - aware(d['observed_at'])).total_seconds()
           for d in snapshot['official_originals'].values()) > 90:
        raise ValueError('Official sources stale after supplementary acquisition; hold')
    forecast = build(snapshot, materials, state_root=store.root, mode='live', now=clock())
    if code != '23':
        # Nearby tide predictions are read-only evidence, never a race-surface
        # measurement. This source tree is disjoint from our writable state.
        from .context import tide_context
        forecast['tide_context'] = tide_context(source, snapshot, forecast['assembled_at'])
    from research.scenario_v2.engine import digest
    forecast['capture_stage'] = stage
    forecast['seconds_before_deadline_at_generation'] = round(
        (aware(forecast['deadline_at']) - aware(forecast['assembled_at'])).total_seconds(), 3)
    forecast['code_commit'] = os.environ.get('MATERIALS_APPLIED_CODE_SHA')
    forecast['first_day_preinspection'] = snapshot['source']['preinspection']
    forecast['odds_context'] = market
    forecast['market_prices_of_cards'] = {name: {c: market.get('odds', {}).get(c) for c in card}
                                         for name, card in forecast['model_cards'].items()}
    forecast['digest'] = digest({k: v for k, v in forecast.items() if k != 'digest'})
    # A crashed producer can leave an orphan input. It must be quarantined by
    # explicit failure, never paired with a newly fetched source silently.
    once(store.root / 'inputs' / (key + '.json'), encode(snapshot))
    once(destination, encode(forecast))
    once(store.root / 'reports' / (key + '.md'), markdown(forecast).encode())
    return {'key': key, 'status': 'frozen_unconfirmed', 'deadline_at': forecast['deadline_at']}


def remote_ack(commit, *, opener=urllib.request.urlopen):
    proof = f'https://api.github.com/repos/{REPO}/git/ref/heads/{STATE_BRANCH}?proof={commit}&nonce={time.time_ns()}'
    headers = {'User-Agent': 'BoatAI-MaterialsApplied/1.0', 'Cache-Control': 'no-cache'}
    if os.environ.get('MATERIALS_APPLIED_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['MATERIALS_APPLIED_TOKEN']
    request = urllib.request.Request(proof, headers=headers)
    with opener(request, timeout=15) as response:
        body = json.load(response); server_date = response.headers.get('Date')
    if body.get('object', {}).get('sha') != commit or not server_date:
        raise ValueError('Fresh external state acknowledgement missing')
    if abs((now() - parsedate_to_datetime(server_date)).total_seconds()) >= 60:
        raise ValueError('Stale server acknowledgement')
    return {'ref_url': proof, 'github_server_date': server_date, 'checked_at': stamp()}


def publish(store):
    root = store.root
    if git(root, 'branch', '--show-current').decode().strip() != STATE_BRANCH:
        raise ValueError('Refuse any write outside isolated applied state branch')
    remote = git(root, 'remote', 'get-url', 'origin').decode().strip()
    if not re.fullmatch(r'https://github\.com/maedayuuki0706-creator/-AI(?:\.git)?', remote):
        raise ValueError('Unexpected state repository remote')
    changed = git(root, 'status', '--porcelain', '-z').decode().split('\0')
    for row in changed:
        if row and (row[3:].split('/')[0] not in ALLOWED or row[:2].strip() == 'R'):
            raise ValueError('Unexpected file in isolated state')
    if any(changed):
        git(root, 'add', '--', *sorted(ALLOWED - {'README.md', 'policy.json'} & {p.name for p in root.iterdir()}))
        if git(root, 'diff', '--cached', '--name-only').strip():
            git(root, 'commit', '-m', 'research applied: immutable inputs, six-boat forecasts and audit')
            git(root, 'push', 'origin', 'HEAD:refs/heads/' + STATE_BRANCH)
    commit = git(root, 'rev-parse', 'HEAD').decode().strip()
    if git(root, 'ls-remote', 'origin', 'refs/heads/' + STATE_BRANCH).decode().split()[0] != commit:
        raise ValueError('External state commit not confirmed')
    pending = [p for p in (root / 'forecasts').glob('*.json') if not (root / 'receipts' / p.name).exists()]
    if not pending:
        return {'status': 'saved', 'remote_commit': commit, 'new_receipts': 0}
    try:
        acknowledgement = remote_ack(commit)
    except Exception as exc:
        return {'status': 'saved_receipt_pending', 'remote_commit': commit,
                'reason': type(exc).__name__ + ': ' + str(exc)[:150]}
    for p in pending:
        f = read(p); inp = root / 'inputs' / p.name
        for prefix, path in (('forecasts', p), ('inputs', inp)):
            if git(root, 'show', commit + ':' + prefix + '/' + p.name) != path.read_bytes():
                raise ValueError('External commit content differs')
        cutoff = aware(f['deadline_at']) - timedelta(seconds=180)
        before = aware(acknowledgement['checked_at']) <= cutoff and parsedate_to_datetime(acknowledgement['github_server_date']) <= cutoff
        receipt = {**acknowledgement, 'key': p.stem, 'race_id': f['race_id'],
            'remote_commit': commit, 'remote_ref': STATE_BRANCH,
            'forecast_sha256': sha256(p.read_bytes()).hexdigest(),
            'input_sha256': sha256(inp.read_bytes()).hexdigest(),
            'forecast_git_blob': git(root, 'rev-parse', commit + ':forecasts/' + p.name).decode().strip(),
            'input_git_blob': git(root, 'rev-parse', commit + ':inputs/' + p.name).decode().strip(),
            'confirmed_at_least_three_minutes_before_deadline': before,
            'count_as_prospective': before,
            'reason': None if before else 'External confirmation too late; exclude prospective record'}
        once(root / 'receipts' / p.name, encode(receipt))
    git(root, 'add', 'receipts'); git(root, 'commit', '-m', 'research applied: external timestamp receipt')
    git(root, 'push', 'origin', 'HEAD:refs/heads/' + STATE_BRANCH)
    return {'status': 'saved', 'remote_commit': commit, 'new_receipts': len(pending)}


def tick(store, source, existing, materials):
    day = now().strftime('%Y%m%d'); captures = []
    for code in VENUES:
        card = store.get(url('racelist', day, code, 1), ttl=900)
        if card['status'] != 'ok':
            captures.append({'venue': code, 'status': 'schedule_unavailable'}); continue
        raw = store.body(card)
        try:
            if len(program(raw)) != 6:
                captures.append({'venue': code, 'status': 'no_published_six_boat_program'}); continue
            schedule = [deadline(raw, rno) for rno in range(1, 13)]
        except (ValueError, KeyError, IndexError) as exc:
            captures.append({'venue': code, 'status': 'schedule_held', 'reason': str(exc)[:180]}); continue
        for rno in range(1, 13):
            hhmm = schedule[rno - 1]
            at = datetime.strptime(day + ' ' + hhmm, '%Y%m%d %H:%M').replace(tzinfo=now().tzinfo)
            remaining = (at - now()).total_seconds()
            for stage, (low, high) in STAGES.items():
                key = f'{day}_{code}_{rno:02}_{stage}'
                if low <= remaining <= high:
                    try:
                        captures.append(freeze(store, source, existing, materials, day, code, rno, stage, hhmm))
                    except Exception as exc:
                        value = {'key': key, 'status': 'held', 'checked_at': stamp(),
                                 'reason': type(exc).__name__ + ': ' + str(exc)[:240]}
                        store.record('attempts', key, value); captures.append(value)
                elif remaining < low and not (store.root / 'forecasts' / (key + '.json')).exists():
                    once(store.root / 'attempts' / (key + '_missed.json'), encode({'key': key,
                        'status': 'missed', 'recorded_at': stamp(), 'reason': 'No complete forecast in actual capture window'}))
    report = {'checked_at': stamp(), 'captures': captures, 'http_requests_total': store.fetches,
              'forecast_producer_read_current_results': False}
    # One current health document, preserving only meaningful events above.
    from research.materials_v1.collector import write
    write(store.root / 'reports/health.json', report)
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--state', required=True, type=Path)
    p.add_argument('--source', required=True, type=Path)
    p.add_argument('--existing', required=True, type=Path)
    p.add_argument('--seconds', type=int, default=0)
    p.add_argument('--interval', type=int, default=20)
    p.add_argument('--publish', action='store_true')
    a = p.parse_args()
    if not 0 <= a.seconds <= 480 or not 15 <= a.interval <= 60:
        raise ValueError('Worker bounds exceeded')
    if a.state.resolve() in (a.source.resolve(), a.existing.resolve()):
        raise ValueError('Writable and existing source trees must be disjoint')
    store = Store(a.state)
    materials = PreparedMaterials(results_root=a.source)
    end = time.monotonic() + a.seconds
    while True:
        print(json.dumps(tick(store, a.source, a.existing, materials), ensure_ascii=False), flush=True)
        pending_receipt = any(not (store.root / 'receipts' / p.name).exists()
                              for p in (store.root / 'forecasts').glob('*.json'))
        if a.publish and pending_receipt:
            print(json.dumps({'persistence': publish(store)}, ensure_ascii=False), flush=True)
        if time.monotonic() + a.interval > end:
            break
        time.sleep(a.interval)
    # Independent outcome phase, after all producer output has been frozen.
    subprocess.run([__import__('sys').executable, '-m', 'research.materials_application_v1.settle',
                    '--state', str(a.state), '--source', str(a.source)], check=True)
    if a.publish:
        print(json.dumps({'final_persistence': publish(store)}), flush=True)


if __name__ == '__main__':
    main()
