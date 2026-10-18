"""Import only existing frozen inputs; keep original forecast identities intact."""
import argparse,json,urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from research.edogawa_phase2.acquire import put,digest
from research.scenario_v2 import engine as scenario

def run(ref,reuse,out):
    if len(ref)!=40:raise ValueError('Pinned source SHA required')
    root=Path(out);old=json.loads(Path(reuse).read_text());records=list(old)
    jobs=[('20261017','16',r) for r in range(6,13)]+[('20261018',j,r) for j in ['16','23'] for r in range(1,13)]
    def one(job):
        day,j,r=job;key=f'{day}_{j}_{r:02}';cache=root/'pairs'/(key+'.json')
        if cache.exists():return json.loads(cache.read_text())
        found={};errors=[]
        for folder in ['inputs','forecasts','reviews','receipts']:
            url=f'https://raw.githubusercontent.com/maedayuuki0706-creator/-AI/{ref}/data/venue_specialists_v1/{folder}/{day}/{key}.json'
            try:
                with urllib.request.urlopen(url,timeout=15) as response:body=response.read(2000001)
                found[folder]=json.loads(body)
            except Exception as e:errors.append({'folder':folder,'error':str(e)[:180]})
        if 'inputs' in found and 'forecasts' in found:
            full=found['inputs'];base=found['forecasts'];scenario.verify(base)
            if scenario.digest(full)!=base['snapshot_digest']:raise ValueError('Frozen source digest mismatch')
            found['input_original_digest']=scenario.digest(full)
            found['inputs']={k:v for k,v in full.items() if k!='official_originals'}
            found['forecasts']={k:base[k] for k in ['race_id','digest','snapshot_digest','virtual_card','created_at','deadline_at','version']}
        found.update(race_id=key,source_state_sha=ref,errors=errors)
        put(cache,json.dumps(found,sort_keys=True,ensure_ascii=False).encode());return found
    with ThreadPoolExecutor(max_workers=2) as pool:
        for i,r in enumerate(pool.map(one,jobs),1):
            records.append(r)
            if i%5==0:print('Frozen pairs',i,'/',len(jobs),flush=True)
    body=json.dumps(records,ensure_ascii=False,sort_keys=True).encode();path=root/(digest(body)+'.json');put(path,body)
    print(json.dumps({'path':str(path),'pairs':len(records),'errors':sum(bool(r['errors']) for r in records)}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--ref',required=True);p.add_argument('--reuse',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.ref,a.reuse,a.out)
