"""Emit only public same-race foot timings. Never persist tokens or user memo data."""
import json
import sys
from .hiyori_public import fetch_race
from research.scenario_v2.engine import number


def main():
    day,jcd,rno=sys.argv[1:]
    raw=fetch_race(day,jcd,rno)
    previews=raw.get("preview") or []
    if isinstance(previews,dict): previews=list(previews.values())
    if len(previews)!=6: raise ValueError("Six public foot previews not available")
    by_id={str(p["player_no"]):p for p in previews}
    rows=[]
    for b in raw["rows"]:
        racer=str(b.get("player_no") or b.get("racer_no") or "")
        p=by_id.get(racer)
        if not p: raise ValueError("Public foot preview racer mismatch")
        for k,v in [("hiduke",day),("place_no",jcd),("race_no",rno)]:
            if int(p[k])!=int(v): raise ValueError("Public foot preview race mismatch")
        row={"lane":int(b["course"]),"racer_id":racer}
        for dest,field in [("straight_time","chokusen"),("turn_time","mawariashi"),("lap_time","shukai")]:
            value=number(p.get(field),-1,10000)
            row[dest]=value/100 if value is not None and value>0 else None
        rows.append(row)
    print(json.dumps({"source_url":raw["source_url"],"rows":rows},ensure_ascii=False,allow_nan=False))


if __name__=="__main__": main()
