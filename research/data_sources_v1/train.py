"""Fixed LightGBM experiments on official-matched historical research only.

No model promotion, delivery, odds use, or retrospective pre-deadline claims.
"""
import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path

from .collect import digest, encode, save_json

FEATURES = ['venue_code','lane','exhibition_course','average_st','exhibition_time',
            'tilt','flying_count','national_win_rate','local_win_rate',
            'motor_top_2_percent','preview_wind_speed','preview_wave_height']


def feature_vector(race, boat, include_exhibition_st=False):
    program, preview = boat['program'], boat['preview']
    values = [int(race['venue_code']),boat['lane'],boat.get('exhibition_course'),boat.get('average_st'),
              preview.get('exhibition_time'),boat.get('tilt'),program.get('flying_count'),
              program.get('national_win_rate'),program.get('local_win_rate'),program.get('motor_top_2_percent'),
              race['preview_environment'].get('wind_speed'),race['preview_environment'].get('wave_height')]
    if include_exhibition_st:
        values.append(boat.get('exhibition_st'))
    # Explicit allowlist; result ST, finishes, payouts and historical odds can
    # never become features by adding fields to an upstream response.
    return [float(v) if isinstance(v,(int,float)) and not isinstance(v,bool) else float('nan') for v in values]


def split_days(races):
    dates=sorted({r['day'] for r in races})
    if len(dates)<30:
        raise ValueError('Need at least 30 distinct race days before evaluation')
    a,b=int(len(dates)*.6),int(len(dates)*.8)
    groups=[set(dates[:a]),set(dates[a:b]),set(dates[b:])]
    return [[r for r in races if r['day'] in group] for group in groups]


def eligible(r):
    boats=r['boats']
    return (r.get('official_normal_eligible') and not r.get('conflicts')
            and len(boats)==6 and {b.get('official_finish') for b in boats}==set(range(1,7))
            and {b.get('exhibition_course') for b in boats}==set(range(1,7)))


def main():
    import lightgbm as lgb
    import numpy as np
    from sklearn.metrics import brier_score_loss

    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True);a=p.parse_args()
    root=Path(a.out)
    records=[];input_files=[]
    for path in sorted((root/'days').glob('*.json.gz')):
        raw=path.read_bytes();input_files.append({'name':path.name,'sha256':digest(raw)})
        records.extend(json.loads(gzip.decompress(raw))['races'])
    ids=[r['race_id'] for r in records]
    if len(ids)!=len(set(ids)):
        raise ValueError('Duplicate race IDs must never inflate training samples')
    usable=[r for r in records if eligible(r)]
    train,valid,test=split_days(usable)
    if len(train)<500 or len(valid)<100 or len(test)<100:
        raise ValueError('Need 500 training / 100 validation / 100 final races')
    result={'created_at':datetime.now(timezone.utc).isoformat(), 'library':lgb.__version__,
            'kind':'retrospective_diagnostic_not_prospective',
            'input_manifest_sha256':digest(encode(input_files)), 'input_files':input_files,
            'eligible_races':len(usable),'excluded_races':len(records)-len(usable),
            'splits':{name:{'races':len(rows),'start':min(r['day'] for r in rows),'end':max(r['day'] for r in rows)}
                      for name,rows in [('train',train),('validation',valid),('final',test)]},
            'features':FEATURES,'production_changes':0,'models':{},
            'limitations':['API input values remain nonofficial historical snapshots',
                           'Final split is now observed; reuse requires a new future holdout',
                           'No ROI or EV claim; no fixed tickets or pre-deadline odds receipts',
                           'No deployment; predictions are research diagnostics only']}
    prior={}
    for r in train:
        for boat in r['boats']:
            key=(r['venue_code'],boat['lane']);n,w=prior.get(key,(0,0));prior[key]=(n+1,w+(boat['official_finish']==1))
    def metrics(rows, pred):
        y=[int(b['official_finish']==1) for r in rows for b in r['boats']]
        pred=np.clip(np.asarray(pred).reshape(-1,6),1e-6,1-1e-6)
        # Each normal race has exactly one winner. Normalize consistently for
        # both baseline and learned classifiers before evaluating.
        pred=pred/pred.sum(axis=1,keepdims=True)
        y=np.asarray(y).reshape(-1,6)
        def score(y,pred):
            return {'races':len(pred),'winner_log_loss':float(-np.log(pred[y==1]).mean()),
                'boat_brier':float(brier_score_loss(y.reshape(-1),pred.reshape(-1))),
                'top1_hit_rate':float((pred.argmax(axis=1)==y.argmax(axis=1)).mean())}
        values=score(y,pred)
        values['by_venue']={}
        for venue in sorted({r['venue_code'] for r in rows}):
            mask=np.asarray([r['venue_code']==venue for r in rows])
            values['by_venue'][venue]=score(y[mask],pred[mask])
        return values
    result['models']['training_venue_lane_frequency']={}
    for name,rows in [('validation',valid),('final',test)]:
        predictions=[]
        for r in rows:
            for boat in r['boats']:
                n,w=prior.get((r['venue_code'],boat['lane']),(0,0));predictions.append((w+1)/(n+6))
        result['models']['training_venue_lane_frequency'][name]=metrics(rows,predictions)
    for include_st in (False,True):
        matrix=lambda rows:np.asarray([feature_vector(r,b,include_st) for r in rows for b in r['boats']],dtype=float)
        labels=np.asarray([int(b['official_finish']==1) for r in train for b in r['boats']])
        model=lgb.LGBMClassifier(n_estimators=100,learning_rate=.04,num_leaves=15,
                min_child_samples=80,random_state=20261019,n_jobs=2,verbosity=-1,
                deterministic=True,force_col_wise=True)
        model.fit(matrix(train),labels)
        key='lightgbm_with_exhibition_st' if include_st else 'lightgbm_without_exhibition_st'
        result['models'][key]={name:metrics(rows,model.predict_proba(matrix(rows))[:,1])
                               for name,rows in [('validation',valid),('final',test)]}
        names=FEATURES+(['exhibition_st'] if include_st else [])
        result['models'][key]['feature_importance_split_count']=dict(zip(names,map(int,model.feature_importances_)))
    save_json(root/'LIGHTGBM_DIAGNOSTIC.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
