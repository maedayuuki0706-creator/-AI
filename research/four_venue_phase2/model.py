"""Common six-boat engine with independent, official training for each venue.

Reuses the unchanged scenario_v2 engine and PR36 A/B probability tables.
Surface/player/motor observations remain hypotheses, never adopted coefficients.
"""
from datetime import datetime
from research.edogawa_phase2 import model as prior
from research.scenario_v2 import engine as scenario
from .collect import VENUES

VERSION='four-venue-phase2-ab-v0.1-unvalidated'
COMBOS=prior.COMBOS
SPECIALIZATION={j:{'venue':n,'validated_coefficients':[],
    'blocked':['潮位・流速の時空間対応','選手構成・季節の交絡','モーター使用期間・出足/伸びの観測']} for j,n in VENUES.items()}

def fit(records,jcd):
    if jcd not in VENUES:raise ValueError('Unsupported venue')
    rows=[r for r in records if r.get('venue_code',r['race_id'][8:10])==jcd]
    fitted=prior.fit(rows)
    fitted.update(version=VERSION,venue_code=jcd,venue=VENUES[jcd],specialization=SPECIALIZATION[jcd])
    fitted['digest']=scenario.digest({k:v for k,v in fitted.items() if k!='digest'})
    return fitted

def check_model(m):
    prior.check_model(m)
    if m.get('version')!=VERSION or m.get('venue_code') not in VENUES:raise ValueError('Wrong model identity')
    if any(x[8:10]!=m['venue_code'] for x in m['training_race_ids']):raise ValueError('Cross-venue model contamination')
    if m['specialization']['validated_coefficients']:raise ValueError('No validated C coefficients in this release')

def course_scores(m,variant):
    check_model(m);return prior.course_scores(m,variant)

def predict(snapshot,m,variant,*,mode,now,code_sha=None):
    check_model(m)
    if str(snapshot['meta']['jcd']).zfill(2)!=m['venue_code']:raise ValueError('Venue/model mismatch')
    if variant not in ['A','B']:raise ValueError('C blocked: no independent validated coefficients')
    scenario.reject_outcomes(snapshot)
    def reject(x):
        if isinstance(x,dict):
            for k,v in x.items():
                if k in {'method','trifecta','first','second','third','winning_combinations','official_trifectas'}:raise ValueError('Post-race label forbidden: '+k)
                reject(v)
        elif isinstance(x,list):
            for v in x:reject(v)
    reject(snapshot)
    if mode=='live' and any(s and scenario.aware(s)>scenario.aware(now) for s in [m['fitted_at'],m.get('data_available_at')]):raise ValueError('Future model/evidence')
    if scenario.aware(snapshot['meta']['captured_at']).date().isoformat()<=prior.TRAIN_END:raise ValueError('Input overlaps training')
    base=scenario.generate(snapshot,mode=mode,now=now);scores=course_scores(m,variant)
    bycourse={b['predicted_course']:b['lane'] for b in base['lanes']};support={};branches=[]
    for lane in base['lanes']:
        for h in lane['hypotheses']:
            branches.append(h)
            for f in h['formations']:support.setdefault(f['combination'],[]).append(h)
        course=lane['predicted_course'];heads=sum(r['n'] for r in m['head_method'] if r['course']==course)
        lane['relative_evidence']={'historical_course_wins':heads,'historical_training_n':m['training_n'],
            'historical_course_share':heads/m['training_n'],
            'supported_conditions_max':max((h['supported_observations'] for h in lane['hypotheses']),default=0),
            'interpretation':'歴史頻度と事前観測根拠を併記。現在レースの勝率として未校正'}
        lane['unlikely_or_uncertain_reason']='根拠の欠測は支持なしとして表示。薄い勝ち筋も削除しないが同じ強さには扱わない'
        lane['reversal_risk']='道中の出口加速・進路で逆転され得る。周回/映像ラベルがないため確率不明'
        lane['alternative_scenarios']=[h['loss_path']+'。他の攻め起点の分岐を再検討' for h in lane['hypotheses']]
    ranked=[]
    for courses,score in scores.items():
        combo='-'.join(str(bycourse[c]) for c in courses);hs=support.get(combo,[])
        ranked.append({'combination':combo,'historical_score':score,'supported_observations':max((h['supported_observations'] for h in hs),default=0),
                       'hypothesis_ids':[h['id'] for h in hs]})
    ranked.sort(key=lambda r:(-r['supported_observations'] if variant=='B' else 0,-r['historical_score'],r['combination']))
    chosen=ranked[:10];primary=chosen[0]['combination'];head=int(primary[0])
    branches.sort(key=lambda h:(h['winner_lane']!=head,-h['supported_observations'],h['id']))
    record={'version':VERSION,'venue_code':m['venue_code'],'variant':variant,'research_only':True,
        'status':'prospective_uncheckpointed' if mode=='live' else 'retrospective_replay',
        'meta':base['meta'],'generated_at':base['generated_at'],'input_digest':scenario.digest(snapshot),
        'model_digest':m['digest'],'training_end':m['training_end'],'code_sha':code_sha,
        'lanes':base['lanes'],'virtual_card':chosen,'unit_yen':100,'stake_yen':1000,
        'primary_prediction':primary,'primary_scenario':branches[0] if branches else None,
        'not_selected':[{**r,'reason':'固定10点に対し採用順位11位以下。A=場別コース分布、B=支持根拠優先後に連動統計'} for r in ranked[10:]],
        'C_status':m['C_status'],'specialization':m['specialization'],
        'selection_reason':'A=場別公式学習コース分布。B=事前根拠の攻め仮説・想定決まり手を周辺化して連動候補を順位付け。実際の決まり手は入力不可',
        'limitations':['攻め起点は仮説・勝者から実攻め艇を断定しない','Bの構造順位は未検証','風波潮・選手モーター補正は未採用','後付け再計算は締切前実測に含めない']}
    record['digest']=scenario.digest(record);return record

# Evaluation is identical across venues and always separate from prediction.
evaluate=prior.evaluate
