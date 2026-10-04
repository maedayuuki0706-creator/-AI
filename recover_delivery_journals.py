"""Restore exact journal rows recovered from Actions artifacts, without posting."""
from __future__ import annotations
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

ALLOWED = {'prediction_log.jsonl','opportunity_alert_deliveries.jsonl',
           'hit_alert_deliveries.jsonl','race_status_log.jsonl'}


def restore(day, *, root=Path('data')):
    datetime.strptime(day, '%Y%m%d')
    manifest = root / 'delivery_recovery' / f'{day}_artifact_rows.json'
    if not manifest.exists():
        return 0
    items = json.loads(manifest.read_text())['records']
    grouped = {}
    for item in items:
        name, row = item['journal'], item['record']
        if name not in ALLOWED or row.get('day') != day or not item.get('artifact_id'):
            raise ValueError('Invalid recovery provenance or journal')
        grouped.setdefault(name, []).append(row)
    restored = 0
    for name, rows in grouped.items():
        path = root / name
        def canonical(row):
            return json.dumps(row, ensure_ascii=False, sort_keys=True)
        seen = {canonical(json.loads(line)) for line in path.read_text().splitlines() if line.strip()} if path.exists() else set()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as handle:
            for row in sorted(rows, key=lambda x: x.get('sent_at', '')):
                value = canonical(row)
                if value not in seen:
                    handle.write(value + '\n'); seen.add(value); restored += 1
            handle.flush(); os.fsync(handle.fileno())
    print(f'Restored {restored} exact artifact journal rows for {day}; no Discord messages sent', flush=True)
    return restored


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--day', default=datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y%m%d'))
    args = parser.parse_args()
    restore(args.day)
