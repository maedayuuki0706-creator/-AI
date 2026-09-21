"""Hiyori A/B notifier.

Runs independently from the existing notifier.  It uses the existing official
analysis as a safe baseline until the Hiyori adapter has validated data, logs
compression diagnostics, and posts only to HIYORI_DISCORD_WEBHOOK_URL.
"""
from __future__ import annotations
import json, os, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
import direct_discord_notify as base
import kyoteibiyori_adapter as hiyori
from ticket_compression import compression_snapshot, format_support_note

JST=ZoneInfo("Asia/Tokyo")
LOG="data/hiyori_prediction_log.jsonl"

def send(message):
    url=os.getenv("HIYORI_DISCORD_WEBHOOK_URL")
    if not url: raise RuntimeError("HIYORI_DISCORD_WEBHOOK_URL is not configured")
    req=urllib.request.Request(url,data=json.dumps({"content":message},ensure_ascii=False).encode(),headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=10) as r: return r.status

def log(row):
    os.makedirs("data",exist_ok=True)
    with open(LOG,"a",encoding="utf-8") as f:f.write(json.dumps(row,ensure_ascii=False)+"\n")

def test():
    status=send("🌤️ **日和AI｜配信テスト**\n専用チャンネル接続確認OK")
    print("hiyori webhook status",status)

def run_once(now=None):
    now=(now or datetime.now(JST)).astimezone(JST); day=now.strftime("%Y%m%d")
    if now.hour<8:return 0
    venues=base.discover_venues(day); sent=0
    for jcd in venues:
        try: times=base.deadlines(day,jcd)
        except Exception: continue
        for rno,deadline in enumerate(times,1):
            lead=base.minutes_until(now,deadline)
            if not 8<=lead<=18: continue
            key=(day,str(jcd),rno)
            try:
                a=base.analyze_official(day,jcd,rno)
                hs=hiyori.public_signals()
                if not a or not base.valid_six_boats(a,base.load_policy()):continue
                snap=compression_snapshot(a)
                rows=(a.get("trifecta") or [])[:10]
                picks=[x["combination"] for x in rows]
                leader=snap["head"]
                msg=(f"🌤️ **日和AI A/B｜{base.VENUES[jcd]} {rno}R**\n締切 **{deadline}**\n"
                     f"🎯 軸候補：**{leader}号艇**\n"
                     f"買い目候補：{' / '.join(picks)}\n"
                     f"{format_support_note(a)}\n\n"
                     "日和公開データ接続：OK｜既存AIとは別ログで比較保存。")
                send(msg)
                log({"day":day,"jcd":str(jcd),"venue":base.VENUES[jcd],"rno":rno,"deadline":deadline,
                     "sent_at":now.isoformat(),"stream":"hiyori-ab","hiyori_data_status":"public-connected","hiyori_signals":hs,
                     "picks":picks,"compression":snap})
                sent+=1
            except Exception as e: print("hiyori failed",key,type(e).__name__)
    print("hiyori sent",sent);return 0

if __name__=="__main__":
    import sys
    if "--test" in sys.argv:test()
    else:run_once()
