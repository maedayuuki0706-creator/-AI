"""Read-only one-shot application to real frozen originals; no delivery."""
import argparse
from collections import Counter
import json
from pathlib import Path

from .application import Materials, build, clock, markdown, read_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--materials', required=True, type=Path)
    p.add_argument('--state', required=True, type=Path)
    p.add_argument('--inputs', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--day', required=True, help='YYYYMMDD')
    p.add_argument('--mode', choices=('live', 'replay'), default='replay')
    a = p.parse_args()
    materials = Materials(a.materials)
    paths = sorted(a.inputs.glob(a.day + '_*.json'))
    a.out.mkdir(parents=True, exist_ok=True)
    rows, failed = [], []
    changed, footprints = Counter(), Counter()
    for path in paths:
        try:
            snapshot = read_json(path)
            record = build(snapshot, materials, state_root=a.state, mode=a.mode)
            for suffix, text in (('.json', json.dumps(record, ensure_ascii=False, indent=2) + '\n'),
                                 ('.md', markdown(record))):
                with (a.out / (record['race_id'] + suffix)).open('x', encoding='utf-8') as f:
                    f.write(text)
            for key, value in record['card_changes'].items():
                changed[key] += bool(value['added'])
            footprints[record['foot_provenance']['status']] += 1
            rows.append({'race_id': record['race_id'], 'digest': record['digest'],
                         'six_boats': len(record['all_six']),
                         'profiles_with_at_least_3_starts': sum(b['course_history']['denominator'] >= 3 for b in record['all_six']),
                         'foot_status': record['foot_provenance']['status']})
        except Exception as exc:
            failed.append({'source_file': path.name, 'reason': str(exc), 'type': type(exc).__name__})
    summary = {'version': 'materials-application-batch-v1', 'generated_at': clock(),
               'mode': a.mode, 'input_count': len(paths), 'output_count': len(rows),
               'all_six_boats': sum(r['six_boats'] for r in rows),
               'profiles_with_at_least_3_starts': sum(r['profiles_with_at_least_3_starts'] for r in rows),
               'foot_status_counts': dict(footprints), 'card_changed_races': dict(changed),
               'rows': rows, 'failed': failed, 'result_accessed': False,
               'prospective_graded_races': 0, 'production_modified': False}
    with (a.out / 'summary.json').open('x', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'rows'}, ensure_ascii=False))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
