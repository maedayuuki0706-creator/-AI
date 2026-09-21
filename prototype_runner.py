"""Collect Existing/Hiyori/Fusion snapshots for races near deadline."""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
import direct_discord_notify as base
from fusion_prototype import build_race

JST=ZoneInfo("Asia/Tokyo")

def run_once(now=None):
    now=(now or datetime.now(JST)).astimezone(JST)
    if now.hour < 8:
        return 0
    day=now.strftime("%Y%m%d")
    count=0
    for jcd in base.discover_venues(day):
        try:
            times=base.deadlines(day,jcd)
        except Exception:
            continue
        for rno,deadline in enumerate(times,1):
            lead=base.minutes_until(now,deadline)
            if 8 <= lead <= 18:
                row=build_race(day,jcd,rno,now)
                print(jcd,rno,row.get("status"))
                count+=1
    print("prototype snapshots",count)
    return 0

if __name__=="__main__":
    raise SystemExit(run_once())
