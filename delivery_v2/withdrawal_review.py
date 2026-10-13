"""Offline review of missed deliveries. Never changes health or sends messages."""
from __future__ import annotations

import copy
from datetime import datetime
import hashlib
import html
import json
import re
from urllib.parse import parse_qs, urlparse


def _clean(value):
    return html.unescape(re.sub(r'<[^>]*>', '', value)).strip()


def _digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def _validate_source(key, source_url, reviewed_at):
    parts = key.split(':')
    if len(parts) != 5:
        raise ValueError('Invalid delivery identity')
    stream, day, jcd, rno, phase = parts
    from delivery_v2.receipts import identity
    if key != identity(stream, day, jcd, rno, phase):
        raise ValueError('Noncanonical delivery identity')
    url = urlparse(source_url)
    if (url.scheme != 'https' or url.netloc != 'www.boatrace.jp'
            or url.path != '/owpc/pc/race/raceresult'
            or parse_qs(url.query) != {'hd': [day], 'jcd': [jcd], 'rno': [str(int(rno))]}):
        raise ValueError('Official result URL does not match race')
    if datetime.fromisoformat(reviewed_at).tzinfo is None:
        raise ValueError('Review time must include timezone')


def result_evidence(key, source_url, raw, *, reviewed_at):
    """Read explicit withdrawal marks only from the official current result table.

    Evidence is retrospective: it never proves the withdrawal was known before
    the deadline, or that an omitted forecast was intentionally suppressed.
    """
    _validate_source(key, source_url, reviewed_at)
    rows = []
    for table in re.findall(r'<table\b[^>]*>(.*?)</table>', raw, re.I | re.S):
        headers = [_clean(x) for x in re.findall(r'<th\b[^>]*>(.*?)</th>', table, re.I | re.S)]
        if headers != ['着', '枠', 'ボートレーサー', 'レースタイム']:
            continue
        for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', table, re.I | re.S):
            cells = re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.I | re.S)
            if len(cells) != 4:
                continue
            lane = _clean(cells[1])
            if lane in '123456' and len(lane) == 1:
                rows.append({'lane': int(lane), 'finish': _clean(cells[0])})
    if sorted(x['lane'] for x in rows) != [1, 2, 3, 4, 5, 6]:
        raise ValueError('Complete current official result table is required')
    lanes = [x['lane'] for x in rows if x['finish'] in {'欠', '欠場'}]
    if not lanes:
        raise ValueError('No explicit current-race withdrawal')
    return {'key': key, 'source_url': source_url, 'reviewed_at': reviewed_at,
            'source_sha256': hashlib.sha256(raw.encode()).hexdigest(),
            'result_rows': rows, 'result_rows_sha256': _digest(rows),
            'withdrawal_lanes': lanes, 'automatic_resend_prohibited': True,
            'known_before_deadline': None,
            'scope': 'retrospective_official_withdrawal_review'}


def review_missed(report, evidence_by_key):
    """Append diagnostics to a copy; leave status, counts, receipts and IDs intact."""
    reviewed, unresolved = [], []
    for row in report.get('active_missed', []):
        evidence = evidence_by_key.get(row['key'])
        eligible = (row.get('status') == 'missed' and not row.get('message_id')
                    and row.get('attempt') == 0 and row.get('delivery_status') == 'missing')
        if not eligible or not evidence:
            unresolved.append(row['key'])
            continue
        _validate_source(row['key'], evidence.get('source_url', ''), evidence.get('reviewed_at', ''))
        if (evidence.get('key') != row['key'] or not evidence.get('automatic_resend_prohibited')
                or evidence.get('scope') != 'retrospective_official_withdrawal_review'
                or _digest(evidence.get('result_rows', [])) != evidence.get('result_rows_sha256')):
            raise ValueError('Withdrawal evidence identity or integrity mismatch')
        lanes = [x['lane'] for x in evidence['result_rows'] if x['finish'] in {'欠', '欠場'}]
        if (not lanes or lanes != evidence.get('withdrawal_lanes')
                or sorted(x['lane'] for x in evidence['result_rows']) != [1, 2, 3, 4, 5, 6]):
            raise ValueError('Explicit withdrawal evidence is required')
        reviewed.append({'key': row['key'], 'category': 'missed_with_confirmed_withdrawal',
                         'withdrawal_lanes': lanes, 'source_url': evidence['source_url'],
                         'known_before_deadline': evidence.get('known_before_deadline'),
                         'automatic_resend_prohibited': True})
    output = copy.deepcopy(report)
    output['withdrawal_review'] = {'reviewed': reviewed, 'unresolved': unresolved,
                                   'production_health_unchanged': True}
    return output
