"""Read-only coverage audit against complete daily race-card manifests.

Missing manifest is UNKNOWN, never a day with zero scheduled races.
Missing archives are not assumed canceled; abnormal results are flagged separately.
"""
from __future__ import annotations
import argparse
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path
from analytics import as_day, is_six, VENUES
from analyst_context import METHODS, valid_number


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def manifest(path, day):
    data = read_json(path)
    if data.get("complete") is not True or str(data.get("day")) != day or not isinstance(data.get("races"), dict):
        raise ValueError("incomplete or invalid manifest")
    keys = set()
    for key, row in data["races"].items():
        code = str(row["jcd"]).zfill(2)
        n = row["rno"]
        if code not in {f"{i:02}" for i in range(1,25)} or type(n) is not int or not 1 <= n <= 12 or key != f"{code}:{n}":
            raise ValueError("invalid race identity in manifest")
        keys.add((code,n))
    return keys


def audit_race(path, day, code, n):
    if not path.exists():
        return {"status":"missing_archive","issues":["missing_archive"]}
    try:
        r = read_json(path)
        if str(r["day"]) != day or str(r["jcd"]).zfill(2) != code or r["rno"] != n or not is_six(r["rows"]):
            raise ValueError("race identity or lineup mismatch")
        rows = r["rows"]
        issues = []
        for field, lo, hi in [("exhibition_time",4,10),("actual_st",0,0.99),("wind_m",0,40),("wave_cm",0,200)]:
            missing = [b["lane"] for b in rows if not valid_number(b.get(field),lo,hi)]
            if missing:
                issues.append({"field":field,"lanes":missing})
        if r.get("settled") is not True:
            status = "unsettled_or_unverified"
        elif (any(type(b.get("finish")) is not int or type(b.get("actual_course")) is not int for b in rows)
              or sorted(b["finish"] for b in rows) != list(range(1,7))
              or sorted(b["actual_course"] for b in rows) != list(range(1,7))):
            status = "abnormal_or_incomplete_result"
        else:
            status = "normal_result"
            winner = next(b for b in rows if b["finish"] == 1)
            if winner.get("method") not in METHODS:
                issues.append({"field":"winning_method","lanes":[winner["lane"]]})
        return {"status":status,"issues":issues}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {"status":"invalid_archive","issues":["invalid_archive"]}


def coverage(cards, archive, start, end):
    first,last = as_day(start),as_day(end)
    if first > last:
        raise ValueError("start must not exceed end")
    days=[]; totals=Counter()
    venues={f"{i:02}":Counter() for i in range(1,25)}
    day=first
    while day <= last:
        d=day.strftime("%Y%m%d")
        path=Path(cards)/f"{d}.json"
        try:
            expected=manifest(path,d)
        except (OSError,ValueError,TypeError,KeyError,AttributeError):
            days.append({"day":d,"manifest_status":"unknown","expected":None})
            totals["unknown_manifest_days"]+=1
            day+=timedelta(days=1)
            continue
        totals["known_manifest_days"]+=1
        actual={p.stem for p in (Path(archive)/d).glob("*.json")}
        expected_stems={f"{code}_{n:02}" for code,n in expected}
        records=[]
        for code,n in sorted(expected):
            v=audit_race(Path(archive)/d/f"{code}_{n:02}.json",d,code,n)
            for c in (totals,venues[code]):
                c["expected"]+=1
                c[v["status"]]+=1
                if v["issues"]: c["races_with_issues"]+=1
            records.append({"venue":code,"race_no":n,**v})
        days.append({"day":d,"manifest_status":"complete","expected":len(expected),
                     "unexpected_files":sorted(actual-expected_stems),"races":records})
        day+=timedelta(days=1)
    clean=(totals["unknown_manifest_days"]==0 and totals["expected"]>0
           and totals["normal_result"]==totals["expected"] and totals["races_with_issues"]==0
           and not any(d.get("unexpected_files") for d in days))
    return {"schema":"analyst-coverage-v1","start":start,"end":end,"totals":dict(totals),
            "all_24_venues":[{"code":c,"name":VENUES[int(c)-1],**dict(v)} for c,v in venues.items()],
            "days":days,"clean_normal_result_subset":clean,
            "limitations":["Manifest coverage is not independently verified against official schedules.",
                           "Abnormal results require official cancellation/return/F reconciliation, not silent exclusion.",
                           "Original exhibition, tide and motor cycle coverage are not assessed here."]}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--cards",type=Path,required=True)
    ap.add_argument("--archive",type=Path,required=True)
    ap.add_argument("--start",required=True);ap.add_argument("--end",required=True)
    args=ap.parse_args()
    print(json.dumps(coverage(args.cards,args.archive,args.start,args.end),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
