"""Local receipt journal for V2 delivery.

Receipts are append-only and keyed by stream/day/venue/race/phase.
A message is complete only when a Discord message id is stored.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path("data/delivery_v2_receipts")

def path_for(stream,day,jcd,rno,phase="final"):
    safe_stream="".join(c for c in stream if c.isalnum() or c in "_-")
    return ROOT/day/safe_stream/f"{str(jcd).zfill(2)}_{int(rno):02d}_{phase}.json"

def read(stream,day,jcd,rno,phase="final"):
    p=path_for(stream,day,jcd,rno,phase)
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError,OSError): return None

def confirmed(stream,day,jcd,rno,phase="final"):
    row=read(stream,day,jcd,rno,phase) or {}
    return str(row.get("message_id","")).isdigit()

def write_confirmed(stream,day,jcd,rno,message_id,phase="final",**extra):
    if not str(message_id).isdigit(): raise ValueError("message_id required")
    p=path_for(stream,day,jcd,rno,phase)
    p.parent.mkdir(parents=True,exist_ok=True)
    row={"stream":stream,"day":day,"jcd":str(jcd).zfill(2),"rno":int(rno),"phase":phase,"message_id":str(message_id),**extra}
    tmp=p.with_suffix(".tmp")
    tmp.write_text(json.dumps(row,ensure_ascii=False,sort_keys=True)+"\n",encoding="utf-8")
    tmp.replace(p)
    return row
