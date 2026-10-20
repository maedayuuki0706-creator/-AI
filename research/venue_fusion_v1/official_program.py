"""Rebuild an honest *official-only main-core* input from immutable official HTML.

This research-only adapter consumes the original official racelist and
beforeinfo HTML captured for the CURRENT race before its deadline. No live
fetch; never reads result, current profile DB, course grades, previous-day
score or retrospective tide information.

Important: main-core calls the unchanged production prediction_engine but
is NOT the full delivered Main-kun (which additionally loads racer_profiles,
previous_form, sometimes odds). The difference remains explicitly recorded.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import re

from research.capture_v1 import parsers
from research.scenario_v2 import engine as scenario
from research.venue_specialists_v1 import engine as venues

VERSION="main-core-from-official-frozen-html-20261020"
MISSING_ENRICHMENT=[
    "historical racer course profile from point-in-time DB",
    "previous day form score from point-in-time DB",
    "full official three-way pre-deadline odds",
    "verified turn/straight/pit-out/lap grades",
]
CORE_REQUIRED=(
    "win_rate","top2_rate","top3_rate",
    "motor_top2_rate","motor_top3_rate","boat_top2_rate","boat_top3_rate"
)
BOATS_URL="https://www.boatrace.jp/owpc/pc/race/racelist"
EXHIB_URL="https://www.boatrace.jp/owpc/pc/race/beforeinfo"


def _url(kind, meta):
    from urllib.parse import urlencode
    return (BOATS_URL if kind=="racelist" else EXHIB_URL)+ "?" + urlencode({
        "hd":meta["day"],"jcd":str(meta["jcd"]).zfill(2),"rno":int(meta["rno"])
    })


def _html(originals, kind, meta, captured, deadline):
    doc=originals.get(kind)
    if not isinstance(doc,dict) or not isinstance(doc.get("html"),str):
        raise ValueError("Missing immutable official "+kind+" HTML")
    if not doc["html"] or len(doc["html"])>2_000_000:
        raise ValueError("Unbounded official HTML")
    if doc.get("url")!=_url(kind,meta):
        raise ValueError("Official original URL/identity changed for "+kind)
    actual=sha256(doc["html"].encode("utf-8")).hexdigest()
    if actual != doc.get("sha256"):
        raise ValueError("Original official HTML SHA256 mismatch: "+kind)
    obs=scenario.aware(doc["observed_at"])
    if obs>captured or obs>deadline-timedelta(minutes=3):
        raise ValueError("Original official page observed after cutoff")
    if obs.strftime("%Y%m%d")!=str(meta["day"]):
        raise ValueError("Original official page from wrong race day")
    return doc["html"],obs,actual


def _equal_numeric(original, reconstructed, field, lane, tolerance=.02):
    a,b=original.get(field),reconstructed.get(field)
    if a is None and b is None:
        return
    if a is None or b is None:
        raise ValueError(f"Frozen/pre-race parser {field} missing mismatch for {lane}")
    if abs(float(a)-float(b))>tolerance:
        raise ValueError(f"Frozen/pre-race parser {field} conflict for {lane}")


def from_frozen_official(snapshot, *, allow_missing_values=False):
    """Build from SAME predeadline archive, never claim full-Main parity.

    Only when all six programs, exhibition entries and official page timestamps
    agree can this be used. Missing officially disclosed measurements are logged,
    and by default the entire comparison is excluded rather than padded.
    """
    scenario.reject_outcomes(snapshot)
    meta=snapshot["meta"]
    # Replay validation checks official acquisition >=3m before deadline.
    scenario.validate(snapshot,"replay",meta["captured_at"])
    code=str(meta["jcd"]).zfill(2)
    if code not in venues.VENUES:
        raise ValueError("Not a selected four-venue research venue")
    deadline=scenario.aware(
        f'{meta["day"][:4]}-{meta["day"][4:6]}-{meta["day"][6:8]}T{meta["deadline"]}:00+09:00'
    )
    captured=scenario.aware(meta["captured_at"])
    original=deepcopy(snapshot.get("official_originals") or {})
    rh,rt,rhash=_html(original,"racelist",meta,captured,deadline)
    bh,bt,bhash=_html(original,"beforeinfo",meta,captured,deadline)
    if abs((bt-rt).total_seconds())>120:
        raise ValueError("Official program and exhibition were acquired too far apart")
    if bt<rt:
        raise ValueError("Exhibition source older than roster (cannot assert atomic main input)")
    program=parsers.parse_racelist_boats(rh)
    preview=parsers.parse_beforeinfo(bh)
    if len(program)!=6 or not preview.get("entry_observed") or preview.get("exhibition_count")!=6:
        raise ValueError("Six verified official program/exhibition records not found")
    sboats={int(b["lane"]):b for b in snapshot["boats"]}
    pboats={int(b["lane"]):b for b in program}
    ev=preview["boats"]
    if set(sboats)!=set(range(1,7)) or set(pboats)!=set(range(1,7)) or set(ev)!=set(range(1,7)):
        raise ValueError("Six pre-race boats incomplete")
    out=[]
    missing={}
    for lane in range(1,7):
        frozen,prog,ex=sboats[lane],deepcopy(pboats[lane]),ev[lane]
        if str(frozen.get("racer_id"))!=str(prog.get("racer_id")):
            raise ValueError("Official racer ID differs from frozen input")
        if int(frozen["course"])!=int(ex.get("predicted_course",-1)):
            raise ValueError("Official exhibition course differs from frozen input")
        if int(frozen.get("motor_number") or 0)!=int(prog.get("motor_number") or 0):
            raise ValueError("Official motor number differs from frozen input")
        _equal_numeric(frozen,prog,"avg_st",lane,.0051)
        _equal_numeric(frozen,prog,"motor_top2_rate",lane,.051)
        _equal_numeric(frozen,ex,"exhibition_time",lane,.0051)
        _equal_numeric(frozen,
            {"exhibition_st":ex.get("exhibition_st_timing")},"exhibition_st",lane,.0051)
        prog.update(ex)
        prog["predicted_course"]=int(ex["predicted_course"])
        prog["entry_shift"]=int(lane)-int(ex["predicted_course"])
        prog["front_entry"]=int(ex["predicted_course"])<lane
        prog["source"]="official_pregame_racelist_beforeinfo"
        prog["historical_profile_applied"]=False
        prog["previous_form_applied"]=False
        problems=[k for k in CORE_REQUIRED if prog.get(k) is None]
        if problems:
            missing[str(lane)]=problems
        out.append(prog)
    if missing and not allow_missing_values:
        raise ValueError("Official program lacks required Main-core fields: "+str(missing))
    # Never substitute post-race wind observation: use only the original
    # preview, cross-checking same snapshot's preview measurements.
    for key in ("wind_speed","wave_cm"):
        if preview.get(key) is not None and (snapshot.get("environment") or {}).get(key) is not None:
            if abs(float(preview[key])-float(snapshot["environment"][key]))>.01:
                raise ValueError("Frozen environment changed: "+key)
    payload={
        "race":{"venue":venues.VENUES[code]["venue"],
                "wind_speed":preview.get("wind_speed"),
                "wave_cm":preview.get("wave_cm"),
                "air_temp_c":preview.get("air_temp_c"),
                "water_temp_c":preview.get("water_temp_c"),
                "tide":(snapshot.get("environment") or {}).get("tide")},
        "boats":out,
        # Original specialist inputs do not record official live odds; do not
        # fill this from today's odds or archived after-race final odds.
        "trifecta_odds":{},
    }
    return {
        "version":VERSION,
        "meta":{"day":meta["day"],"jcd":code,"rno":meta["rno"],
                "deadline":meta["deadline"],
                "captured_at":meta["captured_at"],"source_observed_at":bt.isoformat(),
                "source_type":"immutable_two_official_pages",
                "source_sha256":sha256((rhash+bhash).encode("ascii")).hexdigest(),
                "official_pages":{"racelist":{"observed_at":rt.isoformat(),"sha256":rhash},
                                  "beforeinfo":{"observed_at":bt.isoformat(),"sha256":bhash}},
                "official_missing_values":missing,
                "preprocessing_level":"main_official_core_without_profile_form_odds",
                "production_preprocessing_verified":False},
        "payload":payload,
        "limitations":MISSING_ENRICHMENT,
    }
