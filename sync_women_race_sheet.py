"""Auto-append women-only meeting results to the 女子戦 sheet."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import json, os, re, unicodedata
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

import direct_discord_notify as base
from race_context import parse_result

JST = ZoneInfo("Asia/Tokyo")
SID = os.getenv("BOAT_SHEET_ID","1dbUPyfxjIRaT-G8F_LlGMX7Ld_ZB951UmF4HpW_PYJo")
SHEET = os.getenv("WOMEN_SHEET","女子戦")
BACKFILL_DAYS = max(1,int(os.getenv("WOMEN_BACKFILL_DAYS","3")))
KEYWORDS = (
    "ヴィーナスシリーズ","オールレディース","レディースチャンピオン",
    "レディースオールスター","クイーンズクライマックス","女子王座","プリンセスカップ",
)

def norm(s):
    return unicodedata.normalize("NFKC",str(s or "")).replace("\u3000"," ").strip()

def extract_title(raw):
    for pat in (
        r'heading2_titleName[^>]*>(.*?)</[^>]+>',
        r'class=["\'][^"\']*(?:titleName|raceTitle|eventTitle)[^"\']*["\'][^>]*>(.*?)</[^>]+>',
    ):
        m=re.search(pat,raw,re.I|re.S)
        if m:
            t=norm(base.textify(m.group(1)))
            if t:return t
    lines=[norm(x) for x in base.textify(raw).splitlines()]
    hits=[x for x in lines if any(k in x for k in KEYWORDS)]
    return sorted(hits,key=lambda x:(len(x),x))[0] if hits else ""

def classify(title,grade):
    t=norm(title)
    if "ヴィーナスシリーズ" in t:return "ヴィーナスシリーズ","一般"
    if "オールレディース" in t:return "オールレディース","G3"
    if not any(k in t for k in KEYWORDS[2:]):return None
    if "プリンセスカップ" in t:return "女子G3","G3"\n    if grade=="G1":return "女子G1","G1"
    if grade=="G2":return "女子G2","G2"
    if grade=="G3":return "女子G3","G3"
    return "女子戦",grade or "一般"

def day_label(raw):
    m=re.search(r"(最終日|初日|[2-9]日目)",norm(base.textify(raw)))
    return m.group(1) if m else ""

def existing_keys(values):
    out=set()
    for r in values[4:]:
        if len(r)<8:continue
        d=str(r[0] or "").replace("/","").replace("-","").strip()
        j=str(r[1] or "").strip().zfill(2)
        try:n=int(float(r[7]))
        except:continue
        if len(d)==8 and j.isdigit():out.add((d,j,n))
    return out

def make_row(day,jcd,venue,category,grade,title,section_day,result):
    lanes=[int(x) for x in str(result["trifecta"]).split("-")]
    pay=int(result["payout_per_100"]); h=lanes[0]
    return [
        f"{day[:4]}/{day[4:6]}/{day[6:]}",int(jcd),venue,category,grade,title,section_day,
        int(result["rno"]),lanes[0],lanes[1],lanes[2],result["trifecta"],pay,
        "○" if h==1 else "","○" if h!=1 else "","○" if h>=4 else "",
        "○" if pay>=10000 else "","○" if pay>=30000 else "","○" if pay>=100000 else "",
        "",result["source_url"],"BOAT RACE公式自動取得",""
    ]

def inspect_meeting(day,jcd):
    try:
        raw=base.fetch(base.official_url("racelist",day,jcd,1))
    except Exception:return None
    title=extract_title(raw); grade=base.detect_event_grade(raw); kind=classify(title,grade)
    if not kind:return None
    return {"day":day,"jcd":jcd,"venue":base.VENUES.get(jcd,jcd),"raw":raw,
            "title":title,"category":kind[0],"grade":kind[1],"section_day":day_label(raw)}

def fetch_result(meeting,rno):
    try:
        d=meeting["day"]; j=meeting["jcd"]
        raw=base.fetch(base.official_url("raceresult",d,j,rno))
        result=parse_result(raw,d,j,rno); result["rno"]=rno
        return make_row(d,j,meeting["venue"],meeting["category"],meeting["grade"],
                        meeting["title"],meeting["section_day"],result)
    except Exception:return None

def main():
    raw=os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON secret is required")
    creds=Credentials.from_service_account_info(json.loads(raw),scopes=["https://www.googleapis.com/auth/spreadsheets"])
    book=gspread.authorize(creds).open_by_key(SID); ws=book.worksheet(SHEET)
    values=ws.get_all_values(); keys=existing_keys(values)
    today=datetime.now(JST).date(); days=[(today-timedelta(days=i)).strftime("%Y%m%d") for i in range(BACKFILL_DAYS)]
    meetings=[]
    for day in sorted(days):
        try:venues=base.discover_venues(day)
        except Exception:venues=[]
        with ThreadPoolExecutor(max_workers=12) as pool:
            futs=[pool.submit(inspect_meeting,day,j) for j in venues]
            for fut in as_completed(futs):
                m=fut.result()
                if m:meetings.append(m)

    jobs=[]
    with ThreadPoolExecutor(max_workers=12) as pool:
        futmap={}
        for m in meetings:
            for rno in range(1,13):
                k=(m["day"],m["jcd"],rno)
                if k in keys:continue
                futmap[pool.submit(fetch_result,m,rno)]=(m,rno)
        for fut in as_completed(futmap):
            row=fut.result()
            if not row:continue
            m,rno=futmap[fut]; k=(m["day"],m["jcd"],rno)
            if k in keys:continue
            jobs.append((k,row)); keys.add(k)

    jobs.sort(key=lambda x:(x[0][0],x[0][1],x[0][2]))
    rows=[r for _,r in jobs]
    if not rows:
        print(json.dumps({"detected_meetings":len(meetings),"rows_appended":0},ensure_ascii=False)); return

    last=4
    for i,r in enumerate(values,1):
        if any(str(v or "").strip() for v in r[:23]):last=i
    start=last+1; end=start+len(rows)-1
    if end>ws.row_count:ws.add_rows(max(200,end-ws.row_count+50))
    ws.update(rows,f"A{start}:W{end}",raw=True)
    book.batch_update({"requests":[{"copyPaste":{
        "source":{"sheetId":ws.id,"startRowIndex":435,"endRowIndex":436,"startColumnIndex":0,"endColumnIndex":23},
        "destination":{"sheetId":ws.id,"startRowIndex":start-1,"endRowIndex":end,"startColumnIndex":0,"endColumnIndex":23},
        "pasteType":"PASTE_FORMAT","pasteOrientation":"NORMAL"}}]})
    print(json.dumps({"detected_meetings":len(meetings),"rows_appended":len(rows),"range":f"A{start}:W{end}"},ensure_ascii=False))

if __name__=="__main__":main()
