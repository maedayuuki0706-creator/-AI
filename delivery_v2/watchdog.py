"""Detect missing V2 deliveries without posting anything."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from datetime import timedelta
from zoneinfo import ZoneInfo
from delivery_v2 import receipts

@dataclass(frozen=True)
class Expected:
    stream: str
    day: str
    jcd: str
    rno: int
    deadline_iso: str
    phase: str = "final"
    due_iso: str | None = None

    @property
    def key(self):
        return receipts.identity(self.stream, self.day, self.jcd, self.rno, self.phase)


def generate_expected(day, schedules, *, streams=('main', 'yuuki'), records=()):
    """Normal races come from the official schedule; gated streams from engine output."""
    out = {}
    for jcd, times in schedules.items():
        for rno, deadline in enumerate(times, 1):
            close = datetime.strptime(day + ' ' + deadline, '%Y%m%d %H:%M').replace(tzinfo=ZoneInfo('Asia/Tokyo'))
            for stream in streams:
                lead = 30 if stream == 'yuuki' else 40
                item = Expected(stream, day, str(jcd).zfill(2), rno, close.isoformat(),
                                due_iso=(close-timedelta(minutes=lead)).isoformat())
                out[item.key] = item
    for record in records:
        if record.get('day') != day or record.get('status') == 'sniper_skip':
            continue
        stream = record.get('stream')
        if not stream or not record.get('deadline'):
            continue
        close = datetime.strptime(day+' '+record['deadline'], '%Y%m%d %H:%M').replace(tzinfo=ZoneInfo('Asia/Tokyo'))
        item = Expected(stream, day, str(record['jcd']).zfill(2), int(record['rno']), close.isoformat(),
                        record.get('phase') or 'final', (close-timedelta(minutes=40)).isoformat())
        out[item.key] = item
    return sorted(out.values(), key=lambda item: (item.deadline_iso, item.key))


def audit(expected, *, now, durable, legacy=None):
    """Strict acknowledgements; unknown sends stay held, past deadlines become missed."""
    if now.tzinfo is None:
        raise ValueError('Watchdog requires an aware current time')
    legacy = legacy or {}
    rows = []
    for item in expected:
        due = datetime.fromisoformat(item.due_iso or item.deadline_iso)
        if now < due:
            continue
        proof = durable.get(item.key) or legacy.get(item.key) or {}
        state = proof.get('status', 'sent')
        close = datetime.fromisoformat(item.deadline_iso)
        if close.tzinfo is None or due.tzinfo is None:
            raise ValueError('Watchdog deadlines require timezone')
        if state in {'sent', 'already_sent'} and str(proof.get('message_id', '')).isdigit():
            status = 'sent'
        elif proof and state in {'sending', 'uncertain', 'failed', 'storage_error', 'legacy_unverified'}:
            status = state
        elif proof and state == 'sent':
            status = 'legacy_unverified'
        elif now >= close:
            status = 'missed'
        else:
            status = 'catch_up'
        rows.append({'key': item.key, 'stream': item.stream, 'day': item.day, 'jcd': item.jcd,
                     'rno': item.rno, 'phase': item.phase, 'deadline': item.deadline_iso, 'status': status,
                     'delivery_status': state if proof else 'missing', 'message_id': proof.get('message_id'),
                     'attempt': proof.get('attempt', 0)})
    return rows

def missing(expected, *, now=None, grace_seconds=90):
    now=now or datetime.now(timezone.utc)
    out=[]
    for item in expected:
        if receipts.confirmed(item.stream,item.day,item.jcd,item.rno,item.phase):
            continue
        deadline=datetime.fromisoformat(item.deadline_iso)
        if deadline.tzinfo is None:
            deadline=deadline.replace(tzinfo=timezone.utc)
        age=(now-deadline).total_seconds()
        if age >= grace_seconds:
            out.append({"stream":item.stream,"day":item.day,"jcd":item.jcd,"rno":item.rno,"phase":item.phase,"seconds_late":int(age)})
    return out
