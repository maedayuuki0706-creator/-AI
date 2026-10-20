"""Measured support, historical follower associations and attributed context.

All additions are research hypotheses. Tide proxies and comments are never
silently converted into a measured current or an invented performance grade.
"""
from copy import deepcopy
from itertools import permutations
import re
from pathlib import Path

from .application import read_json
from research.capture_v1.parsers import textify
from research.scenario_v2 import engine as scenario


def comment_context(root, record):
    foot = record['foot_provenance']
    if not root or foot.get('status') != 'joined':
        return {'status': 'missing', 'reason': 'No verified same-race source', 'rows': []}
    from research.materials_v1.collector import Store
    store = Store(root)
    path = foot['raw_path']
    raw = store.body({'raw_path': path, 'sha256': foot['sha256']})
    section = textify(raw).split('選手コメント\n枠\n選手コメント', 1)[-1]
    matches = list(re.finditer(r'\n([1-6])\n([^\n]+)\n([^\n]+)選手のコメント履歴', section))
    boats = {b['lane']: b for b in record['all_six']}
    rows = []
    for m in matches:
        lane = int(m[1])
        if re.sub(r'\s+', '', m[3]) != re.sub(r'\s+', '', boats[lane]['name']):
            return {'status': 'excluded', 'reason': 'Comment name/lane mismatch', 'rows': []}
        quote = m[2]
        aspects = [word for word in ('伸び', '出足', '回り足', '乗り心地', '行き足', '起こし', 'ペラ', '調整') if word in quote]
        rows.append({'lane': lane, 'racer_id': boats[lane]['racer_id'], 'comment': quote,
                     'aspects_mentioned': aspects, 'observed_at': foot['observed_at'],
                     'source_url': foot['source_url'], 'source_sha256': foot['sha256'],
                     'use': 'Attributed corroboration or conflict for human/video review; no sentiment bonus'})
    if len(rows) != 6 or {r['lane'] for r in rows} != set(range(1, 7)):
        return {'status': 'missing', 'reason': 'Six current attributed comments unavailable', 'rows': []}
    return {'status': 'joined', 'rows': rows, 'used_as_numeric_grade': False}


def tide_context(root, snapshot, at):
    code = str(snapshot['meta']['jcd']).zfill(2)
    if code == '23':
        return {'status': 'not_applicable', 'reason': 'Freshwater venue; no tide score'}
    station = {'03': 'TK', '06': 'MI', '16': 'UN'}[code]
    if not root:
        return {'status': 'missing', 'station': station}
    year = snapshot['meta']['day'][:4]
    candidates = [Path(root) / 'tide_predictions' / f'{station}_{year}{ext}'
                  for ext in ('.json.gz.b64', '.json.gz', '.json')]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return {'status': 'missing', 'station': station}
    doc = read_json(path)
    acquisition = doc['acquisition']
    if scenario.aware(acquisition['retrieved_at']) > scenario.aware(at):
        return {'status': 'excluded', 'station': station, 'reason': 'Prediction acquired after generation'}
    expected = f'https://www.data.jma.go.jp/kaiyou/data/db/tide/suisan/txt/{year}/{station}.txt'
    if acquisition.get('url') != expected:
        return {'status': 'excluded', 'station': station, 'reason': 'Prediction station/year/source URL differs'}
    from research.materials_v1.collector import Store
    from research.materials_v1.supplement import tides
    hours, _ = tides(Store(root).body(acquisition), station)
    m = snapshot['meta']
    target = scenario.aware(f'{m["day"][:4]}-{m["day"][4:6]}-{m["day"][6:]}T{m["deadline"]}:00+09:00')
    hours = sorted((r for r in hours if r.get('height_cm') is not None), key=lambda r: r['at'])
    before = [r for r in hours if scenario.aware(r['at']) <= target]
    after = [r for r in hours if scenario.aware(r['at']) > target]
    if not before or not after:
        return {'status': 'missing', 'station': station, 'reason': 'No hourly bracket'}
    a, b = before[-1], after[0]
    gap = (scenario.aware(b['at']) - scenario.aware(a['at'])).total_seconds()
    if gap != 3600:
        return {'status': 'excluded', 'station': station, 'reason': 'Nonadjacent hourly predictions'}
    delta = b['height_cm'] - a['height_cm']
    fraction = (target - scenario.aware(a['at'])).total_seconds() / gap
    return {'status': 'joined_station_proxy', 'station': station, 'target_at': target.isoformat(),
            'height_cm_interpolated': round(a['height_cm'] + fraction * delta, 1),
            'phase_proxy': 'rising' if delta > 0 else 'falling' if delta < 0 else 'level',
            'bracket': [a, b], 'acquired_at': acquisition['retrieved_at'],
            'source_url': acquisition['url'], 'source_sha256': acquisition['sha256'],
            'measurement': 'astronomical_prediction_at_nearby_gauge',
            'race_surface_measured': False, 'current_velocity_known': False,
            'use': 'Freeze environmental cohort for subsequent review, no unvalidated physical bonus'}


def enrich(record, snapshot, materials, *, root=None):
    record['comments_context'] = comment_context(root, record)
    record['tide_context'] = tide_context(root, snapshot, record['assembled_at'])
    ranking = record['profile_baseline_ranking']
    candidates = {}
    courses = {b['lane']: b['predicted_course'] for b in record['all_six']}
    comments = {r['lane']: r for r in record['comments_context']['rows']}
    for boat in record['all_six']:
        boat['attributed_comment'] = comments.get(boat['lane'])
        if hasattr(materials, 'contexts_for'):
            boat['conditional_history_context'] = materials.contexts_for(boat['racer_id'],
                boat['predicted_course'], snapshot['meta']['jcd'], snapshot['meta']['day'],
                snapshot.get('environment', {}).get('wind_speed'))
        eligible = []
        for h in boat['hypotheses']:
            values = [t['support'] for t in h['conditions']]
            h['observation_status'] = ('contradicted_by_observation' if False in values else
                'all_measured_conditions_supported' if values and all(v is True for v in values) else
                'partial_support_missing_observations' if True in values else 'unobserved_hypothesis')
            h['actual_attack_verified'] = False
            if True in values and False not in values:
                eligible.append(h)
            if not hasattr(materials, 'follower_counts'):
                continue
            total, counts = materials.follower_counts(snapshot['meta']['jcd'], boat['predicted_course'], h['tactic'])
            ordered = []
            # Inspect all 20 second/third pairs; never hard-truncate a boat
            # before preserving the full six-boat hypothesis record.
            for second, third in permutations([n for n in range(1, 7) if n != boat['lane']], 2):
                count = counts.get((courses[second], courses[third]), 0)
                ordered.append({'combination': f'{boat["lane"]}-{second}-{third}',
                    'matching_races': count, 'cohort_races': total,
                    'observed_share': count / total if total else None,
                    'eligible_for_research_order': total >= 30 and count >= 3,
                    'attack_origin_verified': False})
            ordered.sort(key=lambda r: (-r['matching_races'], r['combination']))
            h['historical_follower_associations'] = ordered
            h['historical_association_note'] = 'Venue + winner course + official winning method; association, not proof of attack origin'
            if h['observation_status'] == 'all_measured_conditions_supported':
                for item in ordered:
                    if item['eligible_for_research_order']:
                        candidates.setdefault(item['combination'], []).append({
                            'hypothesis': h['id'], 'cohort_races': total,
                            'matching_races': item['matching_races'], 'share': item['observed_share']})
        eligible.sort(key=lambda h: (-int(h['observation_status'] == 'all_measured_conditions_supported'),
                                     -h['supported_observations'], h['id']))
        best = eligible[0] if eligible else None
        boat['strongest_observed_hypothesis'] = best['id'] if best else None
        boat['win_path'] = best['win_path'] if best else '観測で優先できる勝ち筋なし。矛盾・未観測の条件を全分岐に記録'
        boat['loss_path'] = best['loss_path'] if best else '内艇の壁・起点不成立・出口の競合を各分岐で確認'
        boat['linked_followers'] = best['reactions'] if best else []
    if hasattr(materials, 'follower_counts'):
        # Registered rule, not selected using retrospective returns. Retain the
        # six unchanged main-profile tickets and compare four association slots.
        keep = list(ranking[:6])
        position = {c: i for i, c in enumerate(ranking)}
        def order(c):
            evidence = candidates[c]
            return (-max(v['share'] for v in evidence), position.get(c, 120), c)
        selected = keep + [c for c in sorted(candidates, key=order) if c not in keep][:4]
        for c in ranking:
            if len(selected) >= 10:
                break
            if c not in selected:
                selected.append(c)
        record['model_cards']['profiles_contextual_followers'] = selected
        record['contextual_policy'] = {'id': 'retain-profile6-conditional4-v1',
            'cohort_minimum': 30, 'pair_minimum': 3,
            'requires_all_measured_branch_conditions': True, 'evidence': candidates,
            'unvalidated': True, 'probabilities_calibrated': False}
    record['data_use'].update(comments_and_tide='Attributed comments and frozen tide-proxy cohorts; no invented numeric grades',
        follower_associations='All twenty ordered follower pairs per head/tactic; separate unvalidated ten-ticket comparison')
    record['limitations'] = [v for v in record['limitations'] if 'comments and tide need' not in v]
    record['limitations'].extend(['Conditional follower counts do not identify the real attack origin',
        'Tide is a nearby astronomical prediction, not venue current velocity',
        'Comment aspects remain attributed evidence, not inferred numeric foot grades'])
    record['digest'] = scenario.digest({k: v for k, v in record.items() if k != 'digest'})
    return record
