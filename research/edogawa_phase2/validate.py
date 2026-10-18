"""Time-split historical diagnostic plus paired replay of frozen October inputs.

No tuning on final evaluation. Historical A assumes pre-race frame order because
no historical pre-race snapshots exist. B/C and original AI are NOT fabricated
from historical outcomes. Paired A/B replay uses real immutable October inputs.
"""
import argparse,json,math
from pathlib import Path
from collections import Counter,defaultdict
from . import model
from .acquire import put
from .study import writecsv,wilson
from research.scenario_v2 import engine as scenario

def paired_uncertainty(rows):
    # Day-cluster bootstrap, deterministic. Small numbers of days remain inconclusive.
    import random
    byday=defaultdict(list)
    for r in rows:byday[r['日付']].append(r['改良的中']-r['既存的中'])
    days=sorted(byday)
    if not days:return {'days':0,'status':'判定不能'}
    rng=random.Random(20261018);deltas=[]
    for _ in range(1000):
        selected=[d for day in rng.choices(days,k=len(days)) for d in byday[day]]
        deltas.append(sum(selected)/len(selected))
    deltas.sort();mean=sum(sum(x) for x in byday.values())/sum(map(len,byday.values()))
    # A positive interval from 1-2 days is not evidence of stable improvement.
    status='判定不能・開催日/標本不足' if len(days)<10 or len(rows)<100 else '改善' if deltas[25]>0 else '悪化' if deltas[975]<0 else '判定不能'
    return {'days':len(days),'n':len(rows),'mean_hit_delta':mean,'day_cluster_bootstrap_95':[deltas[25],deltas[975]],'status':status,'resamples':1000,'seed':20261018}

def evaluate_history(records,fitted):
    scores=model.course_scores(fitted,'A');picks=['-'.join(map(str,k)) for k in sorted(scores,key=lambda t:(-scores[t],t))[:10]]
    out=[]
    for r in records:
        if not r['normal_eligible'] or r['split']=='学習':continue
        actual=r['trifecta_from_finish'];a=actual.split('-');primary=picks[0].split('-')
        out.append({'race_id':r['race_id'],'日付':r['date'],'区分':r['split'],'モデル':'A・枠なり仮定の後付け研究',
            '買い目':','.join(picks),'実出目':actual,'実決まり手':r['method'],'的中':int(actual in picks),'1着本命正解':int(primary[0]==a[0]),'2着本命正解':int(primary[1]==a[1]),'3着本命正解':int(primary[2]==a[2]),'仮想投資円':1000,'公式払戻100円':r.get('payout_per_100'),
            'ROI':None,'トリガミ':None,'制約':'事前進入・出走者データ・オッズ原本なし。実進入を予想入力に使わず艇番=コースと仮定。既存版/B/Cは再現不能'})
    return out

def replay(pairs,fitted):
    out=[];logs=[]
    for pair in pairs:
        if pair.get('errors') or not all(k in pair for k in ['inputs','forecasts','reviews','receipts']):continue
        snap=pair['inputs'];base=pair['forecasts'];review=pair['reviews'];receipt=pair['receipts']
        if receipt.get('status')!='confirmed_before_deadline' or receipt['digest']!=base['digest'] or review['forecast_digest']!=base['digest']:raise ValueError('Baseline provenance invalid')
        if not scenario.aware(base['created_at'])<=scenario.aware(receipt['checked_at'])<scenario.aware(base['deadline_at']):raise ValueError('Baseline late receipt')
        if pair['input_original_digest']!=base['snapshot_digest']:raise ValueError('Source digest mismatch')
        if review.get('status')!='graded' or len(review.get('winning_combinations',[]))!=1:continue
        actual=review['winning_combinations'][0]
        # Reuse exact pre-race observations; the HTML envelope is omitted only
        # after its full original digest was matched to the frozen baseline.
        for v in ['A','B']:
            pred=model.predict(snap,fitted,v,mode='replay',now=snap['meta']['captured_at'])
            picks=[x['combination'] for x in pred['virtual_card']];hit=actual in picks
            row={'race_id':pair['race_id'],'日付':pair['race_id'][:8],'改良版':v,'既存的中':int(review['hit']),'改良的中':int(hit),
                '既存買い目':','.join(x['combination'] for x in base['virtual_card']),'改良買い目':','.join(picks),'実出目':actual,'1着予測正解':int(pred['primary_prediction'][0]==actual[0]),
                '区分':'既存は締切前原本・改良は同入力の後付け再計算','既存原本digest':base['digest'],'入力原本digest':pair['input_original_digest'],'モデルdigest':fitted['digest'],
                'ROI':None,'損益':'オッズ原本/事故詳細不足・判定不能','ユーザー考察':''}
            out.append(row);logs.append({'baseline_reference':{'state_sha':pair['source_state_sha'],'forecast_digest':base['digest'],'input_digest':pair['input_original_digest']},'research_replay':pred,'actual_trifecta':actual,'original_is_prospective':True,'new_model_is_prospective':False,'actual_attack_origin_verified':False,'user_comment':''})
    return out,logs

def main():
    p=argparse.ArgumentParser();p.add_argument('--study',required=True);p.add_argument('--pairs',required=True);a=p.parse_args();root=Path(a.study)
    records=json.loads((root/'audited_races.json').read_text());fitted=model.fit(records)
    if (root/'model.json').exists():
        old=json.loads((root/'model.json').read_text());model.check_model(old)
        comparable=lambda m:{k:v for k,v in m.items() if k not in {'digest','fitted_at'}}
        if comparable(old)!=comparable(fitted):raise ValueError('Model changed; use a new evaluation output directory')
        fitted=old
    hist=evaluate_history(records,fitted)
    paired,logs=replay(json.loads(Path(a.pairs).read_text()),fitted)
    metrics=[]
    for split in ['検証','最終評価']:
        rows=[r for r in hist if r['区分']==split];n=len(rows);k=sum(r['的中'] for r in rows);lo,hi=wilson(k,n)
        metrics.append({'区分':split,'モデル':'A・枠なり仮定の後付け研究','標本数':n,'的中数':k,'的中率':k/n if n else None,'95下限':lo,'95上限':hi,'ROI':None,'既存との改善判定':'比較用事前特徴量不足・判定不能'})
    summary={'historical':metrics,'paired':{v:paired_uncertainty([r for r in paired if r['改良版']==v]) for v in ['A','B']},
        'prospective_research_races':0,'initial_diagnosis_target':100,'interim_target':300,
        'C':'未実装の係数投入は禁止。検証済み水面・選手係数がないため停止',
        'phase1':'未完了。7日95%・新ゆうき完全保存・浜名湖を独立追跡',
        'final_holdout_policy':'10月1〜17日は現時点の事前登録規則で一度評価。今後の規則変更は新しい未来評価が必要'}
    for name,obj in [('model',fitted),('validation_summary',summary)]:put(root/(name+'.json'),json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2).encode())
    # Per-race logs keep file sizes bounded for review and resumability.
    for log in logs:
        pred=log['research_replay'];key=pred['meta']['race_id']+'_'+pred['variant']
        put(root/'replays'/(key+'.json'),json.dumps(log,ensure_ascii=False,sort_keys=True,indent=2).encode())
    writecsv(root/'historical_validation.csv',hist);writecsv(root/'paired_comparison.csv',paired)
    print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
