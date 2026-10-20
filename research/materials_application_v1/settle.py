"""Outcome-only phase. Grade frozen originals without changing their contents."""
import argparse
from collections import defaultdict
from datetime import timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
from pathlib import Path

from .review import review
from research.scenario_v2 import engine as scenario
from research.materials_v1.collector import (Store, read, once, encode, write, now,
                                            stamp, aware, url, parsers)

BRANCH = 'research-materials-applied-state-v1'


def receipt_eligible(forecast, receipt, input_bytes, forecast_bytes):
    scenario.verify(forecast)
    snapshot = json.loads(input_bytes)
    if forecast['source_input_digest'] != scenario.digest(snapshot):
        raise ValueError('Frozen input digest differs')
    if not receipt:
        return False
    if (receipt.get('forecast_sha256') != sha256(forecast_bytes).hexdigest()
            or receipt.get('input_sha256') != sha256(input_bytes).hexdigest()
            or receipt.get('race_id') != forecast['race_id']):
        raise ValueError('Remote receipt content identity differs')
    cutoff = aware(forecast['deadline_at']) - timedelta(seconds=180)
    checked = aware(receipt['checked_at'])
    server = parsedate_to_datetime(receipt['github_server_date'])
    return bool(forecast['status'] == 'live_uncheckpointed'
        and receipt.get('remote_ref') == BRANCH
        and receipt.get('confirmed_at_least_three_minutes_before_deadline') is True
        and receipt.get('count_as_prospective') is True
        and aware(forecast['assembled_at']) <= checked <= cutoff
        and aware(forecast['assembled_at']) <= server <= cutoff
        and abs((checked - server).total_seconds()) < 60)


def acquire_outcome(store, source, frozen):
    rid = frozen['race_id']; path = store.root / 'results' / (rid + '.json')
    if path.exists():
        record = read(path)
        raw = store.body(record['acquisition'])
        day, code, rno = rid.split('_')
        if parsers.parse_payout(raw) != record['payout']:
            raise ValueError('Saved payout differs from official raw')
        if record.get('details') and parsers.parse_result(raw, day, code, int(rno)) != record['details']:
            raise ValueError('Saved outcome details differ from official raw')
        return record
    if (now() - aware(frozen['deadline_at'])).total_seconds() < 180:
        return None
    source_path = Path(source) / 'results' / (rid + '.json')
    doc = read(source_path) if source_path.is_file() else None
    day, code, rno = rid.split('_')
    if doc and (doc.get('acquisition') or {}).get('status') == 'ok':
        # Reparse the hash-verified official raw instead of trusting a copied
        # payout or finish table that could have been changed independently.
        src = Store(source)
        raw = src.body(doc['acquisition']); acquisition = doc['acquisition']
        store.document(raw, {k: v for k, v in acquisition.items() if k not in ('raw_path', 'sha256', 'bytes')})
    else:
        acquisition = store.get(url('raceresult', day, code, int(rno)), ttl=180)
        if acquisition['status'] != 'ok':
            return None
        raw = store.body(acquisition)
    if acquisition['url'] != url('raceresult', day, code, int(rno)):
        raise ValueError('Outcome source URL/race identity differs')
    if aware(acquisition['retrieved_at']) < aware(frozen['deadline_at']):
        raise ValueError('Outcome observation predates deadline')
    payout = parsers.parse_payout(raw)
    if payout['status'] == 'pending':
        return None
    try:
        details = parsers.parse_result(raw, day, code, int(rno))
    except ValueError:
        # A void/refund page may legitimately have no normal six-boat finish.
        if payout['status'] == 'settled' and not payout.get('refund_lanes'):
            return None
        details = None
    result = {'race_id': rid, 'acquisition': acquisition, 'payout': payout,
              'details': details, 'predictive_input_allowed': False}
    once(path, encode(result))
    return result


def summarize(rows):
    # Multiple capture stages are diagnostics, not independent race samples.
    chosen = {}
    for row in rows:
        if row.get('status') != 'graded_prospective' or not row.get('count_as_prospective'):
            continue
        prior = chosen.get(row['race_id'])
        if prior is None or row['assembled_at'] > prior['assembled_at']:
            chosen[row['race_id']] = row
    models = {}
    for row in chosen.values():
        for name, values in row['models'].items():
            total = models.setdefault(name, {'races': 0, 'hits': 0, 'stake_yen': 0, 'return_yen': 0})
            total['races'] += 1; total['hits'] += int(values['hit'])
            total['stake_yen'] += values['stake_yen']; total['return_yen'] += values['return_yen']
    for total in models.values():
        total['roi_pct'] = round(100 * total['return_yen'] / total['stake_yen'], 2)
        total['hit_rate_pct'] = round(100 * total['hits'] / total['races'], 2)
    return {'generated_at': stamp(), 'prospective_unique_races': len(chosen), 'models': models,
            'selection_rule': 'latest externally confirmed capture per race; all models same ten points',
            'selected_keys': {rid: r['key'] for rid, r in chosen.items()},
            'excluded_or_unconfirmed_stage_records': len(rows) - len(chosen),
            'actual_attack_verified': False, 'profitability_proven': False}


def run(state, source):
    store = Store(state); rows = []; pending = []
    for path in sorted((store.root / 'forecasts').glob('*.json')):
        frozen = read(path); scenario.verify(frozen)
        grade_path = store.root / 'grades' / path.name
        if grade_path.exists():
            rows.append(read(grade_path)); continue
        if now() < aware(frozen['deadline_at']) + timedelta(seconds=180):
            pending.append(path.stem); continue
        result = acquire_outcome(store, source, frozen)
        if result is None:
            pending.append(path.stem); continue
        receipt_path = store.root / 'receipts' / path.name
        receipt = read(receipt_path) if receipt_path.exists() else None
        eligible = receipt_eligible(frozen, receipt,
            (store.root / 'inputs' / path.name).read_bytes(), path.read_bytes())
        row = review(frozen, result)
        if row['status'] != 'excluded':
            row['status'] = 'graded_prospective' if eligible else 'graded_unconfirmed_excluded_from_prospective'
        row.update(key=path.stem, assembled_at=frozen['assembled_at'],
                   capture_stage=frozen['capture_stage'], count_as_prospective=eligible and row['status'] != 'excluded',
                   tide_proxy_cohort=frozen.get('tide_context', {}).get('phase_proxy'),
                   foot_status=frozen['foot_provenance']['status'])
        once(grade_path, encode(row)); rows.append(row)
    report = summarize(rows)
    report.update(pending_keys=pending, graded_stage_records=len(rows))
    write(store.root / 'reports/prospective_summary.json', report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--state', required=True, type=Path)
    p.add_argument('--source', required=True, type=Path)
    a = p.parse_args(); run(a.state, a.source)
