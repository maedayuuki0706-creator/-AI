"""Consume an existing pre-race archive once, with no additional official GETs."""
import argparse,json
from pathlib import Path
from datetime import datetime
from research.scenario_v2 import engine as scenario
from . import shadow

def load_verified(source,key,now):
    day=key.split('_')[0];base=Path(source)/'data/venue_specialists_v1'
    read=lambda folder:json.loads((base/folder/day/(key+'.json')).read_text())
    snap,old,receipt=read('inputs'),read('forecasts'),read('receipts')
    scenario.verify(old)
    if old['race_id']!=key or scenario.digest(snap)!=old['snapshot_digest']:raise ValueError('Baseline input identity mismatch')
    if receipt.get('status')!='confirmed_before_deadline' or receipt.get('digest')!=old['digest']:raise ValueError('Baseline not checkpointed')
    if not scenario.aware(old['created_at'])<=scenario.aware(receipt['checked_at'])<scenario.aware(old['deadline_at']):raise ValueError('Invalid baseline receipt')
    if scenario.aware(receipt['checked_at'])>now:raise ValueError('Future receipt')
    ref={'race_id':key,'forecast_digest':old['digest'],'input_digest':old['snapshot_digest'],
         'receipt_commit_sha':receipt['commit_sha'],'source_state_sha':shadow.git(source,'rev-parse','HEAD')}
    # Keep same six-boat information; original envelope remains referenced by digest.
    snap.pop('official_originals',None)
    snap.setdefault('source',{})['phase2_baseline_reference']=ref
    return snap

def main():
    p=argparse.ArgumentParser();p.add_argument('--source-state',required=True);p.add_argument('--state',required=True);p.add_argument('--model',required=True);p.add_argument('--rno',type=int,default=1);p.add_argument('--mode',choices=['preflight','capture'],default='preflight');a=p.parse_args()
    fitted=json.loads(Path(a.model).read_text())
    if a.mode=='preflight':print(json.dumps(shadow.preflight(a.state,fitted),ensure_ascii=False));return
    if a.rno not in range(1,13):raise ValueError('Invalid race number')
    now=datetime.now(scenario.JST);key=f'{now:%Y%m%d}_03_{a.rno:02}'
    try:
        snap=load_verified(a.source_state,key,now)
        bundle=shadow.capture(snap,fitted,a.state,code_sha=shadow.git(Path(__file__).resolve().parents[2],'rev-parse','HEAD'))
        sha=shadow.persist(a.state);receipt=shadow.receipt(a.state,bundle,sha);shadow.persist(a.state)
        print(json.dumps(receipt,ensure_ascii=False))
    except Exception as e:
        stamp=now.strftime('%Y%m%d/%H%M%S_%f')
        shadow.immutable(Path(a.state)/shadow.PREFIX/'failures'/(stamp+'.json'),{'race_id':key,'status':'missing_or_failed_not_success','reason':str(e),'observed_at':now.isoformat()})
        # Best-effort independent error persistence; never touch baseline branch.
        try:shadow.persist(a.state)
        except Exception:pass
        raise

if __name__=='__main__':main()
