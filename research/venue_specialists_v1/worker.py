"""Bounded research worker: each tick persists first, receipts second, results last."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import time
from . import run, review
from .audit import coverage_counts

BRANCH='research-venue-specialists-state'
PREFIX='data/venue_specialists_v1'


def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args],text=True,stderr=subprocess.STDOUT,timeout=40)


def persist(state,message):
    git(state,'add','--',PREFIX)
    if not git(state,'diff','--cached','--name-only').strip():return None
    # Prevent accidental writes outside the independent research subtree.
    paths=git(state,'diff','--cached','--name-only').splitlines()
    if any(not p.startswith(PREFIX+'/') for p in paths):raise ValueError('Non-research staged path')
    git(state,'commit','-m',message)
    try:
        git(state,'push','origin','HEAD:refs/heads/'+BRANCH)
    except subprocess.CalledProcessError:
        # Another authorized research writer may append originals. Never force
        # the state branch or choose one version of a conflicting original.
        git(state,'fetch','--depth=20','origin',BRANCH)
        remote_sha=git(state,'rev-parse','FETCH_HEAD').strip()
        try:
            git(state,'merge','--no-edit',remote_sha)
        except subprocess.CalledProcessError:
            conflicts=git(state,'diff','--name-only','--diff-filter=U').splitlines()
            if conflicts != [PREFIX+'/summary/latest.json']:
                git(state,'merge','--abort')
                raise ValueError('Conflicting immutable research originals; refusing overwrite')
            git(state,'checkout','--theirs','--',PREFIX+'/summary/latest.json')
            git(state,'add','--',PREFIX+'/summary/latest.json')
            git(state,'commit','--no-edit')
        git(state,'push','origin','HEAD:refs/heads/'+BRANCH)
    sha=git(state,'rev-parse','HEAD').strip()
    remote=git(state,'ls-remote','origin','refs/heads/'+BRANCH).split()[0]
    if remote!=sha:raise ValueError('Remote state branch head did not confirm push')
    return sha


def tick(state):
    state=Path(state);root=state/PREFIX
    collected=run.run(root,max_workers=2)
    # Commit originals even when capture/coverage is degraded.
    sha=persist(state,'research: freeze specialist originals and coverage')
    if sha:
        run.verify_commit(root,sha,git_show=lambda commit,path:git(state,'show',f'{commit}:{path}'))
        persist(state,'research: bind remote originals to immutable receipts')
    reviewed=review.run(root)
    persist(state,'research: official results and specialist coverage scoreboard')
    health=coverage_counts(root,collected['day'])
    return {'at':run.now_jst().isoformat(),'capture':{k:v for k,v in collected.items() if k!='elapsed_races_without_confirmed_forecast'},
            'reviews':reviewed,'coverage':health}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',required=True)
    p.add_argument('--seconds',type=int,default=480);p.add_argument('--interval',type=int,default=60)
    a=p.parse_args();finish=time.monotonic()+a.seconds;errors=[]
    while True:
        start=time.monotonic()
        try:
            local_now=run.now_jst()
            if local_now.hour<8:
                result={"at":local_now.isoformat(),"health":"idle_outside_hours",
                        "note":"No official fetch or prediction overnight; retain independent continuation for next research day"}
            else:result=tick(a.state)
        except Exception as exc:
            result={'at':run.now_jst().isoformat(),'health':'error','error_type':type(exc).__name__,'reason':str(exc)[:500]}
            errors.append(result)
        print(json.dumps(result,ensure_ascii=False),flush=True)
        summary=os.getenv('GITHUB_STEP_SUMMARY')
        if summary:
            with open(summary,'a') as stream:stream.write('\n```json\n'+json.dumps(result,ensure_ascii=False)+'\n```\n')
        if time.monotonic()+a.interval>=finish:break
        time.sleep(max(1,a.interval-(time.monotonic()-start)))
    if errors:raise SystemExit('Research worker encountered errors; originals retained; see per-tick records')


if __name__=='__main__':main()
