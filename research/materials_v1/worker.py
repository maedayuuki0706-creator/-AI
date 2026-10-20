"""Bounded independent worker. The only remote writer is its own state branch."""
import argparse,json,os,subprocess,time,urllib.request
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from .collector import Store,read,write,once,encode,now,stamp,digest,aware,capture,import_existing,import_existing_results,grade,VENUES
from .supplement import refresh_daily,complete_results

STATE_BRANCH='research-materials-state-v1'
REPO='maedayuuki0706-creator/-AI'

def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.STDOUT,text=True).strip()

def publish(store):
    branch=git(store.root,'branch','--show-current')
    if branch!=STATE_BRANCH:raise ValueError('Refuse to write any existing branch: '+branch)
    # This dedicated state tree may only contain research evidence.
    untracked=git(store.root,'status','--porcelain')
    if not untracked:return None
    git(store.root,'add','.')
    git(store.root,'commit','-m','research materials: immutable observations and audit')
    git(store.root,'push','origin','HEAD:refs/heads/'+STATE_BRANCH)
    commit=git(store.root,'rev-parse','HEAD')
    remote=git(store.root,'ls-remote','origin','refs/heads/'+STATE_BRANCH).split()[0]
    if remote!=commit:raise ValueError('Remote state commit not confirmed')
    # Git ref API/CDN can temporarily return the previous head after git push.
    # Require a fresh server response; a stale/missing acknowledgement must
    # never become a prospective receipt, but must not stop data collection.
    body={};server_date=None;error=None
    for attempt in range(3):
        proof_url='https://api.github.com/repos/'+REPO+'/git/ref/heads/'+STATE_BRANCH+'?materials_proof='+commit+'&request='+str(time.time_ns())
        req=urllib.request.Request(proof_url,headers={'User-Agent':'BoatAI-MaterialsResearch/1.0','Cache-Control':'no-cache'})
        try:
            with urllib.request.urlopen(req,timeout=20) as response:
                body=json.load(response);server_date=response.headers.get('Date')
            if body.get('object',{}).get('sha')==commit and server_date and abs((now()-parsedate_to_datetime(server_date)).total_seconds())<60:break
            error='remote API returned an old head or stale server date'
        except Exception as exc:error=type(exc).__name__+': '+str(exc)[:180]
        time.sleep(attempt+1)
    else:
        store.record('persistence_pending',commit,{'commit':commit,'checked_at':stamp(),'reason':error,'git_push_confirmed':True,'prospective_receipt_confirmed':False})
        return {'remote_commit':commit,'status':'git_saved_api_ack_pending','new_forecast_receipts':0,'reason':error}
    checked=stamp();server_at=parsedate_to_datetime(server_date)
    added=0
    for p in (store.root/'fusion_forecasts').glob('*.json'):
        receipt=store.root/'remote_receipts'/p.name
        if receipt.exists():continue
        f=read(p);inp=store.root/'fusion_inputs'/p.name
        deadline=aware(f['deadline_at'])
        file_path='fusion_forecasts/'+p.name;input_path='fusion_inputs/'+p.name
        if git(store.root,'show',commit+':'+file_path).strip()!=p.read_text().strip():raise ValueError('Remote commit forecast mismatch')
        if git(store.root,'show',commit+':'+input_path).strip()!=inp.read_text().strip():raise ValueError('Remote commit input mismatch')
        before=aware(checked)<deadline and server_at<deadline
        value={'race_id':p.stem,'remote_commit':commit,'remote_ref':STATE_BRANCH,'ref_url':req.full_url,'github_server_date':server_date,'checked_at':checked,
            'forecast_sha256':digest(p.read_bytes()),'input_sha256':digest(inp.read_bytes()),'forecast_git_blob':git(store.root,'rev-parse',commit+':'+file_path),
            'input_git_blob':git(store.root,'rev-parse',commit+':'+input_path),'confirmed_before_deadline':before,
            'reason':None if before else 'remote acknowledgement after cutoff; exclude prospective score'}
        once(receipt,encode(value));added+=1
    if added:
        git(store.root,'add','remote_receipts');git(store.root,'commit','-m','research materials: independent remote receipt confirmations');git(store.root,'push','origin','HEAD:refs/heads/'+STATE_BRANCH)
    return {'remote_commit':commit,'checked_at':checked,'github_server_date':server_date,'new_forecast_receipts':added}

def tick(store,old,source_sha):
    start=stamp();before=store.fetches
    reuse=import_existing(store,old,source_sha);results=import_existing_results(store,old,source_sha)
    day=now().strftime('%Y%m%d');rows=[]
    # Read the schedule already persisted by the existing worker. No extra
    # whole-day official card polling while that worker provides the schedule.
    for code in VENUES:
        scheduled=[]
        for p in (Path(old)/'schedules'/day).glob('*.json'):
            s=read(p)
            # Existing schedule formats are intentionally inspected rather
            # than trusting arbitrary fields as race identities.
            if code in s.get('schedules',{}):scheduled.append(s)
        candidates={}
        for p in (Path(old)/'inputs'/day).glob(f'{day}_{code}_*.json'):
            m=read(p)['meta'];candidates[int(m['rno'])]=m['deadline']
        # Published schedule arrays can supply races before a prior input exists.
        for s in scheduled:
            for i,hhmm in enumerate(s.get('schedules',{}).get(code,[]),1):
                if isinstance(hhmm,str):candidates[i]=hhmm
            for r in s.get('races',[]):
                if isinstance(r,dict) and r.get('rno') and r.get('deadline'):candidates[int(r['rno'])]=r['deadline']
        # An incomplete schedule must not hide later races just because one
        # early input has already been captured.
        if len(candidates)<12:
            try:
                c=store.get(__import__('research.materials_v1.collector',fromlist=['url']).url('racelist',day,code,1),ttl=1800)
                if c['status']=='ok':
                    from .collector import deadline
                    body=store.body(c)
                    for r in range(1,13):candidates[r]=deadline(body,r)
            except Exception:pass
        for r,hhmm in sorted(candidates.items()):
            when=datetime.strptime(day+' '+hhmm,'%Y%m%d %H:%M').replace(tzinfo=now().tzinfo);remaining=(when-now()).total_seconds()
            # Minimum work outside the <=20m capture window. Tomorrow's cards
            # and the late result-only refresh are separate daily work.
            if 0<=remaining<=1235:
                try:rows.append(capture(store,day,code,r,allow_result=False))
                except Exception as exc:rows.append({'race_id':f'{day}_{code}_{r:02}','status':'error','reason':str(exc)})
            elif remaining < -180 and not (store.root/'reused_inputs'/f'{day}_{code}_{r:02}.json').exists():
                try:rows.append(capture(store,day,code,r))
                except Exception as exc:rows.append({'race_no':r,'venue_code':code,'status':'error','reason':str(exc)})
    # Repair payout-only originals without touching input or old research state.
    completed=complete_results(store,old,day)
    grade(store)
    run={'started_at':start,'completed_at':stamp(),'source_sha':source_sha,'imported_inputs':reuse['newly_imported'],'imported_results':results,
        'http_requests':store.fetches-before,'captures':rows,'completed_results':completed,'existing_sources_read_only':True}
    store.record('runs','tick',run);return run

def main():
    p=argparse.ArgumentParser();p.add_argument('--state',required=True,type=Path);p.add_argument('--reuse',required=True,type=Path);p.add_argument('--source-sha',required=True);p.add_argument('--seconds',type=int,default=0);p.add_argument('--interval',type=int,default=20);p.add_argument('--publish',action='store_true');a=p.parse_args()
    if not 0<=a.seconds<=600 or not 15<=a.interval<=60:raise ValueError('Bounded worker limits')
    s=Store(a.state);end=time.monotonic()+a.seconds
    refresh_daily(s)
    while True:
        r=tick(s,a.reuse,a.source_sha);print(json.dumps(r,ensure_ascii=False),flush=True)
        if a.publish:print(json.dumps({'persistence':publish(s)}),flush=True)
        if time.monotonic()+a.interval>end:break
        time.sleep(a.interval)

if __name__=='__main__':main()
