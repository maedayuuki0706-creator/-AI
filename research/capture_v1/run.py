"""Manual independent collector; no scheduled job or deployment is installed."""
import argparse
import json
from pathlib import Path
import time
from .collector import Collector


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest",required=True,help="JSON list of day/jcd/rno/deadline")
    p.add_argument("--out",required=True,help="Independent directory outside the repository")
    p.add_argument("--db-root")
    p.add_argument("--fusion-root")
    p.add_argument("--shared-cache")
    p.add_argument("--fetch-foot",action="store_true")
    p.add_argument("--watch",action="store_true")
    p.add_argument("--cycles",type=int,default=0,help="0 watches until interrupted")
    a=p.parse_args()
    c=Collector(a.out,db_root=a.db_root,fusion_root=a.fusion_root,shared_cache=a.shared_cache,fetch_foot=a.fetch_foot)
    cycle=0
    while True:
        manifest=json.loads(Path(a.manifest).read_text())
        if not isinstance(manifest,list):p.error("Manifest must be a list")
        statuses=[]
        for meta in sorted(manifest,key=lambda r:r["deadline"]):
            try:statuses.append(c.step(meta))
            except Exception as exc:statuses.append({"phase":"error","error_type":type(exc).__name__,"reason":str(exc)})
        print(json.dumps({"cycle":cycle,"races":statuses},ensure_ascii=False),flush=True)
        cycle+=1
        if not a.watch or a.cycles and cycle>=a.cycles:break
        time.sleep(30)


if __name__=="__main__":main()
