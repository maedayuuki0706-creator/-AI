"""Append-only research branch persistence; receipt only after remote fetch/readback."""
import argparse,json,os,re,subprocess
from datetime import datetime
from pathlib import Path
from .live import PREFIX,freeze
from research.ultimate_fusion_v1 import engine as e
BRANCH='research-ultimate-fusion-forward-state-20261102'

def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args],text=True,stderr=subprocess.STDOUT,timeout=60).strip()

def allowed(staged):
    for line in staged.splitlines():
        status,path=line.split('\t',1)
        if status!='A' or not path.startswith(PREFIX+'/') or '..' in Path(path).parts:raise ValueError('non_append_research_write_refused')

def verify_bundle(bundle):
    if bundle.get('sha256')!=e.digest({k:v for k,v in bundle.items() if k!='sha256'}):raise ValueError('bundle_digest_mismatch')
    r=bundle['report']
    if r.get('sha256')!=e.digest({k:v for k,v in r.items() if k!='sha256'}):raise ValueError('report_digest_mismatch')
    if r['mode']!='prospective_uncheckpointed' or r['race_id']!=bundle['race_id']:raise ValueError('not_prospective')
    if bundle['deadline_at']!=r['snapshot']['deadline_at'] or bundle['created_at']!=r['generated_at']:raise ValueError('bundle_time_mismatch')
    if e.aware(bundle['created_at'])>e.aware(bundle['deadline_at']):raise ValueError('late_generation')

def persist(root,clock=None):
    root=Path(root);clock=clock or (lambda:datetime.now(e.JST))
    if git(root,'branch','--show-current')!=BRANCH:raise ValueError('wrong_state_branch')
    (root/PREFIX).mkdir(parents=True,exist_ok=True)
    git(root,'add','--',PREFIX);staged=git(root,'diff','--cached','--name-status','--no-renames');allowed(staged)
    if staged:git(root,'commit','-m','Append isolated fusion research originals')
    # Retry unpushed HEAD even when index is clean; never force, reset or overwrite.
    git(root,'push','origin',f'HEAD:refs/heads/{BRANCH}')
    git(root,'fetch','--quiet','origin',f'refs/heads/{BRANCH}')
    remote=git(root,'rev-parse','FETCH_HEAD');head=git(root,'rev-parse','HEAD')
    git(root,'merge-base','--is-ancestor',head,remote)
    observed=e.aware(clock());receipts=[]
    for path in sorted((root/PREFIX/'captures').glob('*/*.json')):
        bundle=json.loads(path.read_text());verify_bundle(bundle)
        dest=root/PREFIX/'receipts'/(bundle['race_id']+'.json')
        if dest.exists():continue
        relative=path.relative_to(root).as_posix()
        stored=json.loads(git(root,'show',remote+':'+relative))
        if stored!=bundle:raise ValueError('remote_readback_mismatch')
        receipt={'race_id':bundle['race_id'],'bundle_sha256':bundle['sha256'],'report_sha256':bundle['report']['sha256'],
                 'remote_commit':remote,'remote_path':relative,'observed_remote_at':observed.isoformat(),
                 'deadline_at':bundle['deadline_at'],'workflow_run_id':os.getenv('GITHUB_RUN_ID'),
                 'status':'confirmed_predeadline' if observed<e.aware(bundle['deadline_at']) else 'late_remote_confirmation_excluded'}
        receipt['sha256']=e.digest(receipt);freeze(dest,receipt);receipts.append(receipt)
    if receipts:
        git(root,'add','--',PREFIX+'/receipts');allowed(git(root,'diff','--cached','--name-status','--no-renames'))
        git(root,'commit','-m','Append remote-readback receipts; late observations excluded')
        git(root,'push','origin',f'HEAD:refs/heads/{BRANCH}')
    return receipts

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--state',required=True);a=p.parse_args();print(json.dumps(persist(a.state),ensure_ascii=False))
