"""Reserve before POST. Recover acknowledgements; hold ambiguous sends."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import urllib.error
import uuid

from delivery_v2 import receipts
from delivery_v2.store import Conflict, default_store

MAX_ATTEMPTS = 3
RECOVERY = Path('data/delivery_v2_recovery')


def deliver_once(stream, day, jcd, rno, content, sender, phase='final', *, store=None,
                 record=None, expires_at=None, clock=None):
    key = receipts.identity(stream, day, jcd, rno, phase)
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = clock()
    if now.tzinfo is None or (expires_at is not None and expires_at.tzinfo is None):
        raise ValueError('Delivery times require a timezone')
    store = store or default_store()
    old, sha = store.read(key)
    if old:
        if old.get('key') != key:
            raise ValueError('Receipt identity mismatch')
        if old.get('status') == 'sent' and str(old.get('message_id', '')).isdigit():
            return {**old, 'status': 'already_sent'}
        if old.get('status') != 'retry' or int(old.get('attempt', 0)) >= MAX_ATTEMPTS:
            return old
        if now < datetime.fromisoformat(old['retry_at']):
            return old
        content, record = old['content'], old.get('record')
        if old.get('expires_at'):
            expires_at = datetime.fromisoformat(old['expires_at'])
    if expires_at is not None and now >= expires_at:
        return {'key': key, 'status': 'expired'}
    claim = {'key': key, 'stream': stream, 'day': day, 'jcd': f'{int(jcd):02d}',
             'rno': int(rno), 'phase': phase, 'status': 'sending',
             'attempt': int((old or {}).get('attempt', 0)) + 1, 'owner': uuid.uuid4().hex,
             'claimed_at': now.isoformat(), 'run_id': os.getenv('GITHUB_RUN_ID', 'local'),
             'content': content, 'content_sha256': hashlib.sha256(content.encode()).hexdigest(),
             'record': record or {}, 'expires_at': expires_at.isoformat() if expires_at else None}
    try:
        sha = store.write(key, claim, sha)
    except Conflict:
        current, _ = store.read(key)
        if current is None:
            raise
        return current
    if expires_at is not None and clock() >= expires_at:
        expired = {**claim, 'status': 'expired'}
        store.write(key, expired, sha)
        return expired
    try:
        message_id = sender(content)
        if not str(message_id).isdigit():
            raise RuntimeError('Discord acknowledgement has no message ID')
    except Exception as exc:
        code = exc.code if isinstance(exc, urllib.error.HTTPError) else None
        status = 'retry' if code == 429 and claim['attempt'] < MAX_ATTEMPTS else 'failed' if code and 400 <= code < 500 else 'uncertain'
        result = {**claim, 'status': status, 'error_type': type(exc).__name__, 'http_status': code}
        if status == 'retry':
            try:
                delay = max(1, float(json.loads(exc.read()).get('retry_after', 60)))
            except (ValueError, TypeError, AttributeError):
                delay = 60
            result['retry_at'] = (clock() + timedelta(seconds=delay)).isoformat()
        store.write(key, result, sha)
        print(f'::error::Discord V2 {key} {status} ({type(exc).__name__})', flush=True)
        return result
    result = {**claim, 'status': 'sent', 'message_id': str(message_id), 'sent_at': clock().isoformat()}
    recovery = RECOVERY / (key.replace(':', '_') + '.json')
    receipts.atomic_write(recovery, result)
    store.write(key, result, sha)
    # Local mirror is for reporting/recovery only; never authoritative in production.
    if store.__class__.__name__ != 'FileStore':
        receipts.write_confirmed(stream, day, jcd, rno, message_id, phase,
                                 sent_at=result['sent_at'], record=result['record'])
    print(f'Discord V2 confirmed {key} message_id={message_id}', flush=True)
    return result
