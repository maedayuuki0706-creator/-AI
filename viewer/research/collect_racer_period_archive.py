"""Discover official BOAT RACE racer-period LZH links; fetch at bounded rate.

Research-only, no secrets, no writes to prod, no raw source commits.
Page: https://www.boatrace.jp/owpc/pc/extra/data/download.html
"""
import hashlib, json, re, time
from pathlib import Path
from datetime import datetime,timezone
from html.parser import HTMLParser
from urllib.request import Request,urlopen
from urllib.parse import urljoin,urlsplit
from urllib.error import HTTPError,URLError

PAGE="https://www.boatrace.jp/owpc/pc/extra/data/download.html"
MAX_ARCHIVES=60
DELAY=1.8
MAGIC=re.compile(rb"^.{2}-lh[0-7]-",re.S)
OUT=Path("/tmp/boat-navi-racer-periods")
class Parser(HTMLParser):
    def __init__(self):super().__init__();self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag!="a":return
        d=dict(attrs); href=d.get("href","")
        uri=urljoin(PAGE,href);url=urlsplit(uri)
        if url.hostname in ("www.boatrace.jp","boatrace.jp") and re.search(r"/kibetsu/fan\d{4}\.lzh$",url.path,re.I):
            self.links.append(uri)

def fetch(url,limit):
    with urlopen(Request(url,headers={"User-Agent":"BoatAINavi-LowRate-RacerStudy/1.0"}),timeout=30) as r:
        if r.status!=200:raise ValueError("Unexpected status")
        b=r.read(limit+1)
    if len(b)>limit:raise ValueError("File over limit")
    return b

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    html=fetch(PAGE,1_000_000).decode("utf-8",errors="replace")
    p=Parser();p.feed(html)
    urls=sorted(set(p.links),reverse=True)
    if not (1<=len(urls)<=MAX_ARCHIVES):raise RuntimeError(f"Unexpected link count: {len(urls)}")
    audit=[]
    for i,url in enumerate(urls,1):
        item={"url":url,"name":Path(urlsplit(url).path).name,"status":"missing","bytes":0}
        try:
            data=fetch(url,8_000_000)
            if len(data)<50 or not MAGIC.search(data[:16]):raise ValueError("Unrecognized LZH signature")
            (OUT/item["name"]).write_bytes(data)
            item.update(status="ok",bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        except HTTPError as exc:
            item.update(status=f"http_{exc.code}",error=str(exc)[:120])
            if exc.code in (403,429,503):
                audit.append(item);break
        except (URLError,TimeoutError,ValueError) as exc:
            item.update(status="failed",error=str(exc)[:120])
        audit.append(item)
        if i%10==0:print(f"PERIOD_PROGRESS {i}/{len(urls)} acquired={sum(x['status']=='ok' for x in audit)}",flush=True)
        time.sleep(DELAY)
    summary={"created":datetime.now(timezone.utc).isoformat(),"source":PAGE,"planned":len(urls),
             "attempted":len(audit),"acquired":sum(x["status"]=="ok" for x in audit),
             "bytes":sum(x["bytes"] for x in audit),
             "source_copyright":"Private research artifact only, not licensed for public redistribution",
             "files":audit}
    (OUT/"audit.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("PERIOD_FINAL "+json.dumps({k:v for k,v in summary.items() if k!="files"},ensure_ascii=False),flush=True)

if __name__=="__main__": main()
