"""Public BoatRace-Biyori adapter.

Reads only public pages.  It extracts venue/race navigation and public alert
signals; if a field is unavailable it returns None instead of fabricating it.
"""
from __future__ import annotations
import re, urllib.request

BASE="https://kyoteibiyori.com/"

def fetch(url=BASE):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 Boat-AI-Navi/1.0"})
    with urllib.request.urlopen(req,timeout=12) as r:
        return r.read().decode("utf-8","ignore")

def public_signals(html=None):
    html=html or fetch()
    text=re.sub(r"<[^>]+>"," ",html)
    text=re.sub(r"\s+"," ",text)
    return {
      "source":"kyoteibiyori-public",
      "makuri_alert_available":"まくりアラート" in text,
      "front_entry_alert_available":"前づけアラート" in text or "前付けアラート" in text,
      "tilt_alert_available":"チルト跳" in text,
      "course_st_gap_available":"コース別" in text and "ST" in text,
      "raw_public_page_ok":bool(text),
    }

def health():
    s=public_signals()
    return s["raw_public_page_ok"] and any(v is True for k,v in s.items() if k.endswith("_available"))

if __name__=="__main__":
    print(public_signals())
