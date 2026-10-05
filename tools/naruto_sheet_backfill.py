from __future__ import annotations
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
from pathlib import Path

import direct_discord_notify as base
from race_context import parse_result

DAYS = ["20260927","20260928","20260929","20260930","20261001","20261002"]
JCD = "14"
OUT = Path("naruto_backfill_20260927_20261002.json")

def sort_key(rec):
    return (rec["day"], int(rec["rno"]))

def fetch_one(day, rno):
    raw=base.fetch(base.official_url("raceresult", day, JCD, rno))
    return parse_result(raw, day, JCD, rno)

def main():
    races=[]
    errors=[]
    jobs=[(day,rno) for day in DAYS for rno in range(1,13)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures={pool.submit(fetch_one,day,rno):(day,rno) for day,rno in jobs}
        for future in as_completed(futures):
            day,rno=futures[future]
            try:
                races.append(future.result())
            except Exception as exc:
                errors.append({"day":day,"rno":rno,"error":f"{type(exc).__name__}: {exc}"})
    races.sort(key=lambda x:(x["day"],int(x["rno"])))

    grouped=defaultdict(list)
    for race in races:
        for item in race.get("finish") or []:
            row=dict(item)
            row["day"]=race["day"]
            row["rno"]=race["rno"]
            row["method"]=race.get("method") if item.get("finish")==1 else None
            row["source_url"]=race.get("source_url")
            grouped[str(item.get("racer_id"))].append(row)

    racers={}
    for rid, rows in grouped.items():
        rows=sorted(rows,key=sort_key)
        numeric_st=[float(x["st"]) for x in rows if isinstance(x.get("st"),(int,float))]
        numeric_course=[int(x["course"]) for x in rows if isinstance(x.get("course"),int)]
        normal=[x for x in rows if x.get("status")=="finished" and isinstance(x.get("finish"),int)]
        racers[rid]={
            "racer_id":rid,
            "name":rows[0].get("name"),
            "starts":len(rows),
            "normal_finishes":len(normal),
            "avg_st":round(sum(numeric_st)/len(numeric_st),3) if numeric_st else None,
            "avg_course":round(sum(numeric_course)/len(numeric_course),2) if numeric_course else None,
            "wins":sum(1 for x in normal if x["finish"]==1),
            "seconds":sum(1 for x in normal if x["finish"]==2),
            "thirds":sum(1 for x in normal if x["finish"]==3),
            "races":rows,
        }

    payload={
        "generated_at":datetime.utcnow().isoformat()+"Z",
        "days":DAYS,
        "jcd":JCD,
        "race_count":len(races),
        "error_count":len(errors),
        "errors":errors,
        "racer_count":len(racers),
        "racers":racers,
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
        "race_count":len(races),
        "error_count":len(errors),
        "racer_count":len(racers),
        "output":str(OUT)
    },ensure_ascii=False))

if __name__=="__main__":
    main()
