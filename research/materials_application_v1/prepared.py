"""Small, provenance-preserving features for future isolated research runs.

The acquired archive remains retrospective. Compilation makes its historical
features available from *now*, never backdates an acquisition receipt.
"""
import argparse
import base64
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
import gzip
from hashlib import sha256
import json
from pathlib import Path

from .application import Materials, read_json, clock
from research.scenario_v2 import engine as scenario

FIELDS = ('racer_id', 'dimension', 'group', 'denominator', 'wins', 'top2_count',
          'top3_count', 'mean_actual_st', 'st_denominator', 'winning_methods',
          'period_start', 'period_end')
SEED = Path(__file__).with_name('seed.json.gz.b64')


def compile_seed(root, destination, *, at=None):
    root, destination = Path(root), Path(destination)
    source = Materials(root)
    profiles = [[row.get(k) for k in FIELDS] for row in source.context_rows.values()]
    motors = []
    for (venue, number), rows in sorted(source.motor_histories.items()):
        groups = defaultdict(list)
        for row in rows:
            if row.get('cycle_id'):
                groups[row['cycle_id']].append(row)
        for cycle, group in sorted(groups.items()):
            motors.append([venue, number, cycle, len(group), sum(r['finish'] <= 2 for r in group),
                           sum(r['finish'] <= 3 for r in group), min(r['day'] for r in group),
                           max(r['day'] for r in group)])
    association_path = root / 'derived/result_course_associations.json'
    associations = read_json(association_path)['rows']
    pairs = [[r['venue_code'], int(r['winner_actual_course']), r['official_winning_method'],
              int(r['second_actual_course']), int(r['third_actual_course']), int(r['count'])]
             for r in associations]
    sources = deepcopy(source.sources)
    sources['result_course_associations'] = {'file': 'derived/result_course_associations.json',
        'sha256': sha256(association_path.read_bytes()).hexdigest(), 'groups': len(pairs)}
    value = {'schema': 'future-research-features-v1', 'compiled_at': at or clock(),
             'through_day': max(r['period_end'] for r in source.context_rows.values()),
             'sources': sources, 'profile_fields': FIELDS, 'profiles': profiles,
             'motor_periods': motors, 'ordered_follower_counts': pairs,
             'source_historical_prospective_receipts': False,
             'usage': 'New future research only; source retrospective flags are not predeadline receipts'}
    raw = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(base64.b64encode(gzip.compress(raw, mtime=0)))
    manifest = {k: v for k, v in value.items() if k not in ('profiles', 'motor_periods', 'ordered_follower_counts')}
    manifest.update(profile_groups=len(profiles), motor_period_groups=len(motors),
                    ordered_follower_groups=len(pairs), seed_sha256=sha256(destination.read_bytes()).hexdigest(),
                    compressed_bytes=destination.stat().st_size)
    destination.with_name('seed_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest


class PreparedMaterials:
    def __init__(self, path=SEED, *, at=None, results_root=None):
        path = Path(path)
        manifest = read_json(path.with_name('seed_manifest.json'))
        if sha256(path.read_bytes()).hexdigest() != manifest['seed_sha256']:
            raise ValueError('Compiled historical feature hash differs')
        data = read_json(path)
        self.loaded_at = at or clock()
        if scenario.aware(self.loaded_at) < scenario.aware(data['compiled_at']):
            raise ValueError('Compiled features did not exist at generation')
        self.available_from = data['compiled_at']
        self.through_day = data['through_day']
        self.latest_history_observed_at = scenario.aware(data['compiled_at'])
        self.sources = {**data['sources'], 'compiled_seed': {
            'sha256': manifest['seed_sha256'], 'available_from': data['compiled_at'],
            'historical_prospective_receipts': False}}
        self.context_rows = {}
        for values in data['profiles']:
            row = dict(zip(data['profile_fields'], values))
            self.context_rows[(str(row['racer_id']), row['dimension'], str(row['group']))] = row
        self.motor_periods = data['motor_periods']
        self.pairs = data['ordered_follower_counts']
        self.updates = []
        if results_root:
            from research.materials_v1.collector import Store, url, parsers
            result_store = Store(results_root)
            # Only earlier *days* and observations already available to this
            # process can enter later features. No current target results.
            for p in sorted((Path(results_root) / 'results').glob('20*.json')):
                if p.stem[:8] >= scenario.aware(self.loaded_at).strftime('%Y%m%d'):
                    continue  # producer never opens any current-day outcome
                record = read_json(p)
                observed = (record.get('acquisition') or {}).get('retrieved_at')
                day = datetime.strptime(record['race_id'][:8], '%Y%m%d').date().isoformat()
                if day <= self.through_day or not observed or scenario.aware(observed) > scenario.aware(self.loaded_at):
                    continue
                rid_day, code, rno = record['race_id'].split('_')
                acquisition = record.get('acquisition') or {}
                if acquisition.get('url') != url('raceresult', rid_day, code, int(rno)):
                    continue
                raw = result_store.body(acquisition)
                record['details'] = parsers.parse_result(raw, rid_day, code, int(rno))
                record['payout'] = parsers.parse_payout(raw)
                details = record.get('details') or {}
                finish = details.get('finish') or []
                if (len(finish) != 6 or record.get('payout', {}).get('status') != 'settled'
                        or record.get('payout', {}).get('refund_lanes')
                        or any(b.get('status') != 'finished' for b in finish)
                        or {b.get('finish') for b in finish} != set(range(1, 7))
                        or {b.get('lane') for b in finish} != set(range(1, 7))
                        or {b.get('course') for b in finish} != set(range(1, 7))):
                    continue
                self.updates.append((day, record))

    def profile(self, racer, course, target_day):
        day = datetime.strptime(target_day, '%Y%m%d').date().isoformat()
        if day <= self.through_day:
            raise ValueError('Prepared live aggregate cannot predict its own or earlier period')
        row = deepcopy(self.context_rows.get((str(racer), 'course', str(course))))
        if row is None:
            row = dict(racer_id=str(racer), denominator=0, wins=0, top2_count=0, top3_count=0,
                       mean_actual_st=None, st_denominator=0, winning_methods={},
                       period_start=None, period_end=None)
        for observed_day, record in self.updates:
            if observed_day >= day:
                continue
            for boat in record['details']['finish']:
                if str(boat['racer_id']) != str(racer) or int(boat['course']) != int(course):
                    continue
                row['denominator'] += 1
                row['wins'] += boat['finish'] == 1
                row['top2_count'] += boat['finish'] <= 2
                row['top3_count'] += boat['finish'] <= 3
                st = boat.get('st')
                if st is not None and 0 <= float(st) <= 1:
                    count = row['st_denominator'] or 0
                    row['mean_actual_st'] = ((row['mean_actual_st'] or 0) * count + float(st)) / (count + 1)
                    row['st_denominator'] = count + 1
                method = record['details'].get('method')
                if boat['finish'] == 1 and method:
                    row['winning_methods'][method] = row['winning_methods'].get(method, 0) + 1
                row['period_start'] = min(row['period_start'] or observed_day, observed_day)
                row['period_end'] = max(row['period_end'] or observed_day, observed_day)
        n = row['denominator']
        if not 0 <= row['wins'] <= row['top2_count'] <= row['top3_count'] <= n:
            raise ValueError('Invalid compiled counts')
        if sum(row['winning_methods'].values()) > row['wins']:
            raise ValueError('Invalid compiled method counts')
        row.update(methods_known=True, sample_status='small_sample' if n < 30 else 'descriptive_only',
                   population='four selected venues only')
        return row

    def motor_context(self, venue, number, target_day):
        day = datetime.strptime(target_day, '%Y%m%d').date().isoformat()
        return {'current_cycle_verified': False, 'model_fields_applied': [],
                'reason': 'Same-number motors are separate generations; no unverified current-cycle bonus',
                'separate_periods': [dict(cycle_id=r[2], starts=r[3], top2_count=r[4],
                    top3_count=r[5], first_race_day=r[6], last_race_day=r[7])
                    for r in self.motor_periods if r[0] == str(venue).zfill(2)
                    and r[1] == int(number) and r[7] < day]}

    def contexts_for(self, racer, course, venue, target_day, wind):
        month = int(target_day[4:6])
        season = (month % 12) // 3
        bucket = 'missing' if wind is None else '0-1' if wind <= 1 else '2-3' if wind <= 3 else '4-5' if wind <= 5 else '6+'
        return {dimension: deepcopy(self.context_rows.get((str(racer), dimension, group)))
                for dimension, group in [('venue_course', f'{str(venue).zfill(2)}:{course}'),
                    ('season_course', f'{season}:{course}'), ('wind_course', f'{bucket}:{course}') ]}

    def follower_counts(self, venue, course, method):
        rows = [r for r in self.pairs if r[:3] == [str(venue).zfill(2), int(course), method]]
        return sum(r[5] for r in rows), {(r[3], r[4]): r[5] for r in rows}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--materials', required=True, type=Path)
    p.add_argument('--out', type=Path, default=SEED)
    a = p.parse_args()
    print(json.dumps(compile_seed(a.materials, a.out), ensure_ascii=False))
