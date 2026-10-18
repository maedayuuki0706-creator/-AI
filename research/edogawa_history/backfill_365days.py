#!/usr/bin/env python3
"""江戸川くん・過去365日を独立取得。既存予想/Discord/Xへの副作用なし。"""
import csv, io, json, hashlib, re, time, sys, tempfile, urllib.request, urllib.error
from pathlib import Path
from datetime import date, timedelta
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

START=date(2025,10,18); END=date(2026,10,17)
DIR=Path("data/research_edogawa_history/20251018_20261017")
KEYS=["race_id","date","race_no","method","first","second","third","fourth","fifth","sixth","wind_dir","wind_m","wave_cm","weather","invalid_or_abnormal","course1_st","course2_st","course3_st","course4_st","course5_st","course6_st","data_source","source_url","sha256"]
def grab(url):
    for n in range(3):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"EdogawaResearch/1.0","Accept":"text/csv,text/plain,application/octet-stream,*/*"})
            with urllib.request.urlopen(req,timeout=24) as r:return r.read()
        except urllib.error.HTTPError as e:
            if e.code==404:return None
            if e.code not in (429,500,502,503,504):return None
        except Exception:pass
        time.sleep(1.2*(n+1))
    return None
def clean(s):return re.sub(r"[\s\u3000]+","",str(s or ""))
def num(x,cast=int):
    try:return cast(clean(x))
    except (ValueError,TypeError):return None
def mirror(d,body,url):
    answer=[];digest=hashlib.sha256(body).hexdigest()
    for x in csv.DictReader(io.StringIO(body.decode("utf-8-sig",errors="replace"))):
        code=clean(x.get("レースコード"))
        if len(code)!=12 or code[:8]!=d.strftime("%Y%m%d") or code[8:10]!="03":continue
        pos=[num(x.get(str(k)+"着_艇番")) for k in range(1,7)]
        bad=any(y is None for y in pos) or len(set(y for y in pos if y is not None))!=6
        z=dict(zip(["first","second","third","fourth","fifth","sixth"],pos))
        z.update(race_id=code,date=d.isoformat(),race_no=int(code[10:]),method=clean(x.get("決まり手")),wind_dir=clean(x.get("風向")),wind_m=num(x.get("風速(m)"),float),wave_cm=num(x.get("波の高さ(cm)"),float),weather=clean(x.get("天候")),invalid_or_abnormal=bad,data_source="BoatraceCSV_nonofficial",source_url=url,sha256=digest)
        for k in range(1,7):z["course"+str(k)+"_st"]=num(x.get(str(k)+"コース_スタートタイミング"),float)
        answer.append(z)
    return answer
def official(d,body,url):
    try:
        import lhafile
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/"result.lzh";p.write_bytes(body)
            a=lhafile.Lhafile(str(p))
            names=[y.filename for y in a.infolist() if y.filename.upper().endswith(".TXT")]
            if not names:raise ValueError("TXT unavailable")
            txt=a.read(names[0]).decode("cp932",errors="replace")
    except Exception as e:raise RuntimeError("LZH decode: "+str(e))
    section=re.search(r"(?ms)^03KBGN\s*$(.*?)^03KEND\s*$",txt)
    if not section:return []
    out=[];cur=None;boats=[];method=""
    def emit():
        if not cur:return
        places={b["finish"]:b["boat"] for b in boats if isinstance(b["finish"],int)}
        pos=[places.get(i) for i in range(1,7)]
        bad=len(boats)!=6 or any(v is None for v in pos) or len(set(v for v in pos if v))!=6
        item=dict(zip(["first","second","third","fourth","fifth","sixth"],pos))
        item.update(race_id=f"{d:%Y%m%d}03{cur['r']:02}",date=d.isoformat(),race_no=cur["r"],method=method,wind_dir=cur["wind_dir"],wind_m=cur["wind_m"],wave_cm=cur["wave_cm"],weather=cur["weather"],invalid_or_abnormal=bad,data_source="BOATRACE_official_K",source_url=url,sha256=hashlib.sha256(body).hexdigest())
        for k in range(1,7):
            hit=next((b for b in boats if b["course"]==k),None)
            item["course"+str(k)+"_st"]=hit["st"] if hit else None
        out.append(item)
    for line in section.group(1).splitlines():
        h=re.match(r"^\s*(\d{1,2})R\s+.*?H\s*\d{4}m(.*)",line)
        if h:
            emit();wind=re.search(r"風\s*([^\s0-9]+)\s*(\d+)m",h.group(2));wave=re.search(r"波\s*(\d+)cm",h.group(2))
            cur={"r":int(h.group(1)),"wind_dir":clean(wind.group(1)) if wind else "", "wind_m":num(wind.group(2)) if wind else None,"wave_cm":num(wave.group(1)) if wave else None,"weather":clean(re.search(r"H\s*\d{4}m\s*(.*?)\s*風",line).group(1)) if "風" in line else ""}
            boats=[];method="";continue
        if cur is None:continue
        if "ﾚｰｽﾀｲﾑ" in line or "レースタイム" in line:
            method=clean(line.split("ﾚｰｽﾀｲﾑ")[-1].split("レースタイム")[-1]);continue
        m=re.match(r"^\s*(\d{2}|F\d|S\d|L\d|K\d)\s+([1-6])\s+\d{4}\s+(.+)",line)
        if not m:continue
        follow=re.search(r"\s\d{1,3}\s+\d{1,3}\s+\d\.\d{2}\s+([1-6])\s+([FfLl]?[0-9\.\-]+)",m.group(3))
        boats.append({"finish":int(m.group(1)) if m.group(1).isdigit() else m.group(1),"boat":int(m.group(2)),"course":int(follow.group(1)) if follow else None,"st":num(follow.group(2),float) if follow else None})
    emit()
    return out
def date_urls(d):
    return f"https://boatracecsv.github.io/data/results/realtime/{d:%Y/%m/%d}.csv", f"https://www1.mbrace.or.jp/od2/K/{d:%Y%m}/k{d:%y%m%d}.lzh"
def day(d):
    a,b=date_urls(d);bytes_=grab(a);problem=""
    if bytes_:
        try:
            races=mirror(d,bytes_,a)
            return d,races,{"date":d.isoformat(),"status":"found" if races else "no_edogawa_race","races":len(races),"source":a,"error":""}
        except Exception as e:problem=str(e)
    k=grab(b)
    if k:
        try:
            races=official(d,k,b)
            return d,races,{"date":d.isoformat(),"status":"found" if races else "no_edogawa_race","races":len(races),"source":b,"error":problem}
        except Exception as e:problem=problem+";"+str(e)
    return d,[],{"date":d.isoformat(),"status":"missing_source","races":0,"source":b,"error":problem or "both sources inaccessible"}
def write_csv(p,fields,rows):
    with p.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)
def main():
    DIR.mkdir(parents=True,exist_ok=True)
    dates=[START+timedelta(days=i) for i in range((END-START).days+1)]
    print("Checking calendar days:",len(dates),flush=True)
    result={}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures={executor.submit(day,d):d for d in dates}
        for future in as_completed(futures):
            d,rows,state=future.result();result[d]=(rows,state)
            if len(result)%35==0:print("Processed",len(result),"/",len(dates),flush=True)
    coverage=[result[d][1] for d in dates]
    race_map={}
    for d in dates:
        for r in result[d][0]:race_map[r["race_id"]]=r
    rows=[race_map[k] for k in sorted(race_map)]
    write_csv(DIR/"races.csv",KEYS,rows)
    write_csv(DIR/"coverage.csv",["date","status","races","source","error"],coverage)
    stats=defaultdict(Counter)
    for r in rows:
        if r["invalid_or_abnormal"] or not all(r.get(z) for z in ("first","second","third")):continue
        stats[(r["first"],r["method"])][(r["second"],r["third"])]+=1
    assoc=[]
    for (head,method),count in sorted(stats.items()):
        n=sum(count.values())
        for (b,c),v in count.most_common():assoc.append({"head":head,"method":method,"second":b,"third":c,"races":v,"group_total":n,"group_share":round(v/n,4)})
    write_csv(DIR/"finish_given_method.csv",["head","method","second","third","races","group_total","group_share"],assoc)
    summary={"start":str(START),"end":str(END),"calendar_days":len(dates),"checked_days":len(coverage),"edogawa_days":sum(x["races"]>0 for x in coverage),"race_rows":len(rows),"complete_finish_rows":sum(not r["invalid_or_abnormal"] for r in rows),"missing_days":sum(x["status"]=="missing_source" for x in coverage),"method_counts":dict(Counter(r["method"] for r in rows)),"head_counts":dict(Counter(str(r["first"]) for r in rows)),"data_origin":dict(Counter(r["data_source"] for r in rows)),"caveat":"BoatraceCSV is nonofficial; verify against BOAT RACE before adopting parameters. No video validation of tactics. No production logic changed."}
    (DIR/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    if summary["missing_days"]:print("INCOMPLETE: check coverage.csv before calling this a full-year dataset",file=sys.stderr)
if __name__=="__main__":main()
