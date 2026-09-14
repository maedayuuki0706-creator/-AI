"""Timestamped, credential-free notification evidence, separate for every run."""
from datetime import datetime
import json
import os
from pathlib import Path
import re
import threading
import uuid
from zoneinfo import ZoneInfo

JST = ZoneInfo('Asia/Tokyo')
AUDIT_ROOT = Path('data/notification_audit')
RUN_ID = os.getenv('GITHUB_RUN_ID') or ('local-' + uuid.uuid4().hex[:12])
RUN_ATTEMPT = os.getenv('GITHUB_RUN_ATTEMPT', '1')
_lock = threading.Lock()


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()
                if not any(word in k.lower() for word in ('token', 'secret', 'webhook', 'authorization'))}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, str):
        return re.sub(r'https?://\S+', '[url omitted]', value)
    return value


def emit(event, *, day=None, jcd=None, rno=None, phase=None, **fields):
    now = datetime.now(JST)
    row = clean({'event_id': uuid.uuid4().hex, 'event': event, 'at': now.isoformat(),
                 'run_id': RUN_ID, 'run_attempt': RUN_ATTEMPT,
                 'code_sha': os.getenv('NOTIFICATION_CODE_SHA') or os.getenv('GITHUB_SHA'),
                 'day': day or now.strftime('%Y%m%d'), 'jcd': jcd, 'rno': rno, 'phase': phase, **fields})
    line = json.dumps(row, ensure_ascii=False, sort_keys=True)
    path = AUDIT_ROOT / row['day'] / f'{RUN_ID}-{RUN_ATTEMPT}.jsonl'
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as stream:
            stream.write(line + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        print('AUDIT ' + line, flush=True)
    return row
