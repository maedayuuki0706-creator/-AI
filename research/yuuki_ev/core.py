"""Immutable forecast snapshots, missing-data gates and flat-stake EV analysis.

All experimental coefficients below are preregistered hypotheses, not fitted or
calibrated probabilities. No after-race input is used by a prediction function.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import permutations
import hashlib
import json
import math
import statistics

JST = timezone(timedelta(hours=9))
VERSION = 'yuuki-ev-shadow-v1.0.0'
MODELS = {'A': 'A_現行PT2', 'B': 'B_展開連動', 'C': 'C_ST安定性',
          'D': 'D_モーター推移', 'E': 'E_風潮位', 'F': 'F_統合研究'}
THRESHOLDS = (1.05, 1.2, 1.4, 1.6, 1.8, 2.0)
COMBINATIONS = tuple('-'.join(map(str, p)) for p in permutations(range(1, 7), 3))

def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def digest(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()

def aware(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return d if d.tzinfo else None
    except (ValueError, TypeError):
        return None

def deadline(source):
    try:
        return datetime.strptime(source['day'] + ' ' + source['deadline'], '%Y%m%d %H:%M').replace(tzinfo=JST)
    except (ValueError, KeyError, TypeError):
        return None

def number(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None

def ev(probability, odds):
    p, o = number(probability), number(odds)
    return p * o if p is not None and 0 <= p <= 1 and o is not None and o > 0 else None

def source_distribution(model):
    rows = {r.get('combination'): r for r in model.get('trifecta', [])}
    missing = []
    if set(rows) != set(COMBINATIONS) or len(model.get('trifecta', [])) != 120:
        missing.append('3連単120通りの確率')
    probs = {c: number(rows.get(c, {}).get('probability')) for c in COMBINATIONS}
    if any(p is None or not 0 <= p <= 1 for p in probs.values()):
        missing.append('有効な予測確率')
    elif abs(sum(probs.values()) - 1) > 0.001:
        missing.append('確率総和1の検証')
    odds = {c: number(rows.get(c, {}).get('odds')) for c in COMBINATIONS}
    if any(o is None or o <= 0 for o in odds.values()):
        missing.append('予測原本の全オッズ')
    return probs, odds, missing

def tilt_distribution(base, factors):
    weighted = {}
    for c, p in base.items():
        lanes = c.split('-')
        weighted[c] = p * math.exp(sum(factors.get(lane, 0) * w for lane, w in zip(lanes, (1, .5, .25))))
    total = sum(weighted.values())
    return {c: p / total for c, p in weighted.items()}

def six_scenarios(model, source, features=None):
    """Explicitly conditional hypotheses; never invent observed ST/foot facts."""
    features = features or {}
    factors = model.get('database', {}).get('lane_factors', {})
    shape = source.get('models', {}).get('prototype1', {}).get('race_shape', {})
    attack = shape.get('best_attack_lane')
    heads = model.get('heads', {})
    out = []
    for lane in range(1, 7):
        observed = factors.get(str(lane), {})
        f = features.get('boats', {}).get(str(lane), {})
        course = f.get('predicted_course')
        win = ('先マイし出口で押す。内側の壁が外の攻めを止める。' if lane == 1 else
               '内艇の旋回で生じる差し場を使う。' if lane == 2 else
               '内側の壁を越える攻め、または攻め艇の後にできる差し場を使う。')
        lose = ('内の差し場を許す、外の攻めが届く、出口の押しが再現しない。' if lane == 1 else
                '差し場が閉じる、内艇の壁が崩れない、外艇に先行される。')
        out.append({'lane': lane, 'predicted_course': course, 'head_probability': heads.get(str(lane)),
                    'win_path': win, 'conditions': 'ST隊形・足・進入がこの展開と一致すること。映像による検証は別途必要。',
                    'lose_path': lose, 'evidence': {'database_signals': observed.get('signals', []),
                                                   'racer_id': observed.get('racer_id'), 'motor_number': observed.get('motor_number'),
                                                   'observed_features': f, 'source_attack_lane': attack},
                    'evidence_status': '条件付き研究仮説／実際に成立した原因は未検証',
                    'non_axis_reason': '確率順位・他艇との比較。0%や勝てないという意味ではない。',
                    'missing': ['旋回映像', '勝ち筋成立の直接ラベル', '予測時点の記録がない足・潮位']})
    return out

def build_snapshots(source, source_sha, observed_at, *, replay=False, features=None):
    """Freeze all variants at one instant. Unavailable variants are records too."""
    base = source.get('models', {}).get('prototype2')
    if base is None:
        base = source.get('model', {})
        source_ai = '既存ゆうき'
    else:
        source_ai = 'PT2'
    close, created, observed = deadline(source), aware(source.get('created_at')), aware(observed_at)
    pre = close and created and observed and created <= observed < close
    cohort = '過去再計算' if replay or not pre else '締切前固定'
    p, odds, missing = source_distribution(base)
    features = features or {}
    feat_at = aware(features.get('observed_at'))
    if features and (not pre or not feat_at or feat_at > observed or feat_at >= close):
        features = {}  # Later official weather/exhibition cannot enter a forecast.
    scenarios = six_scenarios(base, source, features)
    distributions = {'A': p}
    gates = {'A': list(missing)}
    plan_missing = {}
    shape = source.get('models', {}).get('prototype1', {}).get('race_shape', {})
    attack = shape.get('best_attack_lane')
    if attack in range(1, 7) and not missing:
        weighted = {}
        for c, prob in p.items():
            i, j, k = map(int, c.split('-'))
            # Conditional 2nd/3rd coupling is an explicit, uncalibrated hypothesis.
            coupling = .12 if i == attack and j > i else -.04 if i == attack and j == 1 else 0
            coupling += .04 if i == attack and k > i else 0
            weighted[c] = prob * math.exp(coupling)
        z = sum(weighted.values()); distributions['B'] = {c: v/z for c,v in weighted.items()}
        gates['B'] = []
    else:
        gates['B'] = list(missing) + ['事前原本の攻め艇・展開ラベル']
    boats = features.get('boats', {})
    cf = {}
    for lane in map(str, range(1,7)):
        b = boats.get(lane, {})
        avg, ex = number(b.get('avg_st')), number(b.get('exhibition_st'))
        history = b.get('prior_actual_st', [])
        if avg is None or ex is None or len(history) < 5:
            break
        cf[lane] = 2*(.17-avg) + .4*(.15-max(0, ex)) - statistics.pstdev(history)
    gates['C'] = [] if len(cf)==6 and not missing else list(missing)+['6艇の平均ST・展示ST・過去本番ST5件以上（現レース本番STは禁止）']
    if not gates['C']: distributions['C'] = tilt_distribution(p, cf)
    df = {}
    for lane in map(str, range(1,7)):
        b = boats.get(lane, {})
        prev, current = number(b.get('prior_exhibition_time')), number(b.get('exhibition_time'))
        if prev is None or current is None or not b.get('same_motor_period') or not b.get('foot_observation'):
            break
        df[lane] = max(-.15,min(.15,(prev-current)*.3))
    gates['D'] = [] if len(df)==6 and not missing else list(missing)+['同一使用期間の前検・節間推移と出足／回り足／伸びの観測']
    if not gates['D']: distributions['D'] = tilt_distribution(p, df)
    environment = features.get('environment', {})
    ef = features.get('preregistered_environment_factors', {})
    env_required = ('wind_speed','wind_direction','wave_cm','tide_level','tide_trend','tide_station','tide_observed_at')
    gates['E'] = [] if (not missing and all(environment.get(k) is not None for k in env_required)
                         and set(ef)==set(map(str,range(1,7)))
                         and features.get('environment_training_end') and aware(features['environment_training_end'])
                         and aware(features['environment_training_end']) < observed) else list(missing)+['24場別の事前風向・風速・波・潮位・観測所・潮位方向・チルトと過去学習済み補正']
    if not gates['E']: distributions['E'] = tilt_distribution(p, ef)
    gates['F'] = sorted(set(x for letter in 'BCDE' for x in gates[letter]))
    if not gates['F']:
        joint = {c: math.prod(distributions[letter][c] for letter in 'BCDE')**.25 for c in COMBINATIONS}
        z = sum(joint.values()); distributions['F'] = {c:v/z for c,v in joint.items()}
    output = []
    for letter in MODELS:
        dist = distributions.get(letter)
        available = not gates[letter]
        # A_現行PT2 must never label the Yuuki model as PT2.
        if letter == 'A' and source_ai != 'PT2':
            gates[letter].append('PT2原本がない（ゆうき代用禁止）'); available=False
        tickets = [{'combination': c, 'probability': dist[c] if dist else None, 'odds': odds[c],
                    'ev': ev(dist[c],odds[c]) if dist else None,
                    'mark': '★EV1.4+' if dist and ev(dist[c],odds[c]) is not None and ev(dist[c],odds[c])>=1.4 else ''}
                   for c in COMBINATIONS]
        selected = [r['combination'] for r in sorted(tickets,key=lambda r:r['probability'] or 0,reverse=True)[:10]] if available else []
        record = {'id': source['key']+':'+letter+':'+VERSION, 'race_key': source['key'], 'day': source['day'],
                  'venue': source.get('venue',''), 'jcd': source['jcd'], 'rno':source['rno'],
                  'model': MODELS[letter], 'plan':letter, 'version':VERSION,
                  'source_ai':source_ai, 'source_model_version':base.get('model_version',base.get('selection_policy','未取得')),
                  'source_created_at':source.get('created_at'), 'generated_at':observed_at, 'deadline':close.isoformat() if close else None,
                  'cohort':cohort, 'availability':'記録可' if available else '未取得／標本不足',
                  'missing':gates[letter], 'source_sha':source_sha, 'source_digest':digest(source),
                  'odds_asof':source.get('created_at'), 'odds_timestamp_basis':'予想原本の保存時刻（独立のオッズ取得時刻は未取得）',
                  'main':list(dict.fromkeys(base.get('main_picks',[]))) if letter=='A' else selected[:6],
                  'cover':list(dict.fromkeys(base.get('cover_picks',[]))) if letter=='A' else selected[6:],
                  'box':base.get('box_picks',[]) if letter=='A' else [],
                  'picks':list(dict.fromkeys(base.get('picks',[]))) if letter=='A' else selected,
                  'heads':{str(l):sum(r['probability'] or 0 for r in tickets if r['combination'].startswith(str(l)+'-')) if dist else None for l in range(1,7)},
                  'scenarios':scenarios, 'features':features, 'tickets':tickets,
                  'calibration':'Aは原本の未校正値。B〜Fの係数は未検証の研究仮説。',
                  'comparison_policy':'同一固定時刻・同一レース。全モデル比較はA〜Fがすべて記録可の共通集合のみ。',
                  'training_end':features.get('environment_training_end'), 'training_status':'固定係数の仮説。学習済みと称さない。'}
        record['hash'] = digest(record)
        output.append(record)
    return output

def seal_live(record, persisted_at):
    """An actual pre-deadline persistence receipt is mandatory for live scoring."""
    receipt, close = aware(persisted_at), aware(record['deadline'])
    return {'id':record['id'], 'forecast_hash':record['hash'], 'persisted_at':persisted_at,
            'eligible_live':bool(record['cohort']=='締切前固定' and record['availability']=='記録可' and receipt and close and receipt < close)}

def evaluate(record, official, settled_at):
    if official.get('status') not in ('settled','void','special'):
        return None
    payouts, refunds = official.get('payouts',{}), set(official.get('refund_lanes',[]))
    winning = set(payouts)
    selected = set(record['picks'])
    hit = bool(winning & selected)
    reasons = []
    for combo in winning:
        if combo in selected:
            reasons.append('事前の採用買い目に確定3連単が含まれる。展開の因果は映像未確認。')
        elif any(c.split('-')[0]==combo.split('-')[0] for c in selected):
            reasons.append('勝ち艇の頭は採用したが、2・3着の組合せを採用していない。')
        else:
            reasons.append('確定した勝ち艇を頭とする買い目を採用していない。直接の展開原因は未確認。')
    return {'id':record['id'], 'forecast_hash':record['hash'], 'settled_at':settled_at,
            'official':official, 'hit':hit, 'review':reasons,
            'path_verified':'未検証：決まり手・STだけでは勝ち筋成立／事故因果は断定できない',
            'hypothesis':'次期評価期間で頭別2・3着の残り筋を比較。今回の原本は変更しない。'}

def payoff(ticket, official):
    combo = ticket['combination']
    if official['status']=='void' or set(map(int,combo.split('-'))) & set(official.get('refund_lanes',[])):
        return 0,0,False  # Refunded capital is excluded from ROI and loss streaks.
    if official['status']=='special':
        return 100,official.get('special_per_100') or 0,False
    pay = official.get('payouts',{}).get(combo,0)
    return 100,pay,bool(pay)

def summarize(pairs, threshold):
    events=[]; bets=hits=investment=returns=0; racehits=0; mid=big=midpay=bigpay=midcost=bigcost=0
    for forecast,result in pairs:
        selected=[t for t in forecast['tickets'] if t['ev'] is not None and t['ev']>=threshold]
        if not selected or forecast['availability']!='記録可':continue
        inv=ret=h=0; valid_bets=0
        official=result['official']
        for t in selected:
            cost,pay,won=payoff(t,official)
            if not cost:continue
            inv+=cost;ret+=pay;h+=int(won);valid_bets+=1
        if not inv:continue
        # Bucket contribution allocates the full strategy cost of that race,
        # never presents gross payout as net profit contribution.
        payout=max(official.get('payouts',{}).values(),default=0)
        if 2000<=payout<10000: mid+=h;midpay+=ret;midcost+=inv
        if payout>=10000: big+=h;bigpay+=ret;bigcost+=inv
        bets+=valid_bets;hits+=h;investment+=inv;returns+=ret;racehits+=int(h>0)
        events.append((forecast['deadline'],forecast['race_key'],ret-inv,h>0))
    grouped={}
    for close,key,profit,hit in events:
        old=grouped.get(key,(close,key,0,False))
        grouped[key]=(close,key,old[2]+profit,old[3] or hit)
    events=list(grouped.values())
    racehits=sum(event[3] for event in events)
    balance=peak=maxdd=streak=maxstreak=0
    for _,_,profit,hit in sorted(events):
        balance+=profit;peak=max(peak,balance);maxdd=max(maxdd,peak-balance)
        streak=0 if hit else streak+1;maxstreak=max(maxstreak,streak)
    return {'threshold':threshold,'races':len(events),'bets':bets,'hits':hits,'hit_rate':hits/bets if bets else None,
            'race_hits':racehits,'race_hit_rate':racehits/len(events) if events else None,
            'investment':investment,'payout':returns,'roi':returns/investment if investment else None,
            'profit':returns-investment,'max_loss_streak_races':maxstreak,'max_drawdown_yen':maxdd,
            'mid_hits':mid,'manshu_hits':big,'mid_gross_payout':midpay,'manshu_gross_payout':bigpay,
            'mid_net_contribution':midpay-midcost,'manshu_net_contribution':bigpay-bigcost,
            'needed_capital_yen':maxdd+max((sum(100 for t in f['tickets'] if t['ev'] is not None and t['ev']>=threshold) for f,r in pairs),default=0),
            'assessment':'標本不足／継続性未検証' if len(events)<100 else '期間内成績。将来のROI120%を保証しない。',
            'units':'券的中率とレース的中率を分離。全モデル合算は重複購入を含む研究ポートフォリオ。'}

def metrics(records, results, receipts):
    result_map={x['id']:x for x in results};receipt_map={x['id']:x for x in receipts}
    cohorts=defaultdict(list)
    all_models=defaultdict(set)
    for f in records:
        if f['availability']=='記録可':all_models[f['race_key']].add(f['plan'])
    for f in records:
        r=result_map.get(f['id'])
        if not r or r['forecast_hash']!=f['hash']:continue
        cohort=f['cohort']
        if cohort=='締切前固定' and not receipt_map.get(f['id'],{}).get('eligible_live'):continue
        cohorts[(cohort,f['model'],'総計')].append((f,r))
        cohorts[(cohort,f['model'],'日:'+f['day'])].append((f,r))
        cohorts[(cohort,f['model'],'場:'+f['venue'])].append((f,r))
        cohorts[(cohort,'全モデル','総計')].append((f,r))
        cohorts[(cohort,'全モデル','日:'+f['day'])].append((f,r))
        cohorts[(cohort,'全モデル','場:'+f['venue'])].append((f,r))
        if all_models[f['race_key']]==set(MODELS):
            cohorts[(cohort,f['model'],'全モデル共通')].append((f,r))
    return [dict(cohort=k[0],model=k[1],group=k[2],**summarize(v,t)) for k,v in sorted(cohorts.items()) for t in THRESHOLDS]

def write_once(path, value):
    """Exclusive create; a changed source never silently rewrites a forecast."""
    from pathlib import Path
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    try:
        with p.open('x',encoding='utf-8') as f:f.write(dumps(value)+'\n')
        return True
    except FileExistsError:
        old=json.loads(p.read_text())
        if old!=value:
            return False
        return False
