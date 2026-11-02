"""As-of integration over the existing fusion and Yuuki scenario engines.
No network, production imports, betting or notifications. Scores are not probability.
"""
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import json
from research.ultimate_fusion_v1 import engine as v1
from research.scenario_v2 import engine as scenario
from research.venue24_v1.engine import VENUES

VERSION = 'ultimate-fusion-asof-v2.0'
# Explicit field projection prevents outcome leakage and accidental new features.
FIELDS = {
 'national_win_rate': (0,10), 'local_win_rate': (0,10),
 'course_win_rate': (0,100), 'escape_rate': (0,100), 'let_escape_rate': (0,100),
 'sashi_rate': (0,100), 'makuri_rate': (0,100), 'makurisashi_rate': (0,100),
 'avg_st': (0,1), 'meet_st': (0,1), 'lap_time': (.001,100),
 'half_lap_time': (.001,100), 'turn_time': (.001,100), 'straight_time': (.001,100),
 'motor_top2_rate': (0,100), 'wind_m': (0,60), 'wind_direction': (0,360),
 'wave_cm': (0,300), 'tide_cm': (-1000,2000),
}
MOTOR_FIELDS = {'motor_top2_rate'}


def integrate(snapshot, observations):
    """Join field observations at prediction time, with full rejected audit trail.

    An allowlisted domain is necessary, not proof of provenance: collector receipts
    and immutable Git checkpoints are required separately for prospective claims.
    """
    at = v1.aware(snapshot['snapshot_at'])
    known = {b['lane']: b for b in snapshot['boats']}
    selected, audit = {}, []
    for item in observations:
        reason = None
        try:
            field, lane = item['field'], int(item['lane'])
            if field not in FIELDS or lane not in known:
                raise ValueError('unsupported_field_or_lane')
            if item['race_id'] != snapshot['race_id'] or str(item['racer_id']) != str(known[lane]['racer_id']):
                raise ValueError('identity_mismatch')
            host = urlparse(item['source_url']).hostname or ''
            if not (host == 'boatrace.jp' or host.endswith('.boatrace.jp') or host == 'boatrace-karatsu.jp' or host.endswith('.boatrace-karatsu.jp')):
                raise ValueError('source_not_verified')
            retrieved = v1.aware(item['retrieved_at'])
            available = v1.aware(item['available_at'])
            published = v1.aware(item['published_at']) if item.get('published_at') else None
            if available < retrieved or available > at or (published and published > retrieved):
                raise ValueError('future_or_inconsistent_time')
            if field in MOTOR_FIELDS and (not item.get('motor_cycle') or str(item.get('motor_number')) != str(known[lane].get('motor_number'))):
                raise ValueError('motor_cycle_or_number_missing')
            value = v1.number(item.get('value'), *FIELDS[field])
            if value is None:
                raise ValueError('missing_or_invalid_measurement')
            key = (lane, field)
            candidate = {**item, 'value': value}
            prior = selected.get(key)
            if prior is not None and v1.aware(prior['available_at']) == available and prior['value'] != value:
                raise ValueError('conflicting_same_time_values')
            if prior is None or v1.aware(prior['available_at']) < available:
                selected[key] = candidate
        except (ValueError, TypeError, KeyError) as exc:
            reason = str(exc)
        audit.append({'sha256': v1.digest(item), 'accepted': reason is None, 'reason': reason})
    # Conflicts fail closed for the affected field rather than selecting arbitrary input order.
    conflicts = { (int(i['lane']),i['field']) for i,a in zip(observations,audit)
                  if a['reason'] == 'conflicting_same_time_values' }
    for key in conflicts:
        selected.pop(key, None)
    boats = []
    for lane,b in sorted(known.items()):
        row = {**b, **{f: selected[(lane,f)]['value'] if (lane,f) in selected else b.get(f) for f in FIELDS}}
        row['missing_fields'] = [f for f in FIELDS if row[f] is None]
        boats.append(row)
    return {'boats':boats, 'provenance':[selected[k] for k in sorted(selected)], 'audit':audit}


def fit(records, target_day, code):
    """Previous dates only, with result availability before target-day midnight."""
    cutoff = v1.aware(f'{target_day[:4]}-{target_day[4:6]}-{target_day[6:]}T00:00:00+09:00')
    triples, starts, seen, accepted = Counter(), defaultdict(list), set(), []
    for r in sorted(records, key=lambda r: (str(r.get('day','')), str(r.get('rno','')))):
        try:
            if r['day'] >= target_day or not r.get('settled'):
                continue
            if v1.aware(r['settled_at']) >= cutoff:
                continue
            key = v1.identity(r['day'],r['jcd'],r['rno'])
            if key in seen:
                continue
            v1.boats_six(r['rows'])
            if sorted(b['finish'] for b in r['rows']) != list(range(1,7)):
                continue
            seen.add(key)
            ordered=sorted(r['rows'],key=lambda b:b['finish'])
            if str(r['jcd']).zfill(2) == code:
                triples['-'.join(str(b['lane']) for b in ordered[:3])] += 1
                accepted.append(key)
            for b in r['rows']:
                st=v1.number(b.get('actual_st'),0,1)
                if st is not None:
                    starts[str(b['racer_id'])].append(st)
        except (KeyError,ValueError,TypeError):
            continue
    # Dirichlet smoothing is an internal categorical baseline, never a calibrated claim.
    weights={c:triples[c]+1 for c in v1.COMBOS}
    return {'target_day':target_day,'venue_code':code,'training_races':len(accepted),
            'training_ids_sha256':v1.digest(sorted(accepted)), 'counts':dict(triples),
            'weights':weights,'avg_st':{k:sum(v)/len(v) for k,v in starts.items() if len(v)>=5},
            'st_samples':{k:len(v) for k,v in starts.items()}, 'calibrated':False}


def predict(snapshot, model, observations=(), *, now, mode='live'):
    if model['target_day'] != snapshot['day'] or model['venue_code'] != snapshot['venue_code']:
        raise ValueError('model_scope_mismatch')
    expected=v1.digest({'race_id':snapshot['race_id'],'captured_at':snapshot['snapshot_at'],'boats':snapshot['boats']})
    if expected != snapshot['sha256']:
        raise ValueError('snapshot_digest_mismatch')
    if mode == 'live' and (v1.aware(now)-v1.aware(snapshot['snapshot_at'])).total_seconds()>180:
        raise ValueError('stale_live_snapshot')
    joined=integrate(snapshot,list(observations))
    boats=[]
    for b in joined['boats']:
        course=b.get('exhibition_course')
        if course is None:
            raise ValueError('missing_entry_no_silent_lane_fallback')
        boats.append({**{k:b.get(k) for k in ('lane','racer_id','name','exhibition_time','lap_time','turn_time','straight_time','motor_top2_rate')},
                      'course':course,'avg_st':b['avg_st'] if b['avg_st'] is not None else model['avg_st'].get(str(b['racer_id']))})
    ranking=sorted(v1.COMBOS,key=lambda c:(-model['weights'][c],c))
    data={'meta':{'day':snapshot['day'],'jcd':snapshot['venue_code'],'rno':snapshot['race_no'],
                 'deadline':v1.aware(snapshot['deadline_at']).strftime('%H:%M'),'captured_at':snapshot['snapshot_at']},
          'boats':boats,'baseline_picks':ranking[:10],'baseline_ranking':ranking,
          'source':{'snapshot_sha256':snapshot['sha256'],'model_digest':v1.digest(model)}}
    flow=scenario.generate(data,now=now,mode=mode)
    # Reuse Yuuki's six-head tactics / origin / reaction / conditional follower logic.
    chosen=flow['virtual_card']['picks']
    rows=[{'combination':c,'research_score':model['weights'][c],
           'selected_by_flow':c in chosen,'probability':None,'expected_value':None} for c in ranking]
    result={'schema':VERSION,'race_id':snapshot['race_id'],'venue':VENUES[snapshot['venue_code']]['name'],
            'mode':flow['mode'],'generated_at':flow['generated_at'],'snapshot':snapshot,
            'features':joined,'scenario':flow,'trifecta':rows,'baseline_picks':ranking[:10],
            'research_picks':chosen,'training_races':model['training_races'],
            'model_sha256':v1.digest(model),'probabilities_calibrated':False,'decision':'見送り',
            'probability_status':'未校正：研究スコアのみ。確率・期待値・購入推奨は非表示',
            'ready_for_betting':False,'entry_note':'展示進入を仮定。本番進入の確率モデルは未実装'}
    result['sha256']=v1.digest(result)
    return result


def save_immutable(report, directory):
    """Exclusive first write. Replays have separate namespace; no overwrite."""
    if report['sha256'] != v1.digest({k:v for k,v in report.items() if k!='sha256'}):
        raise ValueError('digest_mismatch')
    namespace='replay' if report['mode']=='retrospective_replay' else 'prospective_uncheckpointed'
    path=Path(directory)/namespace/(report['race_id']+'.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    body=json.dumps(report,ensure_ascii=False,sort_keys=True,allow_nan=False)+'\n'
    try:
        with path.open('x') as f:f.write(body)
    except FileExistsError:
        if path.read_text()!=body:raise ValueError('immutable_prediction_conflict')
    return path
