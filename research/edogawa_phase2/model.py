"""A/B research candidates, fixed ten tickets; C stays disabled pending evidence.

Training uses official, normal races through 2026-06-30 only. Actual winner
method is a training label, never a prediction input. Two-stage B marginalizes
possible winner/method and ranks followers. Attack origins reuse v2 hypotheses;
no claim that K result labels identify a losing boat's actual attack.
"""
from collections import Counter, defaultdict
from itertools import permutations
from datetime import datetime
from research.scenario_v2 import engine as scenario

VERSION='edogawa-phase2-ab-v0.1-unvalidated'
TRAIN_END='2026-06-30'
COMBOS=list(permutations(range(1,7),3))

def fit(records):
    train=[r for r in records if r['date']<=TRAIN_END and r['normal_eligible'] and r['official_verified']]
    if not train: raise ValueError('No officially reconciled normal training races')
    joint=Counter();hm=Counter();followers=defaultdict(Counter)
    for r in train:
        byfinish={b['finish']:b['course'] for b in r['boats']}
        triple=tuple(byfinish[i] for i in (1,2,3));h,b,c=triple;m=r['method']
        joint[triple]+=1;hm[h,m]+=1;followers[h,m][b,c]+=1
    model={'version':VERSION,'training_end':TRAIN_END,'training_n':len(train),
        'fitted_at':datetime.now(scenario.JST).isoformat(),
        'data_available_at':max((r.get('observed_at','') for r in train),default=''),
        'joint':{'-'.join(map(str,k)):v for k,v in joint.items()},
        'head_method':[{'course':h,'method':m,'n':n,'followers':{'-'.join(map(str,k)):v for k,v in followers[h,m].items()}} for (h,m),n in sorted(hm.items())],
        'training_race_ids':[r['race_id'] for r in train],
        'training_digest':scenario.digest(train),'adoption_status':'research_only_unvalidated',
        'C_status':'blocked_no_time_validated_surface_or_player_coefficients',
        'hyperparameters':{'joint_pseudocount':1,'follower_backoff_races':20},
        'data_availability':'historical_results_acquired_after_racing; retrospective_training_not_asof_deployment'}
    model['digest']=scenario.digest(model);return model

def check_model(model):
    scenario.verify(model)
    if model['training_end']!=TRAIN_END:raise ValueError('Unexpected training cutoff')
    if any(k[:8]>'20260630' for k in model['training_race_ids']):raise ValueError('Training leakage')

def course_scores(model,variant):
    check_model(model)
    if variant not in ['A','B']:raise ValueError('C disabled until independent holdout validation')
    n=model['training_n'];joint=model['joint'];scores={}
    if variant=='A':
        return {t:(joint.get('-'.join(map(str,t)),0)+1)/(n+120) for t in COMBOS}
    for t in COMBOS:
        h,b,c=t;total=0
        htotal=sum(row['n'] for row in model['head_method'] if row['course']==h)
        back=(joint.get('-'.join(map(str,t)),0)+1)/(htotal+20)
        for row in model['head_method']:
            if row['course']!=h:continue
            # Unseen followers back off to head-only course distribution.
            p_method_head=row['n']/n
            follow=(row['followers'].get(f'{b}-{c}',0)+20*back)/(row['n']+20)
            total+=p_method_head*follow
        scores[t]=total
    return scores

def predict(snapshot,model,variant,*,mode,now,code_sha=None):
    if str(snapshot['meta']['jcd']).zfill(2)!='03':raise ValueError('Edogawa only')
    scenario.reject_outcomes(snapshot)
    def reject_labels(obj):
        if isinstance(obj,dict):
            for k,v in obj.items():
                if k in {'method','trifecta','first','second','third','winning_combinations','official_trifectas'}:raise ValueError('Outcome label forbidden: '+k)
                reject_labels(v)
        elif isinstance(obj,list):
            for v in obj:reject_labels(v)
    reject_labels(snapshot)
    check_model(model)
    if mode=='live':
        for stamp in [model['fitted_at'],model.get('data_available_at')]:
            if stamp and scenario.aware(stamp)>scenario.aware(now):raise ValueError('Future model or training evidence')
    if scenario.aware(snapshot['meta']['captured_at']).date().isoformat()<=TRAIN_END:
        raise ValueError('Prediction source must be after training cutoff')
    base=scenario.generate(snapshot,mode=mode,now=now)
    bycourse={b['course']:b['lane'] for b in snapshot['boats']}
    scores=course_scores(model,variant);support={};branches=[]
    for row in base['lanes']:
        for h in row['hypotheses']:
            # Structural evidence is an ordering policy, not a learned likelihood.
            branches.append({'winner_lane':row['lane'],**h})
            for f in h['formations']:
                support.setdefault(f['combination'],[]).append(h)
    ranked=[]
    for courses,score in scores.items():
        combo='-'.join(str(bycourse[c]) for c in courses)
        hs=support.get(combo,[])
        structural=max((h['supported_observations'] for h in hs),default=0)
        ranked.append({'combination':combo,'historical_score':score,
            'supported_observations':structural,'hypothesis_ids':[h['id'] for h in hs]})
    ranked.sort(key=lambda r:(-r['supported_observations'] if variant=='B' else 0,-r['historical_score'],r['combination']))
    # Scenario primary is an explicit forecast, retained separately from broad coverage.
    chosen=ranked[:10];first=chosen[0]['combination'];heads=int(first[0])
    branches.sort(key=lambda h:(h['winner_lane']!=heads,-h['supported_observations'],h['id']))
    primary=branches[0] if branches else None
    result={'version':VERSION,'variant':variant,'research_only':True,
        'status':'prospective_uncheckpointed' if mode=='live' else 'retrospective_replay',
        'meta':base['meta'],'generated_at':base['generated_at'],'input_digest':scenario.digest(snapshot),
        'model_digest':model['digest'],'training_end':model['training_end'],
        'code_sha':code_sha,'lanes':base['lanes'],'virtual_card':chosen,'unit_yen':100,'stake_yen':1000,
        'primary_prediction':first,'primary_scenario':primary,
        'not_selected':ranked[10:],'C_status':model['C_status'],
        'selection_reason':'A:公式学習期間のコース3連単分布。B:事前根拠を持つ展開仮説を優先し、想定決まり手と連動順位を周辺化した歴史分布で順位付け',
        'limitations':['未校正の研究順位・確率/EVではない','本番ST・本番進入・決まり手の事前入力禁止','風・波・潮・選手適性の未検証係数は不採用','実際の攻め起点は映像未確認なら判定不能','事後再計算は締切前実予想として集計しない']}
    result['digest']=scenario.digest(result);return result

def evaluate(record,result,*,video_annotation=None):
    scenario.verify(record)
    if result['race_id']!=record['meta']['race_id']:raise ValueError('Wrong result race')
    if scenario.aware(result['observed_at'])<scenario.aware(record['meta']['deadline_at']):raise ValueError('Result observed before deadline')
    actual=result.get('trifecta');picks=[r['combination'] for r in record['virtual_card']]
    if actual not in scenario.COMBINATIONS:raise ValueError('Result trifecta unavailable')
    a=actual.split('-');primary=record['primary_prediction'].split('-')
    hit=actual in picks;pay=result.get('payout_per_100');normal=result.get('normal_verified') is True
    refund=result.get('refund_lanes')
    # Payout alone does not establish all accident/refund flags or historical odds.
    money_ok=normal and refund==[] and isinstance(pay,int) and pay>0
    returned=pay if hit else 0
    financial_reason=None if money_ok else '払戻・通常成立・返還の公式確認不足'
    odds_ok=money_ok and bool(result.get('odds_snapshot'))
    r={'race_id':result['race_id'],'variant':record['variant'],'forecast_digest':record['digest'],
        'evaluation_kind':'prospective_receipt_required' if record['status']=='prospective_uncheckpointed' else '後付け研究',
        'primary_first_correct':a[0]==primary[0],'primary_second_correct':a[1]==primary[1],'primary_third_correct':a[2]==primary[2],
        'selected_head_covered':any(c[0]==a[0] for c in picks),'selected_second_covered':any(c.split('-')[:2]==a[:2] for c in picks),
        'hit':hit,'stake_yen':1000,'return_yen':returned if money_ok else None,
        'roi':returned/1000 if odds_ok else None,'torigami':hit and returned<1000 if odds_ok else None,
        'financial_unavailable_reason':financial_reason or ('オッズ原本なし・依頼条件によりROI/トリガミ率は判定不能' if not odds_ok else None),
        'winning_method_correct':record['primary_scenario']['tactic']==result['method'] if result.get('method') and record.get('primary_scenario') else None,
        'attack_origin_correct':None,'prediction_error':[], 'ticket_loss_reason':[],'actual_tactics_verified':False,
        'user_comment':'','actual_trifecta':actual,'actual_method':result.get('method')}
    if not r['primary_first_correct']:r['prediction_error'].append('1着艇の予測ミス')
    if not r['primary_second_correct'] or not r['primary_third_correct']:r['prediction_error'].append('2着・3着の連動予測ミス')
    if r['winning_method_correct'] is False:r['prediction_error'].append('想定決まり手の違い')
    r['prediction_error'].append('攻め方・旋回経路は映像未確認で判定不能')
    if not hit:r['ticket_loss_reason'].append('買い目に含まなかった')
    if r['torigami']:r['ticket_loss_reason'].append('トリガミ')
    if not normal:r['ticket_loss_reason'].append('事故・返還等の詳細未確認')
    if video_annotation:
        if not video_annotation.get('source_url') or not video_annotation.get('reviewed_at'):raise ValueError('Video evidence identity required')
        lane=video_annotation.get('attack_origin_lane')
        if lane in range(1,7):
            r['attack_origin_correct']=lane==record['primary_scenario']['attack_origin_lane'];r['actual_tactics_verified']=True
    r['digest']=scenario.digest(r);return r
