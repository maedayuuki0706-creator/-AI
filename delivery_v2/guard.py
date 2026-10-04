"""Receipt-aware delivery guard."""
from __future__ import annotations
from delivery_v2 import receipts

def deliver_once(stream,day,jcd,rno,content,sender,phase="final"):
    old=receipts.read(stream,day,jcd,rno,phase)
    if old and str(old.get("message_id","")).isdigit():
        return {"status":"already_sent",**old}
    message_id=sender(content)
    row=receipts.write_confirmed(stream,day,jcd,rno,message_id,phase)
    return {"status":"sent",**row}
