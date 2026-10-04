"""One bounded pass over due messages; never post an expired prediction."""
from dataclasses import dataclass
from datetime import datetime, timezone
from delivery_v2.guard import deliver_once


@dataclass(frozen=True)
class Pending:
    stream: str
    day: str
    jcd: str
    rno: int
    due_at: datetime
    expires_at: datetime
    content: str
    record: dict
    phase: str = 'final'


def run_once(pending, senders, *, store, clock=None):
    clock = clock or (lambda: datetime.now(timezone.utc))
    results = []
    for item in sorted(pending, key=lambda x: x.expires_at):
        if item.due_at.tzinfo is None or item.expires_at.tzinfo is None:
            raise ValueError('Catch-up requires timezone-aware times')
        if clock() < item.due_at:
            continue
        try:
            row = deliver_once(item.stream, item.day, item.jcd, item.rno, item.content,
                senders[item.stream], item.phase, store=store, record=item.record,
                expires_at=item.expires_at, clock=clock)
        except Exception as exc:
            row = {'stream': item.stream, 'day': item.day, 'jcd': item.jcd, 'rno': item.rno,
                   'status': 'storage_error', 'error_type': type(exc).__name__}
        results.append(row)
        if row['status'] in {'failed', 'uncertain', 'expired', 'storage_error'}:
            print(f'::error::Discord V2 catch-up {item.stream} {item.jcd} {item.rno}R: {row["status"]}', flush=True)
    return results
