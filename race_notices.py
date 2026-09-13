"""Race status notices, stored separately from forecasts and virtual bets."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

from race_context import clean

NOTICE_PATH = Path('data/race_status_log.jsonl')


def withdrawal_lanes(raw):
    """Only an explicit withdrawal in the current entrant's cells counts.

    Prior meeting results start after the eight current entrant cells. A 欠
    in that history, or a missing/failed HTTP response, is not a withdrawal.
    """
    found = set()
    for body in re.findall(r'<tbody\b[^>]*>(.*?)</tbody>', raw, re.S | re.I):
        lane = re.search(r'is-boatColor([1-6])', body)
        if not lane:
            continue
        row = re.search(r'<tr\b[^>]*>(.*?)</tr>', body, re.S | re.I)
        if not row:
            continue
        cells = re.findall(r'<td\b[^>]*>(.*?)</td>', row[1], re.S | re.I)[:8]
        if any(clean(cell) in {'欠場', '欠', '欠場艇'} or re.search(r'<(?:span|div)\b[^>]*>\s*(?:欠場|欠)\s*</', cell) for cell in cells):
            found.add(int(lane[1]))
    return sorted(found)


def read_notices(path=None):
    path = path or NOTICE_PATH
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except ValueError:
            continue
    return rows


def record_notice(row, path=None):
    path = path or NOTICE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def notice_message(venue, rno, kind, reason):
    labels = {'withdrawn': '欠場', 'unavailable': 'データ未確認',
              'waiting': '見送り推奨（データ待ち）', 'pass': '見送り推奨'}
    message = f'{venue} {rno}レース\n{labels[kind]}'
    if reason:
        message += '\n' + reason
    return message
