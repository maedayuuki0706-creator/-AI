from __future__ import annotations
import json
from pathlib import Path

import daily_report as dr
import direct_discord_notify as base

DAY='20260914'
JCD='09'
RNO=12
TARGET='4-1-2'
OUT=Path('data/case_studies/20260914_tsu12.json')


def main():
    predictions=dr.read_jsonl(base.LOG_PATH)
    chosen,_=dr.latest_predictions(predictions,DAY)
    key=f'{JCD}:{RNO}'
    delivered=chosen.get(key)
    analysis=base.analyze_official(DAY,JCD,RNO)
    raw_result=base.fetch(base.official_url('raceresult',DAY,JCD,RNO))
    official=dr.parse_payout(raw_result)

    target=None
    prob_rank=None
    ev_rank=None
    top_prob=[]
    top_ev=[]
    if analysis:
        trif=analysis.get('trifecta') or []
        for i,row in enumerate(trif,1):
            if row.get('combination')==TARGET:
                target=row
                prob_rank=i
                break
        ev_rows=[r for r in trif if r.get('expected_value') is not None]
        ev_rows.sort(key=lambda r:r.get('expected_value') or -1, reverse=True)
        for i,row in enumerate(ev_rows,1):
            if row.get('combination')==TARGET:
                ev_rank=i
                break
        top_prob=trif[:20]
        top_ev=ev_rows[:20]

    out={
        'day':DAY,'jcd':JCD,'venue':'津','rno':RNO,'target':TARGET,
        'delivered_prediction':delivered,
        'recomputed_analysis':analysis,
        'target_analysis':target,
        'target_probability_rank':prob_rank,
        'target_ev_rank':ev_rank,
        'top_probability':top_prob,
        'top_expected_value':top_ev,
        'official_result':official,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps({
        'delivered_main':(delivered or {}).get('main'),
        'delivered_cover':(delivered or {}).get('cover'),
        'delivered_heads':(delivered or {}).get('heads'),
        'target':target,
        'target_probability_rank':prob_rank,
        'target_ev_rank':ev_rank,
        'boat_scores':(analysis or {}).get('boats'),
        'preview':(analysis or {}).get('preview'),
        'official':official,
    },ensure_ascii=False,sort_keys=True))

if __name__=='__main__':
    main()
