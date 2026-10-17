"""Compare immutable specialist reviews with Git-proven frozen New Yuuki originals."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
from research.scenario_v2.adapters import from_fusion
from research.scenario_v2.batch import verify_git_source
from research.scenario_v2.collector import save_immutable
from .engine import digest,JST


def compare_record(forecast, specialist_review, baseline, checkpoint):
    from_fusion(baseline,checkpoint) # validates identity, timestamps, source digest and original card
    if baseline['key']!=forecast['race_id'] or specialist_review['race_id']!=forecast['race_id']:
        raise ValueError('Comparison race mismatch')
    if specialist_review.get('status')!='graded':raise ValueError('Only common normal graded races')
    picks=baseline['models']['fusion']['picks'];payouts=specialist_review['official_trifectas']
    payout=sum(int(value) for combo,value in payouts.items() if combo in picks)
    out={'race_id':forecast['race_id'],'specialist_forecast_digest':forecast['digest'],
         'specialist_review_digest':specialist_review['digest'],'baseline_digest':baseline['digest'],
         'baseline_commit':checkpoint['commit_sha'],'stake_yen_each':1000,
         'specialist_hit':specialist_review['hit'],'specialist_return_yen':specialist_review['return_yen'],
         'new_yuuki_hit':any(c in picks for c in payouts),'new_yuuki_return_yen':payout,
         'status':'same_race_same_budget_git_proven','probabilities_calibrated':False}
    out['digest']=digest(out);return out


def run(root,repo,ref):
    root=Path(root);saved=[];unavailable=[]
    def show(path):return json.loads(subprocess.check_output(['git','-C',str(repo),'show',f'{ref}:{path}'],text=True,stderr=subprocess.DEVNULL,timeout=20))
    for path in sorted((root/'reviews').glob('20*/*.json')):
        review=json.loads(path.read_text());key=review['race_id'];date=key[:8]
        dest=root/'comparisons'/date/(key+'.json')
        if dest.exists() or review.get('status')!='graded':continue
        try:
            baseline=show(f'data/fusion_shadow/predictions/{date}/{key}.json')
            checkpoint=show(f'data/fusion_shadow/checkpoints/{date}/{key}.json')
            verify_git_source(repo,baseline,checkpoint)
            forecast=json.loads((root/'forecasts'/date/(key+'.json')).read_text())
            record=compare_record(forecast,review,baseline,checkpoint)
            save_immutable(dest,record);saved.append(key)
        except (ValueError,KeyError,OSError,subprocess.SubprocessError) as exc:
            unavailable.append({'race_id':key,'reason':type(exc).__name__})
    return {'saved':saved,'unavailable':unavailable,'checked_at':datetime.now(JST).isoformat()}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True)
    p.add_argument('--baseline-repo',required=True);p.add_argument('--baseline-ref',default='origin/research-fusion-shadow-state')
    a=p.parse_args();print(json.dumps(run(a.out,a.baseline_repo,a.baseline_ref),ensure_ascii=False))


if __name__=='__main__':main()
