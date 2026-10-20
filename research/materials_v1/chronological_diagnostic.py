"""Retrospective date-separated wind diagnostic. Never imports live models.

The target is the winning lane, not an inferred actual course or tactic.
Validation chooses between two prespecified wind buckets. Final dates are not
used for model/bucket selection; historical data were already viewed, so this
is not a pristine prospective holdout or a claim of live wagering performance.
"""
from collections import Counter,defaultdict
import argparse,gzip,json,math
from pathlib import Path
from .collector import write,stamp,digest

def speed(v):return '0-1' if v<=1 else '2-3' if v<=3 else '4-5' if v<=5 else '6+'
def run(archive,out):
    rows=[];ids=set();missing=0
    for p in sorted((Path(archive)/'days').glob('*.json.gz')):
        for r in json.loads(gzip.decompress(p.read_bytes()))['races']:
            if not r['official_normal_eligible']:continue
            if r['race_id'] in ids:raise ValueError('Duplicate race')
            ids.add(r['race_id']);w=(r.get('preview_environment') or {}).get('wind_speed')
            winners=[b['lane'] for b in r['boats'] if b['official_finish']==1]
            if w is None or len(winners)!=1:missing+=1;continue
            rows.append({'id':r['race_id'],'day':r['day'],'venue':r['venue_code'],'y':winners[0]-1,'wind':speed(w),'direction':r.get('preview_wind_direction_text') or 'unknown'})
    train=[r for r in rows if r['day']<'2026-08-01'];val=[r for r in rows if '2026-08-01'<=r['day']<'2026-09-01'];test=[r for r in rows if r['day']>='2026-09-01']
    assert train and val and test and max(r['day'] for r in train)<min(r['day'] for r in val)<min(r['day'] for r in test)
    base=defaultdict(lambda:Counter());counts={k:defaultdict(lambda:Counter()) for k in ['wind','direction_wind']}
    for r in train:
        base[r['venue']][r['y']]+=1
        for kind in counts:
            key=(r['venue'],r['wind']) if kind=='wind' else (r['venue'],r['wind'],r['direction'])
            counts[kind][key][r['y']]+=1
    def probabilities(r,kind):
        b=base[r['venue']];n=sum(b.values());prior=[(b[i]+5)/(n+30) for i in range(6)]
        if kind=='venue_lane_prior':return prior
        key=(r['venue'],r['wind']) if kind=='wind' else (r['venue'],r['wind'],r['direction'])
        g=counts[kind][key];gn=sum(g.values())
        # Fixed shrinkage is prespecified; never tune on the final sample.
        return [(g[i]+100*prior[i])/(gn+100) for i in range(6)]
    def score(rs,kind):
        loss=0;hits=0
        for r in rs:
            ps=probabilities(r,kind);loss-=math.log(ps[r['y']]);hits+=max(range(6),key=lambda i:ps[i])==r['y']
        return {'races':len(rs),'winner_log_loss':round(loss/len(rs),6),'head_hits':hits,'head_accuracy_pct':round(100*hits/len(rs),3)}
    validation={k:score(val,k) for k in ['venue_lane_prior','wind','direction_wind']}
    selected=min(['wind','direction_wind'],key=lambda k:validation[k]['winner_log_loss'])
    final={k:score(test,k) for k in ['venue_lane_prior',selected]}
    result={'generated_at':stamp(),'source_summary_sha256':digest((Path(archive)/'summary.json').read_bytes()),'normal_races':len(ids),'missing_inputs':missing,
        'partitions':{k:{'races':len(rs),'first_day':min(r['day'] for r in rs),'last_day':max(r['day'] for r in rs)} for k,rs in [('train',train),('validation',val),('final',test)]},
        'validation':validation,'selected_using_validation_only':selected,'final':final,'final_log_loss_difference_vs_baseline':round(final[selected]['winner_log_loss']-final['venue_lane_prior']['winner_log_loss'],6),
        'prospective':False,'historical_predeadline_receipts_verified':False,'trifecta_roi_measured':False,'production_adoption':False,
        'limits':['Retrospective archived preview values were acquired after races','Previously explored historical period, not pristine unseen holdout','Winner lane diagnosis does not validate ten-ticket cards or attack mechanisms','Nearby tide observations, actual ST and final odds were not model inputs','Coefficients are not connected to production; verify with forward 100R then 300R']}
    write(Path(out)/'reports/wind_chronological_diagnostic.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True);p.add_argument('--out',required=True);a=p.parse_args();print(json.dumps(run(a.archive,a.out),ensure_ascii=False))
