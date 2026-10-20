"""Independent AFTER-generation review. Producer never imports this module."""
import argparse
from collections import Counter
import json
from pathlib import Path

from .application import read_json, clock
from research.scenario_v2 import engine as scenario


def review(frozen, result):
    scenario.verify(frozen)
    if frozen['race_id'] != result.get('race_id'):
        raise ValueError('Outcome race identity differs')
    observed = (result.get('acquisition') or {}).get('retrieved_at')
    if not observed or scenario.aware(observed) < scenario.aware(frozen['deadline_at']):
        raise ValueError('Outcome must be observed after the deadline')
    details, payout = result.get('details'), result.get('payout', {})
    if not details or payout.get('status') != 'settled':
        return {'race_id': frozen['race_id'], 'status': 'excluded', 'reason': 'unsettled or incomplete'}
    finish = details.get('finish', [])
    if payout.get('refund_lanes') or any(b.get('status') != 'finished' for b in finish):
        return {'race_id': frozen['race_id'], 'status': 'excluded', 'reason': 'refund or accident'}
    if len(finish) != 6 or {int(b['finish']) for b in finish} != set(range(1, 7)):
        raise ValueError('Need six distinct normal finishing positions')
    expected = {b['lane']: str(b['racer_id']) for b in frozen['all_six']}
    if {b['lane']: str(b['racer_id']) for b in finish} != expected:
        raise ValueError('Outcome six-boat identity differs')
    ordered = sorted(finish, key=lambda b: int(b['finish']))
    actual = '-'.join(str(b['lane']) for b in ordered[:3])
    if actual != details['trifecta']:
        raise ValueError('Outcome finishing order and trifecta disagree')
    returned = scenario.integer(details['payout_per_100'], 1, 10**9)
    one, two, _ = actual.split('-')
    models = {}
    for name, card in frozen['model_cards'].items():
        hit = actual in card
        failure = ('hit' if hit else 'head_not_selected' if not any(c.startswith(one + '-') for c in card)
                   else 'second_not_selected' if not any(c.startswith(one + '-' + two + '-') for c in card)
                   else 'third_not_selected')
        models[name] = {'hit': hit, 'stake_yen': 1000, 'return_yen': returned if hit else 0,
                        'selection_stage': failure}
    original_course = {b['lane']: b['predicted_course'] for b in frozen['all_six']}
    changes = [{'lane': b['lane'], 'exhibition_course': original_course[b['lane']],
                'actual_course': b['course']}
               for b in finish if b['course'] != original_course[b['lane']]]
    return {'race_id': frozen['race_id'], 'status': 'graded_retrospective_only',
            'forecast_digest': frozen['digest'], 'actual_trifecta': actual,
            'models': models, 'entry_changes': changes,
            'actual_tactics_verified': False, 'count_as_prospective': False,
            'note': 'Selection-stage failure and observed entry changes are not a full 1M causal explanation'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--forecasts', required=True, type=Path)
    p.add_argument('--results', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    a = p.parse_args()
    rows, totals, excluded = [], {}, []
    for path in sorted(a.forecasts.glob('20*_*.json')):
        result = a.results / path.name
        if not result.exists():
            excluded.append({'race_id': path.stem, 'reason': 'outcome missing'})
            continue
        row = review(read_json(path), read_json(result))
        if row['status'] == 'excluded':
            excluded.append(row)
            continue
        rows.append(row)
        for name, value in row['models'].items():
            total = totals.setdefault(name, {'races': 0, 'hits': 0, 'stake_yen': 0,
                                            'return_yen': 0, 'selection_stages': Counter()})
            total['races'] += 1
            total['hits'] += value['hit']
            total['stake_yen'] += value['stake_yen']
            total['return_yen'] += value['return_yen']
            total['selection_stages'][value['selection_stage']] += 1
    for total in totals.values():
        total['roi_pct'] = round(100 * total['return_yen'] / total['stake_yen'], 2)
        total['hit_rate_pct'] = round(100 * total['hits'] / total['races'], 2)
    report = {'version': 'materials-application-independent-review-v1', 'generated_at': clock(),
              'status': 'retrospective_only', 'prospective_races': 0,
              'graded_races': len(rows), 'models': totals,
              'entry_changed_races': sum(bool(r['entry_changes']) for r in rows),
              'rows': rows, 'excluded': excluded,
              'interpretation': 'Small post-race diagnostic; do not claim improvement or select a model from these returns'}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open('x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('rows',)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
