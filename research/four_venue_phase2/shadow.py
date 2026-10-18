"""Independent append-only forward store. Existing inputs are consumed read-only.

One process/race at a time. No scraper, notifier, daemon or production imports.
Only a verified remote read-back before deadline counts as prospective success.
"""
import argparse,fcntl,json,subprocess,time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from research.scenario_v2 import engine as scenario
from research.edogawa_phase2.shadow import git,immutable
from research.edogawa_phase2.feed import load_verified
from . import model
from .collect import VENUES

BRANCH='research-four-venue-phase2-state'
PREFIX='data/four_venue_phase2_shadow'

@contextmanager
def locked(state):
    gitdir=Path(git(state,'rev-parse','--absolute-git-dir'))
    with (gitdir/'four-venue-phase2.lock').open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:fcntl.flock(f,fcntl.LOCK_UN)

def persist(state):
    if git(state,'branch','--show-current')!=BRANCH:raise ValueError('Dedicated state checkout required')
    if git(state,'diff','--cached','--name-only'):raise ValueError('Unexpected staged files')
    changed=git(state,'status','--porcelain','--untracked-files=all').splitlines()
    if any(x[:2]!='??' or not x[3:].startswith(PREFIX+'/') for x in changed):raise ValueError('Only new independent research logs allowed')
    if changed:
        git(state,'add','--',PREFIX);git(state,'commit','-m','research: append four-venue Phase 2 originals/reviews')
    for attempt in range(3):
        try:
            git(state,'push','origin','HEAD:refs/heads/'+BRANCH)
            sha=git(state,'rev-parse','HEAD')
            remote=git(state,'ls-remote','origin','refs/heads/'+BRANCH).split()[0]
            if remote!=sha:raise ValueError('Concurrent remote head; stop without merging originals')
            git(state,'fetch','--depth=1','origin','refs/heads/'+BRANCH)
            if git(state,'rev-parse','FETCH_HEAD')!=sha:raise ValueError('Remote confirmation mismatch')
            return sha
        except subprocess.CalledProcessError:
            if attempt==2:raise
            time.sleep(.5*(attempt+1))

def capture(snapshot,fitted,state,*,clock=None,code_sha=None):
    clock=clock or (lambda:datetime.now(scenario.JST));now=clock().isoformat()
    if not code_sha or len(code_sha)!=40:raise ValueError('Full code commit required')
    _,meta,_=scenario.validate(snapshot,'live',now)
    if str(meta['jcd']).zfill(2)!=fitted['venue_code']:raise ValueError('Wrong venue model')
    if any(b.get('exhibition_time') is None for b in snapshot['boats']):raise ValueError('Missing exhibition: no forecast')
    path=Path(state)/PREFIX/'forecasts'/meta['day']/(meta['race_id']+'.json')
    if path.exists():
        old=json.loads(path.read_text());scenario.verify(old)
        if old['input_digest']!=scenario.digest(snapshot):raise ValueError('Conflicting duplicate race')
        return old
    variants=[model.predict(snapshot,fitted,v,mode='live',now=now,code_sha=code_sha) for v in ['A','B']]
    saved=clock()
    if (scenario.aware(meta['deadline_at'])-saved).total_seconds()<180:raise ValueError('Insufficient save margin')
    bundle={'race_id':meta['race_id'],'meta':meta,'generated_at':now,'local_saved_at':saved.isoformat(),
            'input_digest':scenario.digest(snapshot),'input':snapshot,'code_sha':code_sha,
            'model_digest':fitted['digest'],'variants':variants,'status':'prospective_uncheckpointed',
            'baseline_original':snapshot.get('source',{}).get('phase2_baseline_reference')}
    bundle['digest']=scenario.digest(bundle)
    if clock()>=scenario.aware(meta['deadline_at']):raise ValueError('Deadline crossed during serialization')
    immutable(path,bundle);return bundle

def receipt(state,bundle,sha,*,clock=None):
    scenario.verify(bundle);clock=clock or (lambda:datetime.now(scenario.JST))
    if len(sha)!=40 or git(state,'rev-parse','FETCH_HEAD')!=sha:raise ValueError('Unverified remote commit')
    path=f"{PREFIX}/forecasts/{bundle['meta']['day']}/{bundle['race_id']}.json"
    if json.loads(git(state,'show',sha+':'+path))!=bundle:raise ValueError('Remote bytes mismatch')
    now=clock().isoformat();before=scenario.aware(bundle['generated_at'])<=scenario.aware(now)<scenario.aware(bundle['meta']['deadline_at'])
    r={'race_id':bundle['race_id'],'forecast_digest':bundle['digest'],'commit_sha':sha,'checked_at':now,
       'status':'confirmed_before_deadline' if before else 'late_receipt_excluded'}
    dest=Path(state)/PREFIX/'receipts'/bundle['meta']['day']/(bundle['race_id']+'.json')
    if dest.exists():
        old=json.loads(dest.read_text())
        if old['forecast_digest']!=bundle['digest']:raise ValueError('Receipt identity conflict')
        return old
    immutable(dest,r);return r

def review_bundle(state,bundle,result,confirmed_receipt):
    scenario.verify(bundle);r=confirmed_receipt
    if r.get('status')!='confirmed_before_deadline' or r.get('forecast_digest')!=bundle['digest'] or len(r.get('commit_sha',''))!=40:raise ValueError('Prospective receipt required')
    if not scenario.aware(bundle['generated_at'])<=scenario.aware(r['checked_at'])<scenario.aware(bundle['meta']['deadline_at']):raise ValueError('Late receipt')
    if result.get('race_id')!=bundle['race_id'] or scenario.aware(result['observed_at'])<scenario.aware(bundle['meta']['deadline_at']):raise ValueError('Wrong/early result')
    base=Path(state)/PREFIX;day=bundle['meta']['day'];key=bundle['race_id']+'.json'
    immutable(base/'results'/day/key,result)
    normal=result.get('normal_verified') is True and result.get('refund_lanes')==[]
    multi=len(result.get('official_trifectas',[]))>1
    if result.get('trifecta') in scenario.COMBINATIONS and not multi:
        reviews=[model.evaluate(p,result) for p in bundle['variants']]
    else:reviews=[{'variant':p['variant'],'hit':None,'roi':None,'attack_origin_correct':None,'reason':'同着複数出目・不成立・結果不足等。専用集計待ちとして通常成績から分離'} for p in bundle['variants']]
    out={'race_id':bundle['race_id'],'forecast_digest':bundle['digest'],'cohort':'同着複数出目' if multi else '通常確認済' if normal else '事故返還/成立未確認',
         'reviews':reviews,'user_comment':'','video_source_url':'','reviewed_at':None,'phase1_complete':False}
    out['digest']=scenario.digest(out);immutable(base/'reviews'/day/key,out);return out

def preflight(fitted):
    model.check_model(fitted)
    return {'status':'preflight_only','venue':fitted['venue'],'training_n':fitted['training_n'],
            'branch':BRANCH,'prefix':PREFIX,'generated':0,'writes':0,'schedule_enabled':False,'prospective_verified':0,'phase1_complete':False}

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--state',required=True);p.add_argument('--source-state');p.add_argument('--rno',type=int);p.add_argument('--forecast');p.add_argument('--result');p.add_argument('--receipt');p.add_argument('--publish',action='store_true');p.add_argument('--mode',choices=['preflight','capture','resume','review'],default='preflight');a=p.parse_args()
    fitted=json.loads(Path(a.model).read_text())
    if a.mode=='preflight':print(json.dumps(preflight(fitted),ensure_ascii=False));return
    if git(a.state,'branch','--show-current')!=BRANCH:raise ValueError('Wrong state branch; no files written')
    with locked(a.state):
        try:
            if a.mode=='capture':
                if a.rno not in range(1,13):raise ValueError('Race number required')
                now=datetime.now(scenario.JST);key=f"{now:%Y%m%d}_{fitted['venue_code']}_{a.rno:02}"
                snap=load_verified(a.source_state,key,now)
                bundle=capture(snap,fitted,a.state,code_sha=git(Path(__file__).resolve().parents[2],'rev-parse','HEAD'))
            elif a.mode=='resume':
                bundle=json.loads(Path(a.forecast).read_text());scenario.verify(bundle)
            else:
                review_bundle(a.state,json.loads(Path(a.forecast).read_text()),json.loads(Path(a.result).read_text()),json.loads(Path(a.receipt).read_text()))
                if a.publish:persist(a.state)
                return
            if a.publish:
                sha=persist(a.state);r=receipt(a.state,bundle,sha);persist(a.state);print(json.dumps(r))
            else:print(json.dumps({'status':'local_only_not_remote_success','race_id':bundle['race_id']}))
        except Exception as e:
            stamp=datetime.now(scenario.JST).strftime('%Y%m%d/%H%M%S_%f')
            immutable(Path(a.state)/PREFIX/'failures'/(stamp+'.json'),{'observed_at':datetime.now(scenario.JST).isoformat(),'reason':str(e),'status':'missing_not_success'})
            # Failure logs remain in a resumable outbox even if the push is down.
            if a.publish:
                try:persist(a.state)
                except Exception:pass
            raise

if __name__=='__main__':main()
