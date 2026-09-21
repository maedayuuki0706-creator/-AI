"""Prospective, fixed-budget Existing / Hiyori / Prototype 1 / Prototype 2 trial.

This is a separate shadow experiment, not a Discord delivery record. The two
controls are rebuilt from the SAME official snapshot at ten points each.
Native candidate cards are retained as diagnostics, never called sent cards.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
from itertools import permutations
import gzip
import json
from math import isfinite
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

import bridge_learning
import detailed_discord_notify as cards

JST = ZoneInfo('Asia/Tokyo')
VERSION = 'four-way-70-30-10points-v1'
POINTS = 10
UNIT_YEN = 100
STREAMS = ('existing', 'hiyori', 'prototype1', 'prototype2')
LABELS = {'existing': '既存', 'hiyori': '日和',
          'prototype1': 'プロトタイプ1（既存優先）',
          'prototype2': 'プロトタイプ2（日和優先）'}
WEIGHTS = {'existing': (1.0, 0.0), 'hiyori': (0.0, 1.0),
           'prototype1': (0.7, 0.3), 'prototype2': (0.3, 0.7)}
COMBINATIONS = frozenset('-'.join(map(str, p)) for p in permutations(range(1, 7), 3))
ROOT = Path('data/prototypes') / VERSION


def identity(day, jcd, rno):
    datetime.strptime(day, '%Y%m%d')
    if not 1 <= int(jcd) <= 24 or not 1 <= int(rno) <= 12:
        raise ValueError('Invalid race identity')
    return f'{day}_{int(jcd):02d}_{int(rno):02d}'


def close_time(day, deadline):
    return datetime.strptime(f'{day} {deadline}', '%Y%m%d %H:%M').replace(tzinfo=JST)


def aware(value):
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None:
        raise ValueError('A timezone-aware timestamp is required')
    return result.astimezone(JST)


def before_deadline(day, deadline, now, lead_seconds=60):
    now = aware(now)
    return now.strftime('%Y%m%d') == day and now <= close_time(day, deadline) - timedelta(seconds=lead_seconds)


def distribution(rows):
    result = {}
    for row in rows:
        combo = row.get('combination')
        if combo not in COMBINATIONS or combo in result:
            raise ValueError('Invalid or duplicate trifecta')
        value = float(row['probability'])
        if not isfinite(value) or value < 0:
            raise ValueError('Invalid probability')
        result[combo] = value
    if set(result) != COMBINATIONS or sum(result.values()) <= 0:
        raise ValueError('A complete 120-combination distribution is required')
    total = sum(result.values())
    return {combo: value / total for combo, value in result.items()}


def fuse(existing_rows, hiyori_rows, existing_weight=0.7, hiyori_weight=0.3):
    weights = (existing_weight, hiyori_weight)
    if any(not isfinite(w) or w < 0 for w in weights) or abs(sum(weights) - 1) > 1e-9:
        raise ValueError('Weights must be nonnegative and sum to one')
    a, b = distribution(existing_rows), distribution(hiyori_rows)
    mixed = {c: existing_weight * a[c] + hiyori_weight * b[c] for c in COMBINATIONS}
    return [{'combination': c, 'probability': mixed[c]}
            for c in sorted(mixed, key=lambda c: (-mixed[c], c))]


def _heads(rows):
    return {str(n): sum(r['probability'] for r in rows if r['combination'].startswith(f'{n}-'))
            for n in range(1, 7)}


def _card(rows, parent, stream, odds):
    analysis = deepcopy(parent)
    analysis['trifecta'] = deepcopy(rows)
    analysis['heads'] = _heads(rows)
    ranked = sorted(analysis['heads'].values(), reverse=True)
    top, gap = ranked[0], ranked[0] - ranked[1]
    analysis['grade'] = 'A' if top >= .45 and gap >= .20 else 'B' if top >= .30 and gap >= .08 else 'C'
    for row in analysis['trifecta']:
        odd = odds.get(row['combination'])
        row['odds'] = odd
        row['expected_value'] = row['probability'] * odd if odd is not None else None
    # All four use the same cap, including the legacy three-head exception.
    selected = cards._conviction_picks(analysis, POINTS)[:POINTS]
    use_bridge = stream in ('existing', 'prototype1')
    if use_bridge:
        selected = bridge_learning._reallocate(analysis, selected)
    picks = [r['combination'] for r in selected]
    if len(picks) != POINTS or len(set(picks)) != POINTS:
        raise ValueError('The fixed-point comparison card is incomplete')
    return {'label': LABELS[stream], 'weights': dict(zip(('existing', 'hiyori'), WEIGHTS[stream])),
            'selection_policy': 'conviction-10-plus-existing-bridge' if use_bridge else 'conviction-10',
            'picks': picks, 'point_count': POINTS, 'stake_yen': POINTS * UNIT_YEN,
            'heads': analysis['heads'], 'grade': analysis['grade'],
            'probability_mass': sum(r['probability'] for r in selected),
            'estimated_return_yen': (sum(UNIT_YEN * r['expected_value'] for r in selected)
                                     if all(r['expected_value'] is not None for r in selected) else None),
            'odds_complete': all(r['odds'] is not None for r in selected),
            'trifecta': analysis['trifecta'],
            'structure': analysis.get('conviction_structure'),
            'bridge': analysis.get('bridge_learning') if use_bridge else None}


def build_bundle(request, hiyori, source, now=None):
    now = aware(now or datetime.now(JST))
    day, jcd, rno = request['day'], str(request['jcd']).zfill(2), int(request['rno'])
    key = identity(day, jcd, rno)
    if not before_deadline(day, request['deadline'], now):
        raise ValueError('Prediction deadline has passed')
    captured = aware(request['captured_at'])
    fetched = aware(source['fetched_at'])
    if not captured <= fetched <= now or captured.strftime('%Y%m%d') != day:
        raise ValueError('Source timestamps do not precede prediction creation')
    base = request['official']
    if base.get('preview', {}).get('exhibition_count') != 6:
        raise ValueError('All six exhibition records are required')
    if not any(f.get('used') for f in hiyori.get('features', [])):
        raise ValueError('No actual Hiyori feature was used')
    def racers(analysis):
        return sorted((int(b['lane']), str(b['racer_id'])) for b in analysis['inputs'])
    if len(base['inputs']) != 6 or racers(base) != racers(hiyori):
        raise ValueError('The two models describe different entrants')
    if [lane for lane, _ in racers(base)] != list(range(1, 7)):
        raise ValueError('Six unique lanes are required')
    # One observed odds snapshot for every strategy; missing odds stay unknown.
    odds = {}
    for row in base['trifecta']:
        try:
            odd = float(row.get('odds'))
            if isfinite(odd) and odd > 0:
                odds[row['combination']] = odd
        except (ValueError, TypeError):
            pass
    models = {}
    for stream in STREAMS:
        a, b = WEIGHTS[stream]
        mixed = fuse(base['trifecta'], hiyori['trifecta'], a, b)
        parent = base if stream in ('existing', 'prototype1') else hiyori
        models[stream] = _card(mixed, parent, stream, odds)
    native = {}
    for stream, analysis in (('existing', base), ('hiyori', hiyori)):
        copied = deepcopy(analysis)
        selected = cards.displayed_picks_variable(copied, True)
        if stream == 'existing':
            selected = bridge_learning._reallocate(copied, selected)
        native[stream] = [r['combination'] for r in selected]
    record = {'version': VERSION, 'mode': 'prospective_shadow', 'key': key,
              'day': day, 'jcd': jcd, 'rno': rno, 'venue': base['venue'],
              'deadline': request['deadline'], 'captured_at': captured.isoformat(),
              'source_fetched_at': fetched.isoformat(), 'created_at': now.isoformat(),
              'code_sha': os.getenv('PROTOTYPE_CODE_SHA') or os.getenv('GITHUB_SHA'),
              'point_count': POINTS, 'unit_yen': UNIT_YEN,
              'source_models': {'existing': base.get('model_version'), 'hiyori': hiyori.get('model_version')},
              'source_url': source.get('source_url'), 'features': deepcopy(hiyori['features']),
              'models': models, 'native_candidate_picks': native,
              'comparison_note': 'Both controls use the shared input snapshot at 10 points; these are not Discord delivery receipts.'}
    record['digest'] = sha256(json.dumps(record, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return record


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        tmp.write((json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode())
        tmp.flush()
        os.fsync(tmp.fileno())
    os.replace(tmp.name, path)


def write_once(path, payload):
    """Publish atomically without overwriting a previously recorded prediction."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        tmp.write(payload)
        tmp.flush()
        os.fsync(tmp.fileno())
    try:
        os.link(tmp.name, path)
        return True
    except FileExistsError:
        return False
    finally:
        os.unlink(tmp.name)


def persist(record, request, source, hiyori):
    day_root = ROOT / record['day']
    archive = {'request': request, 'source': source, 'hiyori': hiyori,
               'bridge_state': bridge_learning._state(), 'record_digest': record['digest']}
    write_once(day_root/'snapshots'/f"{record['key']}.json.gz",
               gzip.compress(json.dumps(archive, ensure_ascii=False, sort_keys=True).encode(), mtime=0))
    path = day_root/'predictions'/f"{record['key']}.json"
    write_once(path, (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode())
    return read(path)


def evaluate(record, result, now=None):
    status = result.get('status')
    if status not in ('settled', 'void', 'special'):
        return None
    payouts = result.get('payouts') or {}
    if status == 'settled' and (not payouts or any(c not in COMBINATIONS or int(v) <= 0 for c, v in payouts.items())):
        raise ValueError('Official winning combinations are incomplete')
    refunds = set(map(int, result.get('refund_lanes') or []))
    models = {}
    for stream in STREAMS:
        picks = record['models'][stream]['picks']
        active, returned, refunded = [], 0, 0
        for pick in picks:
            if status == 'void' or refunds.intersection(map(int, pick.split('-'))):
                returned += UNIT_YEN
                refunded += UNIT_YEN
            elif status == 'special':
                returned += int(result['special_per_100'])
            else:
                active.append(pick)
                returned += int(payouts.get(pick, 0))
        winning = [c for c in active if c in payouts]
        stake = len(picks)*UNIT_YEN
        models[stream] = {'hit': bool(winning), 'winning_picks': winning,
                          'eligible': bool(active) and status == 'settled',
                          'stake_yen': stake, 'return_yen': returned, 'refund_yen': refunded,
                          'profit_yen': returned-stake, 'roi': 100*returned/stake,
                          'manshu': any(int(payouts[c]) >= 10000 for c in winning),
                          'torigami': bool(winning) and returned < stake}
    return {'key': record['key'], 'day': record['day'], 'venue': record['venue'],
            'version': VERSION, 'prediction_digest': record['digest'],
            'settled_at': aware(now or datetime.now(JST)).isoformat(),
            'official': result, 'models': models,
            'comparable': all(m['eligible'] for m in models.values())}


def summarize(day):
    root = ROOT/day
    predictions = [read(p) for p in sorted((root/'predictions').glob('*.json'))]
    by_key = {r['key']: r for r in predictions}
    results = [read(p) for p in sorted((root/'results').glob('*.json'))]
    results = [r for r in results if r['key'] in by_key and r['prediction_digest'] == by_key[r['key']]['digest']]
    cohort = [r for r in results if r['comparable']]
    totals = {}
    for stream in STREAMS:
        rows = [r['models'][stream] for r in cohort]
        hits = sum(r['hit'] for r in rows)
        stake = sum(r['stake_yen'] for r in rows)
        returned = sum(r['return_yen'] for r in rows)
        totals[stream] = {'label': LABELS[stream], 'judged': len(rows), 'hits': hits,
                          'hit_rate': 100*hits/len(rows) if rows else None,
                          'stake_yen': stake, 'return_yen': returned, 'profit_yen': returned-stake,
                          'roi': 100*returned/stake if stake else None,
                          'manshu': sum(r['manshu'] for r in rows),
                          'torigami': sum(r['torigami'] for r in rows)}
    pairs = {}
    for i, a in enumerate(STREAMS):
        for b in STREAMS[i+1:]:
            pairs[f'{a}_vs_{b}'] = {
                'both': sum(r['models'][a]['hit'] and r['models'][b]['hit'] for r in cohort),
                'a_only': [r['key'] for r in cohort if r['models'][a]['hit'] and not r['models'][b]['hit']],
                'b_only': [r['key'] for r in cohort if r['models'][b]['hit'] and not r['models'][a]['hit']],
                'neither': sum(not r['models'][a]['hit'] and not r['models'][b]['hit'] for r in cohort)}
    report = {'day': day, 'version': VERSION, 'mode': 'prospective_shadow',
              'generated_at': datetime.now(JST).isoformat(), 'point_count': POINTS, 'unit_yen': UNIT_YEN,
              'recorded': len(predictions), 'pending': len(predictions)-len(results),
              'excluded_refunds_void_special': len(results)-len(cohort),
              'cohort': [r['key'] for r in cohort], 'totals': totals, 'pairs': pairs}
    write_json(root/'summary.json', report)
    return report
