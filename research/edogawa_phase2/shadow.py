"""Passive-input, one-race A/B capture with a fixed independent Git destination.

Never calls official scraping or delivery. Existing specialist input is read-only.
Result processing is a separate command and never rewrites originals. Preflight
is the default; no daemon/schedule is enabled by this module.
"""
import argparse,json,subprocess,time
from datetime import datetime
from pathlib import Path
from research.scenario_v2 import engine as scenario
from . import model
from .acquire import put

BRANCH='research-edogawa-phase2-state'
PREFIX='data/edogawa_phase2_shadow'
def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args],text=True,stderr=subprocess.PIPE,timeout=25).strip()
def immutable(path,obj):
    put(Path(path),(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode())
def persist(state):
    state=Path(state)
    # Refuse any pre-existing staged changes and any write outside the research prefix.
    staged=git(state,'diff','--cached','--name-only')
    if staged:raise ValueError('Unexpected staged changes')
    changed=git(state,'status','--porcelain','--untracked-files=all').splitlines()
    if any(line[:2]!='??' or not line[3:].startswith(PREFIX+'/') for line in changed):
        raise ValueError('Only new independent research files may be pushed')
    if changed:
        git(state,'add','--',PREFIX);git(state,'commit','-m','research: append immutable Edogawa Phase 2 records')
    for attempt in range(3):
        try:
            git(state,'push','origin','HEAD:refs/heads/'+BRANCH)
            sha=git(state,'rev-parse','HEAD')
            remote=git(state,'ls-remote','origin','refs/heads/'+BRANCH).split()[0]
            if sha!=remote:raise ValueError('Remote head moved; receipt not confirmed')
            git(state,'fetch','--depth=1','origin','refs/heads/'+BRANCH)
            if git(state,'rev-parse','FETCH_HEAD')!=sha:raise ValueError('Fetched remote mismatch')
            return sha
        except subprocess.CalledProcessError:
            if attempt==2:raise
            # Do not merge conflicting originals, force push, or change another branch.
            time.sleep(.5*(attempt+1))
    raise RuntimeError('Persistence not verified')

def capture(snapshot,fitted,root,*,clock=None,code_sha=None):
    clock=clock or (lambda:datetime.now(scenario.JST));now=clock().isoformat()
    if not code_sha or len(code_sha)!=40:raise ValueError('Full code commit identity required')
    _,meta,_=scenario.validate(snapshot,'live',now)
    if any(b.get('exhibition_time') is None for b in snapshot['boats']):raise ValueError('All six exhibition times required')
    if str(meta['jcd']).zfill(2)!='03':raise ValueError('Edogawa only')
    base=Path(root)/PREFIX;key=meta['race_id'];day=meta['day']
    # One bundle is an atomic unit: A and B share precisely the same snapshot.
    path=base/'forecasts'/day/(key+'.json')
    if path.exists():
        old=json.loads(path.read_text());scenario.verify(old)
        if old['input_digest']!=scenario.digest(snapshot):raise ValueError('Duplicate race source changed')
        return old
    variants=[model.predict(snapshot,fitted,v,mode='live',now=now,code_sha=code_sha) for v in ['A','B']]
    if (scenario.aware(meta['deadline_at'])-clock()).total_seconds()<180:raise ValueError('Late generation; no forecast saved')
    bundle={'race_id':key,'meta':meta,'input_digest':scenario.digest(snapshot),'input':snapshot,
        'generated_at':now,'local_saved_at':clock().isoformat(),'code_sha':code_sha,
        'model_digest':fitted['digest'],'status':'prospective_uncheckpointed','variants':variants,
        'baseline_original':snapshot.get('source',{}).get('phase2_baseline_reference')}
    # Recheck after serialization-relevant work before exclusive creation.
    if clock()>=scenario.aware(meta['deadline_at']):raise ValueError('Late save prohibited')
    bundle['digest']=scenario.digest(bundle);immutable(path,bundle);return bundle

def receipt(state,bundle,sha,*,clock=None):
    clock=clock or (lambda:datetime.now(scenario.JST));scenario.verify(bundle)
    if len(sha)!=40:raise ValueError('Full remote commit identity required')
    key=bundle['race_id'];day=bundle['meta']['day'];path=f'{PREFIX}/forecasts/{day}/{key}.json'
    # Read the just-fetched remote commit, not a local working-tree receipt claim.
    if git(state,'rev-parse','FETCH_HEAD')!=sha:raise ValueError('Remote not fetched')
    remote=json.loads(git(state,'show',sha+':'+path))
    if remote!=bundle:raise ValueError('Remote original mismatch')
    checked=clock().isoformat();before=scenario.aware(bundle['generated_at'])<=scenario.aware(checked)<scenario.aware(bundle['meta']['deadline_at'])
    r={'race_id':key,'forecast_digest':bundle['digest'],'commit_sha':sha,'checked_at':checked,
       'status':'confirmed_before_deadline' if before else 'late_receipt_excluded'}
    immutable(Path(state)/PREFIX/'receipts'/day/(key+'.json'),r);return r

def preflight(state,fitted):
    model.check_model(fitted)
    return {'status':'preflight_only_live_not_verified','training_n':fitted['training_n'],
        'destination_branch':BRANCH,'prefix':PREFIX,'predictions_generated':0,'state_writes':0,
        'schedule_enabled':False,'phase1_status':'未完了・新ゆうき/浜名湖/7日95%の追跡継続'}

def review_bundle(bundle,result,root,*,confirmed_receipt=None):
    scenario.verify(bundle)
    if not confirmed_receipt or confirmed_receipt.get('forecast_digest')!=bundle['digest'] or confirmed_receipt.get('status')!='confirmed_before_deadline':
        raise ValueError('Verified receipt required for prospective grading')
    if len(confirmed_receipt.get('commit_sha',''))!=40 or not scenario.aware(bundle['generated_at'])<=scenario.aware(confirmed_receipt['checked_at'])<scenario.aware(bundle['meta']['deadline_at']):
        raise ValueError('Invalid receipt time or remote identity')
    key=bundle['race_id'];day=bundle['meta']['day']
    immutable(Path(root)/PREFIX/'results'/day/(key+'.json'),result)
    reviews=[model.evaluate(r,result) for r in bundle['variants']]
    r={'race_id':key,'forecast_digest':bundle['digest'],'reviews':reviews,'user_comment':'','phase1_completed':False}
    r['digest']=scenario.digest(r);immutable(Path(root)/PREFIX/'reviews'/day/(key+'.json'),r);return r

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--state',required=True);p.add_argument('--input');p.add_argument('--result');p.add_argument('--forecast');p.add_argument('--receipt');p.add_argument('--mode',choices=['preflight','capture','resume','review'],default='preflight');p.add_argument('--publish',action='store_true');a=p.parse_args()
    fitted=json.loads(Path(a.model).read_text());root=Path(a.state)
    if a.mode=='preflight': print(json.dumps(preflight(root,fitted),ensure_ascii=False));return
    try:
        if a.mode=='capture':
            if not a.input:raise ValueError('Frozen pre-race input required')
            snapshot=json.loads(Path(a.input).read_text());bundle=capture(snapshot,fitted,root,code_sha=git(Path(__file__).resolve().parents[2],'rev-parse','HEAD'))
            if a.publish:
                sha=persist(root);r=receipt(root,bundle,sha);persist(root);print(json.dumps(r))
            else:print(json.dumps({'status':'local_only_not_remote_success','race_id':bundle['race_id']}))
        elif a.mode=='resume':
            bundle=json.loads(Path(a.forecast).read_text());scenario.verify(bundle)
            if not a.publish:raise ValueError('Resume requires explicit publish')
            sha=persist(root);r=receipt(root,bundle,sha);persist(root);print(json.dumps(r))
        else:
            obj=review_bundle(json.loads(Path(a.forecast).read_text()),json.loads(Path(a.result).read_text()),root,confirmed_receipt=json.loads(Path(a.receipt).read_text()))
            if a.publish:persist(root)
            print(json.dumps({'race_id':obj['race_id'],'status':'review_saved'}))
    except Exception as e:
        stamp=datetime.now(scenario.JST).strftime('%Y%m%d/%H%M%S_%f')
        immutable(root/PREFIX/'failures'/(stamp+'.json'),{'error':str(e),'status':'failure_not_success','observed_at':datetime.now(scenario.JST).isoformat()})
        raise

if __name__=='__main__':main()
