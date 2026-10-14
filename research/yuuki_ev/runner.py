"""Read-only public source collection; no production module or job is called.

prepare produces connector-ready batches; apply is optional for a separately
provisioned service account, limited by code to the one research spreadsheet.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import time
import urllib.request
from . import core

REPOSITORY = 'maedayuuki0706-creator/-AI'
TARGET = '1gXM8oPdzAOZkkNFly4B6jXwezV4eFSw7f7St6s49EdY'
BRANCH = 'research/yuuki-ev-independent-20261014'

def get(url):
    # Deliberately GET-only, no GitHub token, no production endpoints.
    request=urllib.request.Request(url,headers={'User-Agent':'Yuuki-EV-Independent-Research/1.0'})
    with urllib.request.urlopen(request,timeout=15) as r:return r.read().decode('utf-8')

def official_url(kind,source):
    return 'https://www.boatrace.jp/owpc/pc/race/'+kind+'?hd='+source['day']+'&jcd='+source['jcd']+'&rno='+str(source['rno'])

def textify(raw):
    import html
    return re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]+>',' ',raw))).strip()

def parse_result(raw):
    bodies=re.findall(r'<tbody\b[^>]*>(.*?)</tbody>',raw,re.S|re.I)
    market=next((x for x in bodies if re.search(r'<td\b[^>]*>\s*3連単\s*</td>',x,re.S)), '')
    pay={}
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>',market,re.S|re.I):
        match=re.search(r'([1-6])\s*[-－]\s*([1-6])\s*[-－]\s*([1-6])\s+[¥￥]\s*([\d,]+)',textify(row))
        if match:
            c='-'.join(match.group(i) for i in (1,2,3))
            if len(set(c.split('-')))==3:pay[c]=int(match[4].replace(',',''))
    refunds=set()
    for table in re.findall(r'<table\b[^>]*>(.*?)</table>',raw,re.S|re.I):
        if re.search(r'<th\b[^>]*>\s*返還\s*</th>',table):
            refunds.update(int(x) for x in re.findall(r'numberSet1_number[^>]*>\s*([1-6])\s*</span>',table))
    t=textify(market)
    void=bool(re.search(r'不成立|全返還|中止',t) or re.search(r'レースは中止',textify(raw)))
    special=re.search(r'特払い\s*[¥￥]\s*([\d,]+)',t)
    status='void' if void else 'special' if special else 'settled' if pay else 'pending'
    if '返還艇あり' in textify(raw) and not refunds:status='pending'
    return {'status':status,'payouts':pay,'refund_lanes':sorted(refunds),
            'special_per_100':int(special[1].replace(',','')) if special else None}

def collect_source(source, sha, observed_at, out, *, replay=False, official=None):
    folder=Path(out); source_key=source['key']
    snapshots=core.build_snapshots(source,sha,observed_at,replay=replay)
    written=[];duplicates=0
    for record in snapshots:
        p=folder/'predictions'/source['day']/(record['id'].replace(':','_')+'.json')
        if core.write_once(p,record):written.append(record)
        else:
            duplicates+=1
            record=json.loads(p.read_text())
        if official:
            evaluated=core.evaluate(record,official,observed_at)
            if evaluated:core.write_once(folder/'results'/source['day']/(record['id'].replace(':','_')+'.json'),evaluated)
    return {'new_records':len(written),'duplicates':duplicates}

def read_records(root,kind):
    return [json.loads(p.read_text()) for p in sorted((Path(root)/kind).glob('**/*.json'))]

def prepare(root,out):
    from .sheets import payloads
    records=read_records(root,'predictions');results=read_records(root,'results');receipts=read_records(root,'receipts')
    batches=payloads(records,results,receipts)
    output=Path(out);output.mkdir(parents=True,exist_ok=True)
    for i,requests in enumerate(batches):
        (output/f'batch-{i:03}.json').write_text(core.dumps({'spreadsheet_id':TARGET,'requests':requests}))
    report={'records':len(records),'races':len(set(x['race_key'] for x in records)),
            'settled_records':len(results),'eligible_live_receipts':sum(x['eligible_live'] for x in receipts),
            'available_by_model':{m:sum(x['model']==m and x['availability']=='記録可' for x in records) for m in core.MODELS.values()},
            'cohorts':sorted(set(x['cohort'] for x in records)), 'batches':len(batches)}
    (output/'summary.json').write_text(core.dumps(report));print(core.dumps(report))

def apply_with_existing_account(payload):
    # Optional only. Never move credentials through artifacts or logs.
    import os
    from google.oauth2.service_account import Credentials
    from google.auth.transport.requests import AuthorizedSession
    if payload.get('spreadsheet_id')!=TARGET:raise ValueError('research destination allowlist')
    account=json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON'])
    client=AuthorizedSession(Credentials.from_service_account_info(account,scopes=['https://www.googleapis.com/auth/spreadsheets']))
    response=client.post('https://sheets.googleapis.com/v4/spreadsheets/'+TARGET+':batchUpdate',json={'requests':payload['requests']},timeout=30)
    if not response.ok:raise RuntimeError('research Sheets write failed: HTTP '+str(response.status_code))
    return True

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',default='data/research_yuuki_ev');ap.add_argument('--source-dir');ap.add_argument('--key',action='append');ap.add_argument('--sha');ap.add_argument('--replay',action='store_true');ap.add_argument('--prepare');ap.add_argument('--apply-batch')
    args=ap.parse_args()
    if args.apply_batch:
        apply_with_existing_account(json.loads(Path(args.apply_batch).read_text()));return
    if args.source_dir:
        now=datetime.now(core.JST).isoformat()
        for key in args.key or []:
            root=Path(args.source_dir)
            pt2=root/'data/prototype12_delivery/predictions'/(key+'.json')
            fallback=root/'data/prototype3_delivery/predictions'/(key+'.json')
            source=json.loads((pt2 if pt2.exists() else fallback).read_text())
            official_path=root/'data/prototype_scoreboard'/source['day']/'official'/(key+'.json')
            official=json.loads(official_path.read_text()) if official_path.exists() else None
            print(core.dumps({'race':key,**collect_source(source,args.sha,now,args.root,replay=args.replay,official=official)}))
    if args.prepare:prepare(args.root,args.prepare)

if __name__=='__main__':main()
