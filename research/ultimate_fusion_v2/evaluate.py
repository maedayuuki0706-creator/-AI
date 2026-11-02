"""Reproducible expanding-window retrospective evaluation; no live accuracy claim."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
from research.ultimate_fusion_v1 import engine as v1
from .core import fit, predict, save_immutable, VERSION


def metrics(rows, field):
    n=len(rows); hits=sum(r[field]['hit'] for r in rows)
    stake=sum(r[field]['stake'] for r in rows); paid=sum(r[field]['paid'] for r in rows)
    return {'races':n,'hits':hits,'hit_rate_pct':round(100*hits/n,2) if n else None,
            'stake_yen':stake,'return_yen':paid,'roi_pct':round(100*paid/stake,2) if stake else None}


def replay_snapshot(raw):
    # Explicit replay projection, NEVER persist this as a prospective source.
    projected={k:raw[k] for k in ('day','jcd','rno','deadline','captured_at')}
    projected['rows']=[{k:b.get(k) for k in v1.PRE_RACE_KEYS} for b in raw['rows']]
    s=v1.prepare_live(projected)
    s['archive_raw_sha256']=v1.digest(raw)
    s['source_mode']='retrospective_mutable_archive_projection'
    return s


def run(root, output, start, end, baseline_root=None):
    root=Path(root);out=Path(output);out.mkdir(parents=True,exist_ok=True)
    records=[];invalid=Counter()
    for p in sorted((root/'data/exhibition_log').rglob('*.json')):
        try:records.append(json.loads(p.read_text()))
        except (ValueError,OSError):invalid['unreadable']+=1
    result_cache={p.stem:json.loads(p.read_text()) for p in (root/'data/official_results').glob('*.json')}
    groups=defaultdict(list)
    for r in records:
        if start<=r.get('day','')<=end:groups[(r['day'],str(r['jcd']).zfill(2))].append(r)
    scored=[]; manifest=[];example=None
    for (day,code),targets in sorted(groups.items()):
        model=fit(records,day,code)
        if model['training_races']<30:
            invalid['insufficient_venue_history']+=len(targets);continue
        for raw in sorted(targets,key=lambda r:r['rno']):
            try:
                # Outcome lives in evaluation only, not the prediction interface.
                result=result_cache.get(day,{}).get(f'{code}:{raw["rno"]}')
                if not result or result.get('status')!='settled' or result.get('refund_lanes') or len(result.get('payouts',{}))!=1:
                    invalid['missing_or_exception_result']+=1;continue
                actual,payout=next(iter(result['payouts'].items()))
                v1.boats_six(raw['rows'])
                if sorted(b.get('finish',0) or 0 for b in raw['rows'])!=list(range(1,7)):
                    invalid['non_normal_finish']+=1;continue
                if actual!='-'.join(str(b['lane']) for b in sorted(raw['rows'],key=lambda b:b['finish'])[:3]):
                    invalid['result_disagreement']+=1;continue
                snap=replay_snapshot(raw)
                report=predict(snap,model,now=snap['snapshot_at'],mode='replay')
                item={'race_id':snap['race_id'],'day':day,'venue':code,'actual':actual,
                      'payout_band':'万舟' if payout>=10000 else '中穴' if payout>=3000 else '本線帯',
                      'winning_method':raw['rows'][0].get('method') or '不明',
                      'prediction_sha256':report['sha256'],'raw_sha256':v1.digest(raw)}
                for name,picks in [('baseline',report['baseline_picks']),('fusion',report['research_picks'])]:
                    item[name]={'hit':actual in picks,'stake':100*len(picks),'paid':payout if actual in picks else 0,'picks':picks}
                a,b,c=actual.split('-');picks=report['research_picks']
                item['miss_reason']=('hit' if actual in picks else 'head_not_selected' if not any(x.startswith(a+'-') for x in picks) else 'second_not_selected' if not any(x.startswith(a+'-'+b+'-') for x in picks) else 'third_not_selected')
                if baseline_root:
                    bp=Path(baseline_root)/'data/venue_specialists_v1/forecasts'/day/(snap['race_id']+'.json')
                    if bp.exists():
                        old=json.loads(bp.read_text());card=old.get('specialist_card') or old.get('virtual_card') or {}
                        oldp=[x['combination'] for x in card] if isinstance(card,list) else card.get('picks')
                        if old.get('digest') != v1.digest({k:v for k,v in old.items() if k!='digest'}) or v1.aware(old['created_at']) > v1.aware(old['deadline_at']):
                            oldp=None
                        if oldp and len(set(oldp))==len(oldp) and set(oldp)<=set(v1.COMBOS):
                            item['existing_four']={'hit':actual in oldp,'stake':len(oldp)*100,'paid':payout if actual in oldp else 0,'picks':oldp}
                scored.append(item)
                if example is None or (code=='16' and day>=example['snapshot']['day']):example=report
                manifest.append({'race_id':snap['race_id'],'source_sha256':v1.digest(raw),'training_sha256':v1.digest(model)})
            except (ValueError,KeyError,TypeError) as exc:invalid[str(exc)]+=1
    summary={'schema':VERSION,'mode':'retrospective_replay','window':[start,end],
             'archive_records':len(records),'evaluated_races':len(scored),'excluded':dict(invalid),
             'baseline':metrics(scored,'baseline'),'fusion':metrics(scored,'fusion'),
             'by_venue':{},'by_payout_band':{},'by_winning_method':{},
             'miss_reasons':dict(Counter(r['miss_reason'] for r in scored)),
             'prospective_verified_races':0,'calibrated':False,'live_improvement_proven':False,
             'note':'結果追記済み展示ログの事後再生。確定払戻帯は事後分類で、締切前オッズ帯ではない。固定10点各100円。手法選択後の期間外検証は別途必要。'}
    for group,key in [('by_venue','venue'),('by_payout_band','payout_band'),('by_winning_method','winning_method')]:
        for val in sorted({r[key] for r in scored}):
            subset=[r for r in scored if r[key]==val]
            summary[group][val]={m:metrics(subset,m) for m in ('baseline','fusion')}
    matched=[r for r in scored if 'existing_four' in r]
    summary['matched_existing_four']={m:metrics(matched,m) for m in ('fusion','baseline','existing_four')}
    for name,obj in [('evaluation.json',summary),('evaluation_rows.json',scored),('input_manifest.json',manifest)]:
        (out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    if example:
        save_immutable(example,out/'records')
        (out/'example.json').write_text(json.dumps(example,ensure_ascii=False)+'\n')
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default='.');p.add_argument('--output',required=True)
    p.add_argument('--start',default='20261025');p.add_argument('--end',default='20261031');p.add_argument('--baseline-root')
    a=p.parse_args(); print(json.dumps(run(a.root,a.output,a.start,a.end,a.baseline_root),ensure_ascii=False,indent=2))
