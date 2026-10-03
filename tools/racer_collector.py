import csv, re, time, random, sys
from pathlib import Path
import requests
from bs4 import BeautifulSoup

START=int(sys.argv[1]) if len(sys.argv)>1 else 3388
END=int(sys.argv[2]) if len(sys.argv)>2 else 4150
OUT=Path(f"data/racers_{START}_{END}.csv")
BASE="https://www.boatrace.jp/owpc/pc/data/racersearch"\nDATAZEME="https://abeken1026395.github.io/pallas-mercato-7k9/players/"
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; BoatAI-RacerDB/1.0)"}
FIELDS=["登録番号","選手名","級別","支部","登録期","1C進入率","2C進入率","3C進入率","4C進入率","5C進入率","6C進入率","1C3連対率","2C3連対率","3C3連対率","4C3連対率","5C3連対率","6C3連対率","1C平均ST","2C平均ST","3C平均ST","4C平均ST","5C平均ST","6C平均ST","1Cスタート順","2Cスタート順","3Cスタート順","4Cスタート順","5Cスタート順","6Cスタート順"]
s=requests.Session(); s.headers.update(HEADERS)

def clean(x): return re.sub(r"\s+"," ",x.replace("\xa0"," ").replace("　"," ")).strip()

def get(url):
    for i in range(4):
        try:
            r=s.get(url,timeout=20)
            if r.status_code==200: return r
            if r.status_code not in (429,500,502,503,504): return None
        except requests.RequestException: pass
        time.sleep(2**i)
    return None

def labeled(soup,label):
    tag=soup.find(lambda t: t.name in ("dt","th") and clean(t.get_text())==label)
    if not tag:return ""
    nxt=tag.find_next_sibling("dd" if tag.name=="dt" else "td")
    return clean(nxt.get_text()) if nxt else ""

def six_after_heading(soup, heading_text):
    node=soup.find(string=lambda x:x and heading_text in clean(x))
    if not node:return [""]*6
    container=node.parent
    table=container.find_next("table")
    vals=[""]*6
    if table:
        for tr in table.find_all("tr"):
            cells=[clean(c.get_text()) for c in tr.find_all(["th","td"])]
            if len(cells)>=2 and cells[0] in list("123456"):
                vals[int(cells[0])-1]=cells[-1]
    return vals

def datazeme_fields(toban, name):
    """Collect public player-atlas data without assuming its internal schema.
    The site is JS-driven, so probe likely public data endpoints and player URLs.
    Unknown/unavailable fields are simply omitted.
    """
    candidates=[
        f"{DATAZEME}{toban}/",
        f"{DATAZEME}?toban={toban}",
        f"{DATAZEME}?id={toban}",
        f"https://abeken1026395.github.io/pallas-mercato-7k9/data/players.json",
        f"https://abeken1026395.github.io/pallas-mercato-7k9/players/data.json",
    ]
    out={}
    for url in candidates:
        r=get(url)
        if not r: continue
        ct=r.headers.get("content-type","")
        if "json" in ct or r.text.lstrip().startswith(("{","[")):
            try:
                obj=r.json()
                pool=obj if isinstance(obj,list) else obj.get("players",[]) if isinstance(obj,dict) else []
                for p in pool:
                    if not isinstance(p,dict): continue
                    ident=str(p.get("toban") or p.get("registration") or p.get("id") or "")
                    pname=clean(str(p.get("name","")))
                    if ident==str(toban) or (pname and pname.replace(" ","")==name.replace(" ","")):
                        for k,v in p.items():
                            if isinstance(v,(str,int,float,bool)) or v is None:
                                out["データ攻め_"+str(k)]=v
                        return out
            except Exception:
                pass
        soup=BeautifulSoup(r.content,"html.parser")
        text=clean(soup.get_text(" "))
        if str(toban) not in text and name.replace(" ","") not in text.replace(" ",""): continue
        for tr in soup.find_all("tr"):
            cells=[clean(x.get_text()) for x in tr.find_all(["th","td"])]
            if len(cells)>=2 and cells[0] and cells[1]:
                out["データ攻め_"+cells[0]]=cells[1]
        for dt in soup.find_all("dt"):
            dd=dt.find_next_sibling("dd")
            if dd:
                k,v=clean(dt.get_text()),clean(dd.get_text())
                if k and v: out["データ攻め_"+k]=v
        if out:return out
    return out

def racer(toban):
    rp=get(f"{BASE}/profile?toban={toban}")
    if not rp or "該当する選手が見つかりません" in rp.text:return None
    sp=BeautifulSoup(rp.content,"html.parser")
    ne=sp.find("p",class_="memberData_name")
    if not ne:return None
    row={"登録番号":str(toban),"選手名":clean(ne.get_text()),"級別":labeled(sp,"級別"),"支部":labeled(sp,"支部"),"登録期":labeled(sp,"登録期")}
    rc=get(f"{BASE}/course?toban={toban}")
    if rc:
        sc=BeautifulSoup(rc.content,"html.parser")
        groups=[("進入率","コース別進入率"),("3連対率","コース別3連対率"),("平均ST","コース別平均スタートタイミング"),("スタート順","コース別スタート順")]
        for key,heading in groups:
            vals=six_after_heading(sc,heading)
            for i,v in enumerate(vals,1):row[f"{i}C{key}"]=v
    return row

def main():
    OUT.parent.mkdir(parents=True,exist_ok=True)
    rows=[]
    for n in range(START,END+1):
        d=racer(n)
        if d:
            rows.append(d); print(f"{n} {d['選手名']} {d['級別']}",flush=True)
        else: print(f"{n} skip",flush=True)
        time.sleep(random.uniform(.7,1.1))
    with OUT.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
    print(f"saved {len(rows)} racers -> {OUT}")

if __name__=="__main__": main()
