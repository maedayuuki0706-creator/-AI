"""Ablation diagnostics. Replays never count as pre-deadline research forecasts."""
import argparse,json
from pathlib import Path
from . import model
from .collect import VENUES
from .settle import settle
from research.edogawa_phase2.acquire import put
from research.edogawa_phase2.study import wilson,writecsv
from research.edogawa_phase2.validate import evaluate_history,paired_uncertainty
from research.scenario_v2 import engine as scenario

def replay(pair,fitted,cache=None,code_sha=None):
    snap,base,review,receipt=[pair[k] for k in ['inputs','forecasts','reviews','receipts']]
    if receipt.get('status')!='confirmed_before_deadline' or receipt.get('digest')!=base['digest'] or review.get('forecast_digest')!=base['digest']:raise ValueError('Original identity/receipt invalid')
    if not scenario.aware(base['created_at'])<=scenario.aware(receipt['checked_at'])<scenario.aware(base['deadline_at']):raise ValueError('Original receipt late')
    if pair['input_original_digest']!=base['snapshot_digest']:raise ValueError('Original input mismatch')
    refundable=review.get('status')=='excluded' and bool(review.get('refund_lanes'))
    if (review.get('status')!='graded' and not refundable) or len(review.get('winning_combinations',[]))!=1:return [],[]
    actual=review['winning_combinations'][0];a=actual.split('-');out=[];logs=[]
    for v in ['A','B']:
        existing=Path(cache)/(pair['race_id']+'_'+v+'.json') if cache else None
        if existing and existing.exists():
            pred=json.loads(existing.read_text())['research_replay'];scenario.verify(pred)
            if pred['model_digest']!=fitted['digest'] or pred['input_digest']!=scenario.digest(snap) or pred['code_sha']!=code_sha:raise ValueError('Changed replay identity; new study output required')
        else:pred=model.predict(snap,fitted,v,mode='replay',now=snap['meta']['captured_at'],code_sha=code_sha)
        picks=[r['combination'] for r in pred['virtual_card']];primary=pred['primary_prediction'].split('-')
        cohort='返還確認' if refundable else '返還なし・全6艇未照合'
        baseline_picks=[r['combination'] for r in base['virtual_card']]
        baseline_settle=settle(baseline_picks,review.get('official_trifectas'),review.get('refund_lanes'))
        improved_settle=settle(picks,review.get('official_trifectas'),review.get('refund_lanes'))
        row={'場':fitted['venue'],'場コード':fitted['venue_code'],'race_id':pair['race_id'],'日付':pair['race_id'][:8],
             '集計群':cohort,'改良版':v,'既存的中':int(actual in baseline_picks),'改良的中':int(actual in picks),
             '1着予測正解':int(primary[0]==a[0]),'2着予測正解':int(primary[1]==a[1]),'3着予測正解':int(primary[2]==a[2]),
             '既存買い目':','.join(r['combination'] for r in base['virtual_card']),'改良買い目':','.join(picks),'実出目':actual,
             '仮想投資円':1000,'ROI':None,'トリガミ':None,'攻め起点一致':None,'想定決まり手一致':None,
             '既存払戻返還円':baseline_settle['return_yen'],'改良払戻返還円':improved_settle['return_yen'],'既存返還円':baseline_settle['refund_yen'],'改良返還円':improved_settle['refund_yen'],
             '区分':'既存締切前原本と改良の同入力・後付け研究','ユーザー考察':'','映像URL':'','再検証日':''}
        out.append(row)
        formation_candidates={x['combination'] for b in pred['lanes'] for h in b['hypotheses'] for x in h['formations']}
        ticket_reason=[]
        if actual not in picks:ticket_reason.append('展開形成候補にあったが固定10点から外れた' if actual in formation_candidates else '展開形成候補と固定10点の双方に含まれなかった')
        logs.append({'baseline_reference':{'source_state_sha':pair['source_state_sha'],'forecast_digest':base['digest'],'input_digest':pair['input_original_digest']},
                     'research_replay':pred,'actual_trifecta':actual,'actual_attack_origin_verified':False,
                     'prediction_error':['1着艇の予測ミス']*(primary[0]!=a[0])+['2着・3着候補の評価ミス']*(primary[1:]!=a[1:])+['攻め方・旋回経路は映像未確認で判定不能'],
                     'ticket_loss_reason':ticket_reason,'cause_status':'着順との不一致を記録。実戦の戦術原因は未確定',
                     'normal_cohort':cohort,'baseline_settlement':baseline_settle,'improved_settlement':improved_settle,'roi':None,'torigami':None,
                     'original_is_prospective':True,'new_model_is_prospective':False,'user_comment':''})
    return out,logs

def run(study,pairs,code_sha):
    if len(code_sha)!=40:raise ValueError('Full published research code SHA required')
    root=Path(study);records=json.loads((root/'audited_races.json').read_text());pairs=json.loads(Path(pairs).read_text())
    hist=[];paired=[];metrics=[];models={};pending=[]
    for jcd,name in VENUES.items():
        rs=[r for r in records if r['venue_code']==jcd];fitted=model.fit(rs,jcd)
        path=root/jcd/'model.json'
        if path.exists():
            old=json.loads(path.read_text());model.check_model(old)
            same=lambda m:{k:v for k,v in m.items() if k not in {'digest','fitted_at'}}
            if same(old)!=same(fitted):raise ValueError('Changed model: new study required')
            fitted=old
        models[jcd]=fitted;put(path,json.dumps(fitted,ensure_ascii=False,sort_keys=True,indent=2).encode())
        rows=evaluate_history(rs,fitted)
        rows=[{'場':name,'場コード':jcd,**r} for r in rows];hist.extend(rows)
        for period in ['検証','最終評価']:
            sub=[r for r in rows if r['区分']==period];n=len(sub);k=sum(r['的中'] for r in sub);lo,hi=wilson(k,n)
            metrics.append({'場':name,'区分':period,'モデル':'A・枠なり仮定の後付け','標本数':n,'的中数':k,'的中率':k/n if n else None,'95下限':lo,'95上限':hi,
                            '1着予測的中率':sum(r['1着本命正解'] for r in sub)/n if n else None,
                            '2着予測的中率':sum(r['2着本命正解'] for r in sub)/n if n else None,
                            '3着予測的中率':sum(r['3着本命正解'] for r in sub)/n if n else None,
                            'ROI':None,'トリガミ率':None,'改善判定':'既存同条件の過去事前原本なし。改善判定不能'})
        for pair in pairs:
            if pair['race_id'].split('_')[1]!=jcd:continue
            if pair.get('errors') or not all(k in pair for k in ['inputs','forecasts','reviews','receipts']):
                pending.append({'race_id':pair['race_id'],'reason':'既存原本/照合/受領の不足','errors':pair.get('errors')});continue
            out,logs=replay(pair,fitted,root/'replays',code_sha);paired.extend(out)
            if not logs:pending.append({'race_id':pair['race_id'],'reason':'既存結果が未確定/除外。通常成績に補完しない'})
            for log in logs:
                pred=log['research_replay'];put(root/'replays'/(pair['race_id']+'_'+pred['variant']+'.json'),json.dumps(log,ensure_ascii=False,sort_keys=True).encode())
    comparison=[]
    for jcd,name in VENUES.items():
        for v in ['A','B']:
            rows=[r for r in paired if r['場コード']==jcd and r['改良版']==v and r['集計群']!='返還確認'];n=len(rows)
            comparison.append({'場':name,'改良版':v,'同入力比較R':n,'既存的中数':sum(r['既存的中'] for r in rows),'改良的中数':sum(r['改良的中'] for r in rows),
                '既存的中率':sum(r['既存的中'] for r in rows)/n if n else None,'改良的中率':sum(r['改良的中'] for r in rows)/n if n else None,
                **paired_uncertainty(rows),'実測締切前研究R':0,'ROI':None,'注意':'改良は後付け再計算。事前特徴量は原本からのみ。期間/標本不足'})
    ablation=[]
    for jcd,name in VENUES.items():
        byid={r['race_id']:r for r in paired if r['場コード']==jcd and r['改良版']=='A' and r['集計群']!='返還確認'}
        changes=[{'日付':r['日付'],'既存的中':byid[r['race_id']]['改良的中'],'改良的中':r['改良的中']} for r in paired if r['場コード']==jcd and r['改良版']=='B' and r['race_id'] in byid]
        ablation.append({'場':name,'比較':'BからAを引いた差',**paired_uncertainty(changes)})
    summary={'historical':metrics,'comparison':comparison,'B_vs_A':ablation,'refund_comparison':[r for r in paired if r['集計群']=='返還確認'],'pending_pairs':pending,'prospective_research_races':0,
        'C':'検証済み水面/選手/モーター係数なし・停止',
        'holdout_limit':'全期間の記述集計を既に閲覧したため最終評価は診断。将来の未観測期間で再評価が必要',
        'history_limit':'過去事前原本なし。Aのみ艇番=予想コースの仮定。実進入・ST・当該決まり手を予想入力に使わない。B/C/既存の長期比較は不能',
        'financial_limit':'過去オッズ原本がないためROI/トリガミ率は算出しない。事故/返還を通常と分ける',
        'phase1_complete':False,'initial_target':100,'interim_target':300}
    put(root/'validation_summary.json',json.dumps(summary,ensure_ascii=False,sort_keys=True,indent=2).encode())
    writecsv(root/'historical_validation.csv',hist);writecsv(root/'paired_comparison.csv',paired)
    writecsv(root/'comparison_summary.csv',comparison)
    print(json.dumps(summary,ensure_ascii=False),flush=True);return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--study',required=True);p.add_argument('--pairs',required=True);p.add_argument('--code-sha',required=True);a=p.parse_args();run(a.study,a.pairs,a.code_sha)
