"""Validated atomic receipts; production uses the separate state branch."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import tempfile

ROOT = Path('data/delivery_v2_receipts')


def identity(stream, day, jcd, rno, phase='final'):
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,40}', str(stream)):
        raise ValueError('Invalid stream')
    from datetime import datetime
    datetime.strptime(str(day), '%Y%m%d')
    if not re.fullmatch(r'\d{8}', str(day)) or not 1 <= int(jcd) <= 24 or not 1 <= int(rno) <= 12:
        raise ValueError('Invalid race identity')
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,40}', str(phase)):
        raise ValueError('Invalid phase')
    return f'{stream}:{day}:{int(jcd):02d}:{int(rno)}:{phase}'


def path_for(stream, day, jcd, rno, phase='final'):
    identity(stream, day, jcd, rno, phase)
    return ROOT / str(day) / stream / f'{int(jcd):02d}_{int(rno):02d}_{phase}.json'


def read(stream, day, jcd, rno, phase='final'):
    p = path_for(stream, day, jcd, rno, phase)
    if not p.exists():
        return None
    row = json.loads(p.read_text(encoding='utf-8'))
    if not isinstance(row, dict):
        raise ValueError('Invalid receipt')
    return row


def confirmed(stream, day, jcd, rno, phase='final'):
    row = read(stream, day, jcd, rno, phase) or {}
    return row.get('status', 'sent') == 'sent' and str(row.get('message_id', '')).isdigit()


def atomic_write(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_confirmed(stream, day, jcd, rno, message_id, phase='final', **extra):
    if not str(message_id).isdigit():
        raise ValueError('message_id required')
    row = {**extra, 'key': identity(stream, day, jcd, rno, phase), 'stream': stream,
           'day': day, 'jcd': f'{int(jcd):02d}', 'rno': int(rno), 'phase': phase,
           'message_id': str(message_id), 'status': 'sent'}
    atomic_write(path_for(stream, day, jcd, rno, phase), row)
    return row
