"""Review only read-back-confirmed originals against separately acquired official results."""
import argparse,json,re,subprocess
from pathlib import Path
from .live import PREFIX,freeze
from .checkpoint import git
from .review import review
from research.ultimate_fusion_v1 import engine as e

def score(state,results,out):
    state=Path(state);rows=[];pending=[]
    for p in sorted((state/PREFIX/'receipts').glob('*.json')):
        receipt=json.loads(p.read_text());key=receipt['race_id'];day,code,rno=key.split('_')
        try:
            # Prove the exact captured object exists at the recorded remote commit.
            commit=receipt['remote_commit']
            if not re.fullmatch('[0-9a-f]{40}',commit) or receipt['remote_path']!=f'{PREFIX}/captures/{day}/{key}.json':raise ValueError('invalid_receipt_pointer')
            try:git(state,'cat-file','-e',commit)
            except subprocess.CalledProcessError:git(state,'fetch','--depth=1','origin',commit)
            bundle=json.loads(git(state,'show',commit+':'+receipt['remote_path']))
            path=Path(results)/(day+'.json')
            if not path.exists():pending.append({'race_id':key,'reason':'results_not_received'});continue
            result=json.loads(path.read_text()).get(f'{code}:{int(rno)}')
            if not result:pending.append({'race_id':key,'reason':'result_missing'});continue
            expected=f'https://www.boatrace.jp/owpc/pc/race/raceresult?hd={day}&jcd={code}&rno={int(rno)}'
            if result.get('source_url')!=expected:raise ValueError('unexpected_result_source')
            row=review(bundle,receipt,{**result,'race_id':key},result['checked_at']);rows.append(row)
            if row['status']=='reviewed':freeze(Path(out)/'reviews'/(key+'.json'),row)
        except (ValueError,KeyError) as exc:pending.append({'race_id':key,'reason':str(exc)})
    accepted=[r for r in rows if r['status']=='reviewed'];summary={'verified_races':len(accepted),'pending_or_rejected':pending,'models':{}}
    for model in ('fusion','baseline'):
        stakes=sum(r['models'][model]['stake_yen'] for r in accepted);paid=sum(r['models'][model]['return_yen'] for r in accepted)
        summary['models'][model]={'hits':sum(r['models'][model]['hit'] for r in accepted),'stake_yen':stakes,'return_yen':paid,'roi_pct':100*paid/stakes if stakes else None}
    freeze(Path(out)/'summary.json',summary);return summary
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--state',required=True);p.add_argument('--results',required=True);p.add_argument('--out',required=True);a=p.parse_args();print(json.dumps(score(a.state,a.results,a.out),ensure_ascii=False))
