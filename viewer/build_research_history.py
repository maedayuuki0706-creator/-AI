"""Offline, read-only adapters. Never import or execute production code.
Outcome/weather/exhibition data are retrospective, never prediction inputs.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import gzip
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
BOAT_FIELDS = ['day','venue','race','course','finish','st','lane','local_win','exhibition']


def number(value, low, high):
    if value is None or isinstance(value, bool) or value == '':
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) and low <= n <= high else None
    except (TypeError, ValueError):
        return None


def identity(day, venue, race):
    day = str(day).replace('-', '')
    try:
        datetime.strptime(day, '%Y%m%d')
        j = int(venue); r = int(race)
        if not re.fullmatch(r'20\d{6}', day) or not 1 <= j <= 24 or not 1 <= r <= 12:
            return None
        return day, f'{j:02}', r
    except (TypeError, ValueError):
        return None


def payout(combination, amount):
    if not isinstance(combination, str) or not re.fullmatch('[1-6]-[1-6]-[1-6]', combination) or len(set(combination.split('-'))) != 3:
        return None
    n = number(amount, 1, 999999999)
    return int(n) if n is not None and n.is_integer() else None


def emit(path, obj):
    content = json.dumps(obj, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode() + b'\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(content); temporary.replace(path)
    return len(content)


def build(source_root, audited_path, output, source_ref='', audit_ref=''):
    rows = {}; conflicts = set(); counts = Counter(); exclusions = Counter(); inputs = []
    players = defaultdict(dict)

    def remember(path):
        inputs.append({'path': str(path.relative_to(source_root)) if path.is_relative_to(source_root) else path.name,
                       'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})

    def add(key, combination, amount, meta):
        counts['source'] += 1
        if key is None:
            exclusions['invalid_identity'] += 1; return
        value = payout(combination, amount)
        if value is None:
            exclusions['invalid_payout'] += 1; return
        if key in conflicts:
            counts['conflicting_records'] += 1; return
        row = [*key, combination, value, meta]
        if key in rows:
            if rows[key][3:5] != row[3:5]:
                conflicts.add(key); del rows[key]; counts['conflicting_records'] += 2
            else:
                counts['duplicates'] += 1
                rows[key][5].update(meta)
        else:
            rows[key] = row

    if audited_path:
        remember(audited_path)
        audited = json.loads(gzip.decompress(audited_path.read_bytes()))
        if not isinstance(audited, list):
            raise ValueError('audited archive must be a list')
        for race in audited:
            key = identity(race.get('date'), race.get('venue_code'), race.get('race_no'))
            payouts = race.get('official_trifectas', [])
            if race.get('official_verified') is not True or len(payouts) != 1 or race.get('dead_heat_confirmed'):
                counts['source'] += 1; exclusions['unverified_or_multiple_payouts'] += 1; continue
            meta = {'wind': number(race.get('wind_m'), 0, 100), 'direction': race.get('wind_dir') or None,
                    'wave': number(race.get('wave_cm'), 0, 999), 'tide': None,
                    'entry_changed': race.get('entry_changed') if race.get('course_mapping_complete') else None,
                    'winner_course': race.get('winner_course'), 'method': race.get('method'),
                    'retrospective': True, 'source': 'official_K'}
            add(key, payouts[0].get('combination'), payouts[0].get('payout_per_100'), meta)
            if key is None: continue
            for boat in race.get('boats', []):
                rid = str(boat.get('racer_id', ''))
                if not re.fullmatch(r'\d{4}', rid): continue
                program = boat.get('program') or {}
                local = number(program.get('local_win_rate'), 0, 10) if str(program.get('racer_id')) == rid else None
                players[rid][key] = [*key, number(boat.get('course'), 1, 6), number(boat.get('finish'), 1, 6),
                                     number(boat.get('actual_st'), 0, 2), number(boat.get('lane'), 1, 6),
                                     local, number(boat.get('exhibition_time'), 3, 15)]

    for path in sorted((source_root / 'data/official_results').glob('*.json')):
        if not re.fullmatch(r'20\d{6}\.json', path.name): continue
        remember(path)
        data = json.loads(path.read_text())
        for name, record in data.items():
            parts = name.split(':')
            key = identity(path.stem, *parts) if len(parts) == 2 else None
            payouts = record.get('payouts') if isinstance(record, dict) else None
            if not isinstance(payouts, dict) or len(payouts) != 1 or record.get('status') != 'settled':
                counts['source'] += 1; exclusions['unsettled_or_multiple_payouts'] += 1; continue
            combination, amount = next(iter(payouts.items()))
            add(key, combination, amount, {'retrospective': True})

    # Enrich only exact matched, settled races. Never infer actual course from lane.
    for path in sorted((source_root / 'data/exhibition_log').glob('*/*.json')):
        remember(path)
        item = json.loads(path.read_text()); key = identity(item.get('day'), item.get('jcd'), item.get('rno'))
        if key not in rows or item.get('settled') is not True: continue
        boats = item.get('rows', [])
        if len(boats) != 6 or {b.get('lane') for b in boats} != set(range(1,7)):
            counts['invalid_exhibition_identity'] += 1; continue
        if any(identity(b.get('day'), b.get('jcd'), b.get('rno')) != key for b in boats):
            counts['invalid_exhibition_identity'] += 1; continue
        # A conflicting top three makes the entire enrichment untrusted.
        ordered = sorted((b for b in boats if b.get('finish') in (1,2,3)), key=lambda b:b['finish'])
        if len(ordered) != 3 or [b['finish'] for b in ordered] != [1,2,3] or '-'.join(str(b['lane']) for b in ordered) != rows[key][3]:
            counts['exhibition_result_conflicts'] += 1; continue
        counts['exhibition_joined'] += 1
        meta = rows[key][5]
        for src,dst,limit in [('wind_m','wind',100), ('wave_cm','wave',999)]:
            values = {number(b.get(src), 0, limit) for b in boats}
            if len(values) == 1 and None not in values:
                meta.setdefault(dst, next(iter(values)))
        courses = [b.get('actual_course') for b in boats]
        if set(courses) == set(range(1,7)):
            meta.setdefault('entry_changed', any(b['lane'] != b['actual_course'] for b in boats))
            meta.setdefault('winner_course', ordered[0]['actual_course'])
        for boat in boats:
            rid = str(boat.get('racer_id', ''))
            if not re.fullmatch(r'\d{4}', rid): continue
            if key not in players[rid]:
                players[rid][key] = [*key, number(boat.get('actual_course'),1,6), number(boat.get('finish'),1,6),
                                    number(boat.get('actual_st'),0,2), boat['lane'], None, number(boat.get('exhibition_time'),3,15)]
        meta.setdefault('method', ordered[0].get('method'))
    if not rows: raise ValueError('No valid results; previous manifest preserved')
    ordered = sorted(rows.values(), key=lambda r:(r[0],r[1],r[2]), reverse=True)
    months = defaultdict(list)
    for row in ordered: months[row[0][:6]].append(row)
    shards=[]; shard_info=[]
    for month, group in sorted(months.items()):
        digest=hashlib.sha256(json.dumps(group,ensure_ascii=False).encode()).hexdigest()[:12]
        name=f'{month}-{digest}'
        size=emit(output/'history'/f'{name}.json', {'rows':group,'counts':{'source':len(group),'skip':0}})
        shards.append(name);shard_info.append({'name':name,'from':min(r[0] for r in group),'to':max(r[0] for r in group),'rows':len(group),'bytes':size})
    buckets=defaultdict(dict)
    for rid, records in players.items():
        valid=[r for key,r in records.items() if key in rows]
        if valid: buckets[rid[:2]][rid]=sorted(valid,key=lambda r:(r[0],r[1],r[2]),reverse=True)
    player_files={}
    for bucket, records in sorted(buckets.items()):
        digest=hashlib.sha256(json.dumps(records,ensure_ascii=False).encode()).hexdigest()[:12]
        name=f'{bucket}-{digest}.json'
        emit(output/'research/players'/name, {'fields':BOAT_FIELDS,'data':records})
        player_files[bucket]=name
    missing={f:sum(r[5].get(f) is None for r in ordered) for f in ['wind','direction','wave','tide','entry_changed','winner_course']}
    report={'schema':'research-quality-v1','source_ref':source_ref,'audit_ref':audit_ref,'counts':dict(counts),
            'exclusions':dict(exclusions),'conflict_races':[list(k) for k in sorted(conflicts)],'indexed':len(ordered),
            'from':ordered[-1][0],'to':ordered[0][0],'missing_races':missing,
            'player_records':sum(len(r) for v in buckets.values() for r in v.values()),
            'players':sum(len(v) for v in buckets.values()),'inputs':inputs,
            'notes':['Saved confirmed single trifecta results only; not all venues or all scheduled races.',
                     'All outcome/weather/exhibition data are retrospective; never use as pre-race model input.',
                     'Tide, observation station/time/unit linkage, stabilizer and shortened distance are unavailable.']}
    emit(output/'research/quality.json',report)
    emit(output/'research/manifest.json',{'schema':'research-player-v1','from':report['from'],'to':report['to'],
                                         'players':player_files,'counts':{'players':report['players'],'records':report['player_records']}})
    emit(output/'history/manifest.json',{'schema':'race-history-manifest-v2','from':report['from'],'to':report['to'],
          'shards':shards,'shard_info':shard_info,'counts':{'source':counts['source'],'indexed':len(ordered),
          'skip':sum(exclusions.values()),'duplicates':counts['duplicates'],'conflicts':len(conflicts)},
          'source_ref':source_ref,'audit_ref':audit_ref,'notes':report['notes']})
    return {k:v for k,v in report.items() if k!='inputs'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source-root',type=Path,required=True);p.add_argument('--audited',type=Path)
    p.add_argument('--output',type=Path,default=ROOT/'data');p.add_argument('--source-ref',default='');p.add_argument('--audit-ref',default='')
    a=p.parse_args();print(json.dumps(build(a.source_root,a.audited,a.output,a.source_ref,a.audit_ref),ensure_ascii=False,indent=2))
