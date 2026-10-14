"""Bounded hourly collection using public GETs and separate research state.

This module prepares updates. Connector writes and their actual success
receipts are performed by the scheduled task; it does not claim a local file
write is a Google Sheets persistence receipt.
"""
from datetime import datetime, timedelta
from pathlib import Path
import argparse
import json
from . import core
from .runner import REPOSITORY, collect_source, get, official_url, parse_result, read_records, prepare

def discover(now):
    base='https://api.github.com/repos/'+REPOSITORY
    branch=json.loads(get(base+'/branches/main'))
    sha=branch['commit']['sha']
    tree=json.loads(get(base+'/git/trees/'+sha+'?recursive=1'))
    if tree.get('truncated'):raise RuntimeError('source tree truncated: coverage not proven')
    today=now.strftime('%Y%m%d')
    paths=[x['path'] for x in tree['tree'] if x.get('type')=='blob' and x['path'].startswith('data/prototype12_delivery/predictions/'+today+'_') and x['path'].endswith('.json')]
    return sha,paths

def raw(sha,path):
    return json.loads(get('https://raw.githubusercontent.com/'+REPOSITORY+'/'+sha+'/'+path))

def run(root,output,limit=6):
    now=datetime.now(core.JST);root=Path(root);root.mkdir(parents=True,exist_ok=True)
    sha,paths=discover(now)
    existing=read_records(root,'predictions')
    known={f['race_key'] for f in existing}
    # Public files are metadata-discovered. No whole past history download.
    candidates=[p for p in paths if Path(p).stem not in known]
    inputs=[];errors=[]
    for path in candidates[-24:]:
        try:
            source=raw(sha,path)
            close=core.deadline(source)
            inputs.append((0 if close and close>now else 1,close.isoformat() if close else '',source))
        except Exception as exc:errors.append({'path':path,'status':'source_get_failed','error_type':type(exc).__name__})
    for _,_,source in sorted(inputs,key=lambda x:(x[0],x[1]))[:limit]:
        collect_source(source,sha,datetime.now(core.JST).isoformat(),root)
    # Evaluate existing fixed forecasts separately. Current-race actual ST is
    # never passed into the prediction function.
    existing=read_records(root,'predictions');result_ids={r['id'] for r in read_records(root,'results')}
    pending={f['race_key']:f for f in existing if f['id'] not in result_ids and core.aware(f['deadline']) and core.aware(f['deadline'])+timedelta(minutes=5)<now}
    for key,f in list(pending.items())[:12]:
        try:
            official=raw(sha,'data/prototype_scoreboard/'+f['day']+'/official/'+key+'.json')
        except Exception:
            try:
                url=official_url('raceresult',f)
                official=parse_result(get(url));official['source_url']=url
                official['checked_at']=datetime.now(core.JST).isoformat()
            except Exception as exc:
                errors.append({'race_key':key,'status':'official_get_failed','error_type':type(exc).__name__});continue
        for forecast in (x for x in existing if x['race_key']==key):
            if forecast['id'] in result_ids:continue
            result=core.evaluate(forecast,official,datetime.now(core.JST).isoformat())
            if result:
                core.write_once(root/'results'/f['day']/(forecast['id'].replace(':','_')+'.json'),result)
            else:errors.append({'race_key':key,'status':'official_pending'})
    event={'observed_at':datetime.now(core.JST).isoformat(),'source_sha':sha,'today_source_races':len(paths),
           'new_candidate_races':len(candidates),'processed_limit':limit,'errors':errors,
           'coverage_note':'最高頻度1時間・今回上限6レース。全レースの締切前捕捉を保証しない。'}
    core.write_once(root/'coverage'/(now.strftime('%Y%m%dT%H%M%S')+'.json'),event)
    prepare(root,output)
    (Path(output)/'collection.json').write_text(core.dumps(event))
    return event

def acknowledge(root,ids,persisted_at):
    known={f['id']:f for f in read_records(root,'predictions')}
    for ident in ids:
        f=known[ident];receipt=core.seal_live(f,persisted_at)
        core.write_once(Path(root)/'receipts'/f['day']/(ident.replace(':','_')+'.json'),receipt)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',default='data/research_yuuki_ev');parser.add_argument('--output',required=True);parser.add_argument('--limit',type=int,default=6)
    args=parser.parse_args();print(core.dumps(run(args.root,args.output,min(max(args.limit,1),6))))

if __name__=='__main__':main()
