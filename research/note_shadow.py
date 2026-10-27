"""Read-only, note-inspired prequential replay of delivered boat-race predictions.

No network requests, wager placement, sheet writes, Discord or X imports.
Reads frozen predictions, matching delivery receipts, and settled official results.
Writes JSON only to an explicitly chosen separate output directory.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import permutations
import json
import math
from pathlib import Path

VERSION = 'note-prob-ev-shadow-v1'
TICKETS = {'-'.join(map(str, t)) for t in permutations(range(1, 7), 3)}
EXPONENTS = (0.65, 0.8, 1.0, 1.25, 1.5, 1.8, 2.2)
MIN_TRAIN = 100
HOLD_DAYS = 30


def read(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def as_time(value):
    date = datetime.fromisoformat(value)
    if date.tzinfo is None or date.utcoffset() is None:
        raise ValueError('timezone required')
    return date


def probs(rows):
    result = {}
    for entry in rows:
        combo = entry.get('combination')
        p = float(entry['probability'])
        if combo not in TICKETS or combo in result or not math.isfinite(p) or p < 0:
            raise ValueError('invalid distribution')
        result[combo] = p
    if set(result) != TICKETS or not 0.995 <= sum(result.values()) <= 1.005:
        raise ValueError('incomplete distribution')
    total = sum(result.values())
    return {c: p / total for c, p in result.items()}


def calibrated(p, exponent):
    values = {c: x ** exponent for c, x in p.items()}
    total = sum(values.values())
    return {c: x / total for c, x in values.items()}


def load_samples(root):
    root = Path(root)
    samples, excluded = [], defaultdict(int)
    streams = (
        ('pt1', root / 'data/prototype12_delivery/predictions', 'prototype1',
         root / 'data/prototype12_delivery/deliveries/prototype1'),
        ('pt2', root / 'data/prototype12_delivery/predictions', 'prototype2',
         root / 'data/prototype12_delivery/deliveries/prototype2'),
        ('yuuki', root / 'data/prototype3_delivery/predictions', 'model',
         root / 'data/prototype3_delivery/deliveries'),
    )
    for name, folder, model_key, receipt_folder in streams:
        for path in sorted(folder.glob('*.json')):
            raw = read(path)
            if not isinstance(raw, dict):
                excluded['invalid_forecast'] += 1
                continue
            key = str(raw.get('key') or '')
            if path.stem != key or len(key) != 14:
                excluded['invalid_identity'] += 1
                continue
            receipt = read(receipt_folder / (key + '.json'))
            if not isinstance(receipt, dict) or receipt.get('key') != key or receipt.get('prediction_digest') != raw.get('digest'):
                excluded['missing_matching_receipt'] += 1
                continue
            try:
                cutoff = as_time(f"{raw['day'][:4]}-{raw['day'][4:6]}-{raw['day'][6:8]}T{raw['deadline']}:00+09:00")
                created = as_time(raw['created_at'])
                delivered = as_time(receipt['delivered_at'])
                if not (created <= delivered < cutoff):
                    raise ValueError('not frozen')
                model = raw[model_key] if model_key == 'model' else raw['models'][model_key]
                p = probs(model['trifecta'])
                odds = {}
                for item in model['trifecta']:
                    v = item.get('odds')
                    if v is not None and math.isfinite(float(v)) and float(v) > 1:
                        odds[item['combination']] = float(v)
            except (ValueError, KeyError, TypeError, OverflowError):
                excluded['invalid_or_late_forecast'] += 1
                continue
            official = read(root / 'data/prototype_scoreboard' / raw['day'] / 'official' / (key + '.json'))
            if not isinstance(official, dict) or official.get('status') != 'settled' or official.get('refund_lanes'):
                excluded['no_clean_official_result'] += 1
                continue
            payouts = official.get('payouts') or {}
            if len(payouts) != 1 or next(iter(payouts)) not in TICKETS:
                excluded['nonstandard_official_result'] += 1
                continue
            winner, payout = next(iter(payouts.items()))
            if not isinstance(payout, int) or payout < 100:
                excluded['invalid_payout'] += 1
                continue
            version = model.get('model_version') or (receipt.get('model_version') if name == 'pt2' else None) or 'unspecified'
            samples.append({'day': raw['day'], 'key': key, 'model': name, 'version': version,
                            'winner': winner, 'payout_yen': payout, 'probabilities': p, 'odds': odds,
                            'snapshot_at': created.isoformat(), 'delivered_at': delivered.isoformat(),
                            'prediction_digest': raw['digest'],
                            'native_picks': [c for c in model.get('picks', []) if c in TICKETS]})
    return sorted(samples, key=lambda r: (r['day'], r['key'], r['model'])), dict(excluded)


def choose_exponent(history, today, min_train=MIN_TRAIN):
    start = datetime.strptime(today, '%Y%m%d') - timedelta(days=HOLD_DAYS)
    past = [r for r in history if start <= datetime.strptime(r['day'], '%Y%m%d') < datetime.strptime(today, '%Y%m%d')]
    if len(past) < min_train:
        return 1.0, len(past), False
    scored = []
    for e in EXPONENTS:
        loss = sum(-math.log(max(calibrated(r['probabilities'], e)[r['winner']], 1e-15)) for r in past)
        scored.append((loss, abs(e - 1), e))
    return min(scored)[-1], len(past), True


def select(p, odds):
    prob10 = sorted(p, key=lambda c: (-p[c], c))[:10]
    rated = sorted((c for c in odds if c in p), key=lambda c: (-p[c] * odds[c], c))
    gate = [c for c in rated if p[c] * odds[c] * 0.85 > 1.0][:10]
    return {'prob_10': prob10, 'ev_10': rated[:10], 'ev_gate_85': gate}


def replay(samples, min_train=MIN_TRAIN):
    # Only completed earlier days can train today's temperature; prevent same-day leakage.
    by_day = defaultdict(list)
    for item in samples:
        by_day[item['day']].append(item)
    history = defaultdict(list)
    rows = []
    for day in sorted(by_day):
        pending = defaultdict(list)
        daily_calibration = {}
        for r in by_day[day]:
            identity = (r['model'], r['version'])
            if identity not in daily_calibration:
                daily_calibration[identity] = choose_exponent(history[identity], day, min_train)
            exp, ntrain, fitted = daily_calibration[identity]
            raw, cal = r['probabilities'], calibrated(r['probabilities'], exp)
            strategies = {}
            for tag, dist in (('raw', raw), ('cal', cal)):
                for policy, tickets in select(dist, r['odds']).items():
                    name = tag + '_' + policy
                    strategies[name] = {'picks': tickets, 'tickets': len(tickets),
                                        'stake_yen': 100 * len(tickets),
                                        'return_yen': r['payout_yen'] if r['winner'] in tickets else 0,
                                        'hit': r['winner'] in tickets,
                                        'manshu_hit': r['payout_yen'] >= 10000 and r['winner'] in tickets}
            native = list(dict.fromkeys(r.get('native_picks') or []))
            strategies['native_logged'] = {'picks': native, 'tickets': len(native),
                    'stake_yen': 100*len(native),
                    'return_yen': r['payout_yen'] if r['winner'] in native else 0,
                    'hit': r['winner'] in native,
                    'manshu_hit': r['payout_yen'] >= 10000 and r['winner'] in native}
            rows.append({'day': day, 'key': r['key'], 'model': r['model'], 'model_version': r['version'],
                         'training_prior_races': ntrain, 'calibration_fitted': fitted,
                         'calibration_exponent': exp, 'raw_log_loss': -math.log(max(raw[r['winner']], 1e-15)),
                         'cal_log_loss': -math.log(max(cal[r['winner']], 1e-15)),
                         'winning_combination': r['winner'], 'official_payout_yen': r['payout_yen'],
                         'winning_snapshot_odds': r['odds'].get(r['winner']),
                         'winning_settlement_odds': r['payout_yen'] / 100,
                         'strategies': strategies})
            pending[identity].append(r)
        for identity, newrows in pending.items():
            history[identity].extend(newrows)
    return rows


def summarize(rows, excluded):
    groups = defaultdict(lambda: {'races': 0, 'bet_races': 0, 'hits': 0, 'manshu_hits': 0, 'stake_yen': 0, 'return_yen': 0})
    for r in rows:
        for policy, s in r['strategies'].items():
            item = groups[(r['model'], r['model_version'], policy)]
            item['races'] += 1
            item['bet_races'] += int(bool(s['tickets']))
            item['hits'] += int(s['hit'])
            item['manshu_hits'] += int(s['manshu_hit'])
            item['stake_yen'] += s['stake_yen']
            item['return_yen'] += s['return_yen']
    report = []
    for key, d in sorted(groups.items()):
        report.append({**dict(zip(('model', 'model_version', 'policy'), key)), **d,
                      'hit_rate_pct': round(100*d['hits']/d['bet_races'], 2) if d['bet_races'] else None,
                      'roi_pct': round(100*d['return_yen']/d['stake_yen'], 2) if d['stake_yen'] else None})
    return {'version': VERSION, 'mode': 'offline_replay', 'research_only': True,
            'valid_model_races': len(rows), 'excluded': excluded, 'metrics': report,
            'warning': 'Historical replay is not live shadow performance. No causal claim or guaranteed edge.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, default=Path('.'))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--min-train', type=int, default=MIN_TRAIN)
    args = parser.parse_args()
    samples, excluded = load_samples(args.repo)
    rows = replay(samples, min_train=args.min_train)
    report = summarize(rows, excluded)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    (args.out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'valid_model_races': len(rows), 'excluded': excluded, 'summary': str(args.out / 'summary.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
