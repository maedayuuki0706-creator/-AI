"""Read-only X receipts/volume audit. No X POST, Discord POST or state repair."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import urllib.request

import fusion_shadow as core
from x_delivery_v2 import dispatcher
from x_delivery_v2.store import Store, key

API = "https://api.github.com/repos/maedayuuki0706-creator/-AI"


def read(path):
    headers = {"Accept":"application/vnd.github+json","User-Agent":"boat-ai-read-only-recovery-audit"}
    token = os.getenv("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = "Bearer "+token
    req = urllib.request.Request(API+"/contents/"+path+"?ref=x-delivery-state",headers=headers,method="GET")
    with urllib.request.urlopen(req,timeout=20) as response:
        value=json.load(response)
    return base64.b64decode(value["content"]).decode()


class Snapshot(Store):
    def __init__(self, days):
        self.states, self.archives = {}, {}
        for day in days:
            self.states[day] = json.loads(read(f"data/x_post_delivery/{day}.json"))
            self.archives[day] = {}
            for line in read(f"data/x_post_delivery/{day}_posts.jsonl").splitlines():
                if line.strip():
                    row=json.loads(line)
                    self.archives[day].setdefault(key(row),row)
    def state(self, day):
        return self.states[day]
    def archive(self, day):
        return self.archives[day]
    def update(self,*args,**kwargs):
        raise AssertionError("Read-only audit must not change a claim or receipt")
    def publish(self,*args,**kwargs):
        raise AssertionError("Read-only audit must not create a prediction")
    def report(self,day,value):
        pass


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",required=True)
    args=parser.parse_args()
    now=datetime.now(core.JST)
    days=[now.strftime('%Y%m%d'),(now-timedelta(days=1)).strftime('%Y%m%d')]
    store=Snapshot(days)
    def forbidden(*args,**kwargs):
        raise AssertionError("This audit cannot send any production post")
    report=dispatcher.run_once(store=store,clock=lambda:now,mode='predictions',candidates=[],
                               transport=forbidden,ready=forbidden)
    report.update(read_only=True,production_x_dispatcher_unchanged=True,
                  production_quarantine_still_held=True,zero_post_requests=True)
    root=Path(args.out)
    core.write_report(root/'x_recovery_audit.json',report)
    core.write_once(root/'x_audits'/days[0]/f"{now.strftime('%H%M%S')}_{os.getenv('GITHUB_RUN_ID','local')}.json",report)
    return 0 if report['status'] in ('checked','checked_with_quarantine') else 1


if __name__=='__main__':
    raise SystemExit(main())
