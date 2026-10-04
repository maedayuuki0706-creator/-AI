"""Detect missing V2 deliveries without posting anything."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from delivery_v2 import receipts

@dataclass(frozen=True)
class Expected:
    stream: str
    day: str
    jcd: str
    rno: int
    deadline_iso: str
    phase: str = "final"

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
