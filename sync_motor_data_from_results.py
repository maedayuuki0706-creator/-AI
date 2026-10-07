import json,os,re
from collections import defaultdict
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

SID=os.getenv("BOAT_SHEET_ID","1dbUPyfxjIRaT-G8F_LlGMX7Ld_ZB951UmF4HpW_PYJo")
MOTOR="モーターデータ"; BASE="モーター自動集計基準_20261008"; FOOT="足回り推移"
FORCED={"常滑":"20261006"}

def nd(v):
    s=str(v or "").strip().replace("/","").replace("-","")
    return s if len(s)==8 and s.isdigit() else ""
def fd(s): return f"{s[:4]}/{s[4:6]}/{s[6:]}" if len(s)==8 else s
def iv(v):
    try:return int(float(str(v).replace(",","")))
    except:return 0
def val(r,i): return r[i-1] if len(r)>=i else ""
def key(r):
    v=val(r,2).strip(); m=val(r,3).strip()
    try:m=str(int(float(m)))
    except:return None
    return (v,m) if v else None

def cycles():
    out=dict(FORCED)
    try:
        x=json.load(open("data/motor_cycles.json",encoding="utf-8"))
        for c in x.get("cycles",[]):
            v=str(c.get("venue") or "").strip(); d=nd(c.get("start_date"))
            if v and d: out[v]=max(out.get(v,""),d)
    except Exception: pass
    return out

def main():
    creds=Credentials.from_service_account_info(json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),scopes=["https://www.googleapis.com/auth/spreadsheets"])
    b=gspread.authorize(creds).open_by_key(SID)
    ws=b.worksheet(MOTOR); base=b.worksheet(BASE).get_all_values(); foot=b.worksheet(FOOT).get_all_values()
    cur=ws.get_all_values(); bm={key(r):r for r in base[1:] if key(r)}
    fm=defaultdict(list)
    for r in foot[1:]:
        if len(r)<18: continue
        v=val(r,1).strip(); d=nd(val(r,3)); m=val(r,8).strip(); n=val(r,6).strip()
        try:m=str(int(float(m))); rn=iv(val(r,10)); fin=iv(val(r,18))
        except:continue
        if not v or not d or fin not in range(1,7): continue
        fm[(v,m)].append({"d":d,"r":rn,"f":fin,"n":n,"p":val(r,49).strip()})
    for a in fm.values(): a.sort(key=lambda x:(x["d"],x["r"]))
    cs=cycles(); up=[]; changed=resetn=added=0
    for no,r in enumerate(cur[1:],2):
        k=key(r)
        if not k: continue
        v,m=k; br=bm.get(k); ss=nd(val(r,4)); fs=cs.get(v,""); start=max(ss,fs) if ss else fs
        if not start: continue
        bs=nd(val(br or [],4)); bu=nd(val(br or [],5)); reset=(not br) or (bs and start>bs)
        if reset: w=s=t=st=0; cutoff=""
        else: w,s,t,st=[iv(val(br,i)) for i in (9,10,11,12)]; cutoff=bu or start
        allr=[x for x in fm.get(k,[]) if x["d"]>=start]
        delta=[x for x in allr if reset or x["d"]>cutoff]
        if not reset and not delta and start==ss: continue
        w+=sum(x["f"]==1 for x in delta); s+=sum(x["f"]==2 for x in delta); t+=sum(x["f"]==3 for x in delta); st+=len(delta); added+=len(delta)
        g=round((w+s)/st*100,2) if st else 0; h=round((w+s+t)/st*100,2) if st else 0
        latest=allr[-1] if allr else None; day=latest["d"] if latest else start
        memo=re.sub(r"｜?現行モーター使用開始=\d{4}/\d{2}/\d{2}|｜?結果自動集計 \d{4}/\d{2}/\d{2}まで|｜?旧モーター周期を分離","",val(r,24)).strip("｜ ")
        bits=([memo] if memo else [])+[f"現行モーター使用開始={fd(start)}",f"結果自動集計 {fd(day)}まで"]
        if reset: bits.append("旧モーター周期を分離")
        up += [
          {"range":f"D{no}:E{no}","values":[[fd(start),fd(day)]]},
          {"range":f"G{no}:L{no}","values":[[g,h,w,s,t,st]]},
          {"range":f"V{no}","values":[[latest["n"] if latest else ""]]},
          {"range":f"X{no}","values":[["｜".join(bits)]]},
        ]
        parts=next((x for x in reversed(allr) if x["p"]),None)
        if parts: up.append({"range":f"W{no}","values":[[f"{fd(parts['d'])} {parts['r']}R時点｜{parts['p']}"]]})
        elif reset: up.append({"range":f"W{no}","values":[[""]]})
        if reset:
            up += [{"range":f"F{no}","values":[[""]]},{"range":f"M{no}:U{no}","values":[["","","","","","","","",""]]}]; resetn+=1
        changed+=1
    for i in range(0,len(up),250): ws.batch_update(up[i:i+250],raw=True)
    print(json.dumps({"changed_motor_rows":changed,"cycle_reset_rows":resetn,"settled_result_rows_added":added,"writes":len(up)},ensure_ascii=False))
if __name__=="__main__": main()
