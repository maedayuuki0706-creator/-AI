"""Expose unresolved delivery attempts in Actions instead of hiding them."""
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import urllib.error
from zoneinfo import ZoneInfo

import sokuhou_delivery as delivery
from persist_runtime_data import git, content


def audit(day=None):
    day = day or datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y%m%d')
    if delivery.paused():
        print('Sokuhou delivery is paused by policy')
        return 0
    delivery.STORE.ensure()
    # One Git fetch avoids spending one REST request per receipt on each audit.
    git('fetch', '--no-tags', 'origin', delivery.BRANCH)
    head = git('rev-parse', 'FETCH_HEAD').decode().strip()
    files = git('ls-tree', '-r', '--name-only', head, '--', f'data/sokuhou_receipts/{day}/').decode().splitlines()
    counts = Counter()
    held = []
    now = datetime.now(ZoneInfo('Asia/Tokyo'))
    for path in files:
        if not path.endswith('.json'):
            continue
        row = json.loads(content(head, path))
        status = row.get('status', 'invalid')
        counts[status] += 1
        if status in {'sending', 'retry'}:
            timestamp = datetime.fromisoformat(row.get('retry_at') or row['claimed_at'])
            if timestamp.tzinfo is not None and (now - timestamp).total_seconds() < 600:
                continue  # Another active workflow may still be confirming it.
        if status != 'sent':
            held.append((row.get('key', path), status))
    lines = [f'Sokuhou {day}: ' + ', '.join(f'{key}={count}' for key, count in sorted(counts.items()))]
    lines += [f'- {key}: {status} (automatic repost held; review receipt)' for key, status in held]
    print('\n'.join(lines))
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a') as handle:
            handle.write('\n'.join(lines) + '\n')
    if held:
        print(f'::error::{len(held)} Sokuhou receipts need review')
    return int(bool(held))


if __name__ == '__main__':
    raise SystemExit(audit())
