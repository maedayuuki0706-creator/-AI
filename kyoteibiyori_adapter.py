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


def race_url(day, jcd, rno):
    return (f"{BASE}race_shusso.php?hiduke={day}&place_no={int(jcd)}&race_no={int(rno)}")

def race_signals(day, jcd, rno, html=None):
    """Race-scoped public-page metadata. Never fabricates missing dynamic fields."""
    url=race_url(day,jcd,rno)
    html=html or fetch(url)
    text=re.sub(r"<[^>]+>"," ",html)
    text=re.sub(r"\\s+"," ",text)
    deadline=None
    m=re.search(r"締切\\s*([0-2]?\\d:[0-5]\\d)",text)
    if m: deadline=m.group(1)
    return {
      "source":"kyoteibiyori-public-race",
      "source_url":url,
      "page_ok":bool(text.strip()),
      "deadline":deadline,
      "makuri_alert_mentioned":"まくりアラート" in text,
      "front_entry_alert_mentioned":"前づけ" in text or "前付け" in text,
      "tilt_alert_mentioned":"チルト" in text,
      "course_st_mentioned":"コース別" in text and "ST" in text,
    }

def race_model(day, jcd, rno):
    """Independent Hiyori model interface used by fusion_prototype.

    Public HTML currently exposes race metadata but key per-boat tables are
    dynamically loaded. Until those lane-level values are parsed independently,
    return ready=False so the fusion stream cannot silently reuse Existing AI.
    """
    try:
        signals=race_signals(day,jcd,rno)
    except Exception as e:
        return {"ready":False,"reason":f"fetch_error:{type(e).__name__}",
                "source_url":race_url(day,jcd,rno),"signals":None,"trifecta":[]}
    return {
      "ready":False,
      "reason":"lane_level_hiyori_dynamic_data_not_parsed",
      "source_url":signals["source_url"],
      "signals":signals,
      "trifecta":[],
    }
