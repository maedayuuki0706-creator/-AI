"""Auto-update player weak-motor recovery ratings (選手データ V/W).

Reads Google Sheets as the source of truth and recomputes from scratch.
Does not import prediction, Discord, or X code.
"""
import json, math, os
from collections import defaultdict
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID=os.getenv("BOAT_SHEET_ID","1dbUPyfxjIRaT-G8F_LlGMX7Ld_ZB951UmF4HpW_PYJo")
VENUES=["桐生","戸田","江戸川","平和島","多摩川","浜名湖","蒲郡","常滑","津","三国","びわこ","住之江","尼崎","鳴門","丸亀","児島","宮島","徳山","下関","若松","芦屋","福岡","唐津","大村"]

def num(v):
    if v is None: return None
    s=str(v).strip().replace("%","")
    if not s: return None
    try:
        x=float(s)
        return x if math.isfinite(x) else None
    except ValueError: return None

def norm_date(v):
    return str(v or "").strip().replace("-","/")

def main():
    raw=os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON secret is required")
    info=json.loads(raw)
    creds=Credentials.from_service_account_info(info,scopes=["https://www.googleapis.com/auth/spreadsheets"])
    book=gspread.authorize(creds).open_by_key(SPREADSHEET_ID)

    motor_maps={}
    section_dist={}
    for venue in VENUES:
        try: vals=book.worksheet(venue).get_all_values()
        except gspread.WorksheetNotFound: continue
        mm={}; sd=defaultdict(list)
        for r in vals[2:]:
            if len(r)<13: continue
            reg=(r[1] if len(r)>1 else "").strip(); sec=norm_date(r[2] if len(r)>2 else "")
            motor=(r[8] if len(r)>8 else "").strip(); two=num(r[10] if len(r)>10 else None)
            if not reg or not sec or not motor or two is None: continue
            if two<=1: two*=100
            grade=(r[12] if len(r)>12 else "").strip().upper()
            mm[(reg,sec,motor)]={"two":two,"grade":grade}; sd[sec].append(two)
        motor_maps[venue]=mm; section_dist[venue]=sd

    foot=book.worksheet("足回り推移").get_all_values()
    groups=defaultdict(list)
    for r in foot[1:]:
        if len(r)<32: continue
        venue=r[0].strip(); sec=norm_date(r[1]); reg=r[4].strip(); motor=r[7].strip()
        if venue and sec and reg and motor: groups[(venue,sec,reg,motor)].append(r)

    assignments=[]
    for (venue,sec,reg,motor), rows in groups.items():
        md=motor_maps.get(venue,{}).get((reg,sec,motor))
        arr=sorted(section_dist.get(venue,{}).get(sec,[]))
        if not md or not arr: continue
        pct=sum(v<=md["two"] for v in arr)/len(arr)
        weak=(md["grade"]=="D" or (md["grade"]=="C" and pct<=.35) or pct<=.20)
        if not weak: continue
        scores=[]
        for r in rows:
            ds=[num(r[i]) if len(r)>i else None for i in (19,20,21,22)]
            if any(v is None for v in ds) or any(abs(v)>2 for v in ds): continue
            w=num(r[31] if len(r)>31 else None)
            if w is None: w=1.0
            scores.append((ds[0]*.15+ds[1]*.25+ds[2]*.40+ds[3]*.20)*w)
        if not scores: continue
        avg=sum(scores)/len(scores); pos=sum(v>0 for v in scores)/len(scores)
        late=scores[len(scores)//2:]; late_avg=sum(late)/len(late)
        evidence=avg*.45+late_avg*.35+pos*.20
        assignments.append((reg,len(scores),evidence))

    agg=defaultdict(lambda:{"sum":0.0,"runs":0,"meets":0})
    for reg,n,e in assignments:
        a=agg[reg]; a["sum"]+=e*n; a["runs"]+=n; a["meets"]+=1

    ratings={}
    for reg,a in agg.items():
        score=a["sum"]/a["runs"]; rating=1.0
        if score>=.30: rating=4.0
        elif score>=.15: rating=3.5
        elif score>=.07: rating=3.0
        elif score>=.02: rating=2.5
        elif score>=-.03: rating=2.0
        elif score>=-.10: rating=1.5
        if a["meets"]>=2 and score>=.30: rating=4.5
        ratings[reg]=(rating,a["meets"])

    ws=book.worksheet("選手データ"); players=ws.get_all_values()
    output=[]
    matched=0
    for r in players[1:]:
        reg=(r[0] if r else "").strip()
        if reg in ratings:
            v,w=ratings[reg]; output.append([v,w]); matched+=1
        else: output.append(["",""])
    if output:
        ws.update(output,range_name=f"V2:W{len(output)+1}",value_input_option="RAW")
    print(json.dumps({"weak_assignments":len(assignments),"rated_players":len(ratings),"written":matched},ensure_ascii=False))

if __name__=="__main__":
    main()
