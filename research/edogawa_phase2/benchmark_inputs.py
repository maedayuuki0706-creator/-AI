"""Read-only import of already frozen research inputs; never writes source branch."""
import argparse,json,urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from research.scenario_v2 import engine as scenario
from .acquire import put,digest

def main():
    p=argparse.ArgumentParser();p.add_argument('--ref',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    if len(a.ref)!=40:raise ValueError('Pin exact source state SHA')
    jobs=[(day,r) for day,rs in [('20261017',range(7,13)),('20261018',range(1,13))] for r in rs]
    def one(job):
        day,r=job;key=f'{day}_03_{r:02}';found={};errors=[]
        for folder in ['inputs','forecasts','reviews','receipts']:
            path=f'data/venue_specialists_v1/{folder}/{day}/{key}.json'
            url=f'https://raw.githubusercontent.com/maedayuuki0706-creator/-AI/{a.ref}/{path}'
            try:
                with urllib.request.urlopen(url,timeout=15) as response:body=response.read(2000001)
                found[folder]=json.loads(body)
            except Exception as e: errors.append({'folder':folder,'error':str(e)[:150]})
        if 'inputs' in found and 'forecasts' in found:
            if scenario.digest(found['inputs'])!=found['forecasts']['snapshot_digest']:raise ValueError('Frozen input digest mismatch')
            scenario.verify(found['forecasts'])
            full=found['inputs'];found['input_original_digest']=scenario.digest(full)
            found['inputs']={k:v for k,v in full.items() if k!='official_originals'}
            # Original envelope hashes remain in the baseline record/reference.
            found['forecasts']={k:found['forecasts'][k] for k in ['race_id','digest','snapshot_digest','virtual_card','created_at','deadline_at','version']}
        found.update(race_id=key,source_state_sha=a.ref,errors=errors)
        return found
    with ThreadPoolExecutor(max_workers=2) as ex:records=list(ex.map(one,jobs))
    body=json.dumps(records,ensure_ascii=False,sort_keys=True,indent=2).encode();path=Path(a.out)/(digest(body)+'.json');put(path,body)
    print(json.dumps({'path':str(path),'races':len(records),'complete_pairs':sum(all(k in r for k in ['inputs','forecasts','reviews','receipts']) for r in records)}),flush=True)

if __name__=='__main__':main()
