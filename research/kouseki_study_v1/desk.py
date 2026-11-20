"""Build an offline single-file analyst desk; raw files are opened read-only."""
import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from html import escape
from pathlib import Path
from statistics import mean, median, pstdev

from analytics import VENUES, as_day, is_six, recent, summarize
from analyst_context import pre_race_exhibition, rate, read_history, valid_number
from coverage_audit import coverage
from longitudinal import connect, scenarios, follower, similar, nearest, check_g1, evaluate_escape, discover
from relationships import study, start_study, motor_events
from lineup_store import target_record
from tide_study import tide
from official_profiles import racer_terms, program
from exhibition_study import columns, cohorts, audit_splits

def cell(x):
    return escape(str(x)) if x is not None else '未取得'

def table(headers, rows):
    rows=list(rows)
    if not rows:
        return '<p>該当する収録データは0件です。</p>'
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+cell(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+cell(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'

def fmt(r):
    if not r['n']: return '0件'
    return f"{r['count']}/{r['n']}（{r['pct']}%・95%区間 {r['wilson95_pct'][0]}–{r['wilson95_pct'][1]}%）"

def official_result(data, race):
    p=data/'official_results'/f"{race['day']}.json"
    item=day_results(p).get(f"{race['venue']}:{race['race_no']}",{})
    order='-'.join(str(b['lane']) for b in sorted(race['rows'],key=lambda b:b['finish'])[:3])
    payouts=item.get('payouts') or {}
    if item.get('status')!='settled' or not payouts: return '公式キャッシュ未確認', None
    return ('一致',payouts[order]) if order in payouts else ('不一致',None)

@lru_cache(maxsize=400)
def day_results(p):
    return json.loads(p.read_text()) if p.exists() else {}

def orig(data, target):
    day,venue,n=target['day'],target['jcd'],target['rno']
    folder=data/'venue24_v2'/'daily_source'
    p=folder/(day+'.csv')
    if not p.exists() or venue=='03': return [],[]
    with p.open(encoding='utf-8-sig') as f:
        matches=[r for r in csv.DictReader(f) if r['レースコード']==f'{day}{venue}{n:02}']
    if len(matches)!=1:return [],[]
    r=matches[0]
    metrics=columns(r,sorted(target['rows'],key=lambda b:b['lane']))
    return list(metrics),list(metrics.values())

def exhibit(names, cols):
    def td(i,col):
        v=col[i]
        rank=1+sum(a<v for a in col) if all(a is not None for a in col) else None
        return f'<td class="r{rank}">{cell(v)}</td>'
    return '<div class="scroll"><table><tr><th>艇番</th>'+''.join('<th>'+cell(n)+'</th>' for n in names)+'</tr>'+''.join('<tr><td>'+str(i+1)+'</td>'+''.join(td(i,col) for col in cols)+'</tr>' for i in range(6))+'</table></div>'

def player_list(players):
    profiles=[]
    for rid,rows in sorted(players.items()):
        if not rows:continue
        ss=summarize(rows)
        profiles.append((rid,rows[-1]['name'],len(rows),ss['first_pct'],ss['top3_pct'],ss['st_mean'],summarize(recent(rows))['top3_pct']))
    return profiles

def build(a):
    data=a.data
    path=data/'exhibition_log'/a.day/f'{a.venue}_{a.race:02}.json'
    t=target_record(data,a.day,a.venue,a.race); day=t['day']; code=t['jcd']
    if (day,code,t['rno'])!=(a.day,a.venue,a.race) or not is_six(t['rows']):raise ValueError('target identity mismatch')
    boats=sorted(t['rows'],key=lambda b:b['lane'])
    history,audit=read_history(data/'exhibition_log',day)
    players=defaultdict(list); local=[r for r in history if r['venue']==code]
    for r in history:
        sts=[b.get('actual_st') for b in r['rows']]
        for b in r['rows']:
            st=b.get('actual_st')
            players[str(b['racer_id'])].append(dict(day=r['day'],race=r['race_no'],venue=r['venue'],course=b['actual_course'],
                finish=b['finish'],lane=b['lane'],st=st if valid_number(st,0,.99) else None,tilt=b.get('tilt'),method=r['method'],
                st_rank=1+sum(s<st for s in sts) if all(valid_number(s,0,.99) for s in sts) else None,name=b['name']))
    db=connect(a.db); groups=scenarios(db,day)
    pages={}
    label=VENUES[int(code)-1]+f' {t["rno"]}R'
    cards=data/'race_cards'/f'{day}.json'
    manifest=json.loads(cards.read_text()) if cards.exists() else {}
    venues=Counter(str(v['jcd']).zfill(2) for v in manifest.get('races',{}).values())
    pages['ホーム・開催場']=f'<p>{cell(day)} 保存番組表　{cell(label)}のアーカイブ再分析</p>'+table(['開催場','予定R'],[(VENUES[int(v)-1],n) for v,n in sorted(venues.items())])
    course_ok=sorted([str(b.get('exhibition_course')) for b in boats])==list('123456')
    summary=[]; player_tables=[]
    for b in boats:
        rid=str(b['racer_id']);c=b.get('exhibition_course') if course_ok else b['lane']
        rows=players[rid]; sample=[r for r in rows if r['course']==c]; s=summarize(sample)
        summary.append((b['lane'],b['name'],rid,c,len(sample),s['first_pct'],s['top3_pct'],s['st_mean'],s['st_sd']))
        for window in (30,90,180,365):
            lo=(as_day(day)-timedelta(days=window)).strftime('%Y%m%d')
            group=[r for r in sample if r['day']>=lo]; ss=summarize(group)
            player_tables.append((b['name'],c,window,len(group),ss['first_pct'],ss['second_pct'],ss['third_pct'],fmt(rate(sum(x['finish']<=2 for x in group),len(group))),ss['st_mean']))
    pages['6艇比較']=f'<p>{cell(label)}　想定進入は'+('展示進入' if course_ok else '枠なり仮定')+'。対象日より前の収録済み完走歴を使用。</p>'+table(['艇','選手','登録','想定コース','走数','1着%','3連対%','本番平均ST','ST標準偏差'],summary)+table(['選手','コース','日数','走数','1着%','2着%','3着%','2連対','平均ST'],player_tables)
    profiles=player_list(players)
    pages['選手検索']='<label>氏名・登録番号 <input id="search" type="search"></label>'+table(['登録','選手','収録走','1着%','3連対%','平均ST','直近10走 3連対%'],profiles)
    cycles=json.loads((data/'motor_cycles.json').read_text())['cycles']
    motors=[]
    for b in boats:
        matches=[v for v in cycles if v['jcd']==code and v['start_date']<=day<=(v.get('end_date') or day)]
        sample=[x for r in local if len(matches)==1 and matches[0]['start_date']<=r['day'] for x in r['rows'] if b.get('motor_number') and x.get('motor_number')==b['motor_number']]
        motors.append((b['lane'],b.get('motor_number'),matches[0]['start_date'] if len(matches)==1 else None,len(sample),fmt(rate(sum(x['finish']<=2 for x in sample),len(sample))),len({x['racer_id'] for x in sample})))
    pages['モーター']=table(['艇','機番','使用開始','走数','2連対','使用選手数'],motors)+'<p>使用選手の実力補正前。周期資料のない場は機番集計を保留。</p>'
    ex=pre_race_exhibition(t);names,cols=orig(data,t)
    pages['展示比較']=exhibit(['公式展示']+names,[[b['exhibition_time'] for b in ex['boats']]]+cols)+'<p>各列で6艇の値が揃う場合に順位付け。同着は同順位。薄赤は1位、薄黄は2位。二次資料は事後取得。登録番号を含まない分割タイムはレースコード・艇番・氏名を照合。</p>'+('<p>オリジナル展示分割タイム未取得または照合不能。</p>' if not cols else '')
    pages['水面・風・潮']=table(['風速 m/s','波高 cm','潮向・変化量'],[(ex['wind_m'],ex['wave_cm'],None)])+table(['風速 m/s','完走R','実1コース1着','万舟'],[(v,n,fmt(rate(k,n)),fmt(rate(h,n))) for v,n,k,h in db.execute('SELECT wind_m,count(*),sum(e.course=1),sum(payout_yen>=10000) FROM race r JOIN entry e ON r.id=e.id AND rank=1 WHERE jcd=? AND day<? GROUP BY wind_m ORDER BY wind_m',(code,day))])
    scen=groups[code]
    pages['展開シミュレーション']='<p>成立した攻めを選ぶと、その条件で実際に残ったコースを比較できます。攻めが成立する確率は未推定。</p><label>攻めの起点 <select id="attacker">'+''.join(f'<option>{i}</option>' for i in range(1,7))+'</select></label><label>決まり手 <select id="method">'+''.join('<option>'+cell(m)+'</option>' for m in sorted({r['deciding_method'] for r in scen}))+'</select></label><div id="conditional"></div>'
    sim=similar(local,t)
    payout={(r['day'],r['race_no']):official_result(data,r)[1] for r in local}
    pages['類似レース']='<p>同場・枠順ごとの級別6人一致。6艇の展示順位の絶対差を平均し、距離の小さい順。事後保存データでの探索。</p>'+table(['距離','日付','R','決まり手','確定組','払戻円'],[(*r,payout[r[1],r[2]]) for r in sim])
    venue_rows=[]
    for v in range(1,25):
        rr=groups[f'{v:02}']; n=sum(x['n'] for x in rr)
        venue_rows.append((VENUES[v-1],n,fmt(rate(sum(x['n'] for x in rr if x['attacker']==1 and x['deciding_method']=='逃げ'),n)),fmt(follower(rr,1,True))))
    pages['全国24場']=table(['場','長期完走R','実1コース逃げ','2025年 4まくり時の5コース2着'],venue_rows)
    windows=[]
    for v in [code,'全国']:
        rr=scen if v==code else [r for vs in groups.values() for r in vs]
        for h in (0,1):
            windows.append((VENUES[int(code)-1] if v==code else v,'2025検証' if h else '2022–24探索',fmt(follower(rr,h,True)),fmt(follower(rr,h,False))))
    pages['傾向の再検証']='<p>検証仮説　実4コースのまくり勝ちでは、同じ4コースが他の決まり手で勝ったときより、実5コースが2着に入りやすいか。各群にWilson 95%区間を表示。選手構成・同一開催内の相関は未調整。</p>'+table(['対象','期間','まくり','他の決まり手'],windows)
    cv=coverage(data/'race_cards',data/'exhibition_log',a.audit_start,a.audit_end)
    pages['収録・欠損']=f'<p>{cell(a.audit_start)}〜{cell(a.audit_end)}　番組表不明 {cv["totals"].get("unknown_manifest_days",0)}日。分母は保存した完全番組表の予定数。</p>'+table(['場','予定','ファイルあり','未収録','正常完走','未確定','異常・不完全','無効'],[(v['name'],v.get('expected',0),v.get('expected',0)-v.get('missing_archive',0),v.get('missing_archive',0),v.get('normal_result',0),v.get('unsettled_or_unverified',0),v.get('abnormal_or_incomplete_result',0),v.get('invalid_archive',0)) for v in cv['all_24_venues']])+''.join('<details><summary>'+cell(d['day'])+'</summary>'+table(['場','R','状態','欠損項目・艇番'],[(r['venue'],r['race_no'],r['status'],json.dumps(r['issues'],ensure_ascii=False)) for r in d.get('races',[]) if r['issues'] or r['status']!='normal_result'])+'</details>' for d in cv['days'])
    g=check_g1(db,a.g1,day)
    checks=Counter(official_result(data,r)[0] for r in history)
    pages['精度・出典']=table(['2026年完走着順 × 保存公式3連単','件数'],sorted(checks.items()))+table(['常滑G1','収録R','1号艇1着','万舟','長期DB照合一致','不一致','照合対象外'],[(k,len(rs),sum(x[1]==1 for x in rs),sum(isinstance(x[2],int) and x[2]>=10000 for x in rs),sum(x[4] is True for x in rs),sum(x[4] is False for x in rs),sum(x[4] is None for x in rs)) for k,rs in g.items()])+table(['資料','対象期間・取得記録'],[('公式K成績（6艇完走）',str(tuple(db.execute('select min(day),max(day),count(*) from race where day<?',(day,)).fetchone()))),('出走・展示保存',path.name+' / '+str(t.get('captured_at'))),('分析対象履歴',str(audit)),('原本の締切前固定','未確認。リプレイ専用'),('未取得・未検証','潮位、事故理由の全件分類、2021年結果の公式全件照合、個別レース確率の校正、実機Safari、級別/節区分補正'),('生成日時 UTC',datetime.now(timezone.utc).isoformat())])
    roles,starts,motor_rows=study(history,t,cycles)
    role_view=[];st_view=[];motor_view=[]
    for b in boats:
        c=b['exhibition_course'] if course_ok else b['lane']
        key=str(b['racer_id']),c
        trials=[x for x in roles[key] if x[0] is not None]
        wins=[x for x in trials if x[2]==1]
        for m in ('逃げ','差し','まくり','まくり差し','抜き'):
            k=sum(x[0]==m for x in wins)
            role_view.append((b['name'],c,m,fmt(rate(k,len(trials))),fmt(rate(k,len(wins))),
                fmt(rate(sum(x[0]==m and x[2]!=1 for x in trials),len(trials)))))
        adj=starts[key];ss=[r for r in players[key[0]] if r['course']==c]
        sr=[r['st_rank'] for r in ss if r['st_rank'] is not None]
        st_view.append((b['name'],c,len(adj),round(mean(adj),3) if adj else None,
            round(mean(sr),2) if sr else None,len(sr),fmt(rate(sum(x[0]=='逃げ' and x[1]==1 for x in trials),len(trials))) if c==2 else '対象外'))
        mh=motor_rows[b.get('motor_number')];paired=[(hit,base) for hit,base,_,_ in mh if base is not None]
        motor_view.append((b['lane'],b.get('motor_number'),len(mh),len(paired),
            round(100*mean(hit-base for hit,base in paired),1) if paired else None))
    pages['6艇比較']+=table(['選手','実コース','決まり手','既知完走あたり勝利','本人勝利内の構成','当該決まり手で他艇勝利'],role_view)+table(['選手','コース','隣接ST母数','本番ST差（外−内）','平均ST順位','順位母数','2コース時の1逃げ'],st_view)
    pages['モーター']+=table(['艇','機番','完走','比較可能走','2連対の期待との差 pt'],motor_view)+'<p>各走の使用選手について、それ以前の日に同じ実コースで当該機を除いて走った2連対率を基準とし、観測との差を平均。比較履歴ゼロは除外。少数標本・相手の強さによる偏りが残る。</p>'
    found=discover(db,day)
    pages['傾向の再検証']+='<h3>風速条件の探索</h3><p>場ごとに風速4m/s以上と未満を比較。探索期間に両群100件以上の場から逃げ率の低下幅が最大の1場を固定し、2025年で同条件を再集計。</p>'+table(['選択場','期間','風速','実1コース逃げ'],[(VENUES[int(v)-1],'2025検証' if h else '2022–24探索','4m/s以上' if w else '4m/s未満',fmt(rr)) for v,h,w,rr in found])
    scores=evaluate_escape(db,day)
    pages['精度・出典']+='<h3>イン逃げ頻度の時系列検証</h3><p>2022〜24年の場別逃げ率に加算平滑化（成功+1、母数+2）。2025年を一括評価。誤差は小さいほど良好。校正差は検証実測率−推定率。研究基準値で、個別レースの確率としては未採用。</p>'+table(['場','学習R','検証R','推定%','実測%','校正差 pt','Brier','Log Loss','全国固定Brier','全国固定Log Loss'],[(VENUES[int(v)-1],n,tst,round(100*p,2),round(100*obs,2),round(100*(obs-p),2),*(round(s,5) for s in loss)) for v,n,tst,p,obs,*loss in scores])
    historical_profiles=db.execute("""SELECT e.racer_id,max(e.name),count(*),sum(rank=1),
       sum(rank<=3),min(day),max(day) FROM entry e JOIN race USING(id) WHERE day<? GROUP BY e.racer_id ORDER BY e.racer_id""",(day,))
    pages['選手検索']+='<h3>長期公式K成績</h3>'+table(['登録','選手（収録表記）','完走','1着','3着内','初回','最終'],historical_profiles)
    detail=[]
    for b in boats:
        rid=str(b['racer_id'])
        for c in range(1,7):
            ss=summarize(recent([r for r in players[rid] if r['course']==c]))
            detail.append((b['name'],c,ss['n'],ss['first_pct'],ss['second_pct'],ss['third_pct'],ss['st_mean']))
    pages['6艇比較']+='<details><summary>6選手のコース別直近10走</summary>'+table(['選手','コース','収録走','1着%','2着%','3着%','平均ST'],detail)+'</details>'
    p_recent=(data/'venue24_v2'/'daily_source')
    errors=[]
    for file in sorted(p_recent.glob('*.acquisition_error.audit.json')):
        item=json.loads(file.read_text()); errors.append((item.get('date'),item.get('checked_at'),item.get('error')))
    pages['収録・欠損']+='<h3>オリジナル展示の取得エラー記録</h3>'+table(['日付','確認日時','取得結果'],errors)
    pages['精度・出典']+=table(['原本','参照情報'],[('長期資料',a.db.name),('常滑G1',a.g1.name),('当該レース原本',str(path.relative_to(data)) if path.exists() else 'lineups.sqlite / '+day+code+f'{a.race:02}'),('対象レース出典',t.get('source')),('分割展示','BoatraceCSV・日別CSVと同日監査JSON'),('選手・機力・近況の履歴範囲',min((r['day'] for r in history),default='未取得')+'〜'+max((r['day'] for r in history),default='未取得')),('注意','日数指定は検索窓。保存されていない日も含む。監査と結果照合は対象日以降の記録を含み得るため、レース説明変数には使用しない。')])
    split_history=cohorts(p_recent,code,day,local)
    pages['展示比較']+='<h3>同じ場・実進入での展示順位と本番3連対</h3>'+table(['計測項目','実コース','展示順位','3連対'],[(metric,c,'上位2位' if top else '3位以下',fmt(rate(sum(f<=3 for f in finishes),len(finishes)))) for (metric,c,top),finishes in sorted(split_history.items())])
    profile_file=data/'venue_tide_profiles.json'
    if profile_file.is_file():
        source=json.loads(profile_file.read_text())
        profiles=source.get('venues',{})
        pages['水面・風・潮']+=table(['水質','潮差','観測地点・適用条件','資料更新'],[(profiles.get(code,{}).get('water_type'),profiles.get(code,{}).get('tidal_difference'),profiles.get(code,{}).get('exclusion_reason') or profiles.get(code,{}).get('station_name'),source.get('updated_at'))])
        p=profiles.get(code,{})
        state=tide(data/'tide',p,day,t.get('deadline'))
        if state:
            pages['水面・風・潮']+=table(['最終正時 JST','天文潮位 cm','前1時間変化 cm','方向'],[state])
        trend=[]
        for c,vp in sorted(profiles.items()):
            observed=defaultdict(list)
            for race in history:
                if race['venue']!=c:continue
                state=tide(data/'tide',vp,race['day'],race['deadline'])
                if state:observed[state[3]].append(race)
            for direction,rs in sorted(observed.items()):
                trend.append((VENUES[int(c)-1],vp.get('station_name'),direction,len(rs),
                    fmt(rate(sum(r['winning_course']==1 and r['method']=='逃げ' for r in rs if r['method']),sum(bool(r['method']) for r in rs)))))
        pages['水面・風・潮']+='<h3>周辺地点の潮位変化と当地の逃げ</h3><p>気象庁の公開天文潮位（予報値）。締切前の直近正時と1時間前の差。水面の実測値・流速は未取得。同値を潮止まりとは認定しない。</p>'+table(['場','基準地点','前1時間の方向','対象R','逃げ'],trend)
    derby=db.execute("""SELECT deciding_method,count(*),sum(winning_boats like '1-%'),sum(payout_yen>=10000)
        FROM race WHERE jcd='08' AND day BETWEEN '20221025' AND '20221030' AND day<? GROUP BY deciding_method""",(day,)).fetchall()
    pages['全国24場']+='<h3>常滑SG・第69回ボートレースダービー</h3><p>公式開催期間 2022年10月25〜30日。対象は公式K成績の6艇正常完走。</p>'+table(['決まり手','完走R','1号艇1着','万舟'],derby)
    explanations=[]
    for b in boats:
        c=b['exhibition_course'] if course_ok else b['lane']
        key=str(b['racer_id']),c;known=[x for x in roles[key] if x[0] is not None]
        for method in ('逃げ',) if c==1 else ('差し','まくり','まくり差し'):
            k=sum(m==method and finish==1 for m,_,finish in known)
            local_cases=[r for r in scen if r['attacker']==c and r['deciding_method']==method]
            n=sum(r['n'] for r in local_cases)
            if not n:continue
            followers=Counter()
            for r in local_cases:followers[r['second']]+=r['n']
            leader,hits=followers.most_common(1)[0]
            explanations.append((b['name'],c,method,fmt(rate(k,len(known))),f'{leader}コース '+fmt(rate(hits,n)),f'他コースが2着 {n-hits}/{n}'))
    pages['展開シミュレーション']+='<h3>この6選手の攻めと、当地での連動</h3><p>本人がその勝ち方をした頻度と、当地で同じ攻めが成立した後の2着を比較。想定進入が動けば該当する行も変わる。</p>'+table(['攻める選手','想定コース','勝ち筋','本人・既知完走あたり','当地の最多2着コース','反対事例'],explanations)
    split_totals,retry=audit_splits(p_recent,cv['days'])
    pages['収録・欠損']+='<h3>23場のオリジナル展示・行単位の棚卸し</h3><p>番組表既知日のみ。保存はレースコード1行あり。各タイム完備の保証はない。中止掲示は場単位で、個々のRの返還は未照合。江戸川は公式展示を使う。</p>'+table(['場','予定','保存','重複','中止掲示・行なし','要再確認'],[(VENUES[v-1],x['scheduled'],x['saved'],x['duplicate'],x['cancel_notice'],x['scheduled']-x['saved']-x['cancel_notice']) for v in range(1,25) if v!=3 for x in [split_totals[f'{v:02}']]])
    import base64
    export={'audit':cv,'original_exhibition_retry':retry,'source_note':'daily manifests; race-code presence only; original records distinct from official exhibition'}
    encoded=base64.b64encode(json.dumps(export,ensure_ascii=False,separators=(',',':')).encode()).decode()
    pages['収録・欠損']+=f'<p><a download="coverage_{a.audit_end}.json" href="data:application/json;base64,{encoded}">日別・場別・R別の欠損と再取得対象を保存（JSON）</a></p>'
    riders={str(b['racer_id']):(b['exhibition_course'] if course_ok else b['lane']) for b in boats}
    terms=racer_terms(data/'racer_terms',day,riders)
    if terms:
        pages['選手検索']+='<h3>対象6選手・公式期別成績の推移</h3>'+table(['登録','適用期','算出開始','算出終了','級','全国勝率','全走数','実コース','進入数','1着','2着','3着','平均ST','平均ST順位'],[v[:-1] for v in terms])
        pages['精度・出典']+=table(['期','公式ファン手帳URL'],sorted({(r[1],r[-1]) for r in terms}))
    prog=program(data,t)
    if prog:
        info,meta=prog
        pages['6艇比較']='<p>'+cell(info.get('title'))+'　'+cell(info.get('subtitle'))+'　'+cell(info.get('grade_number_source'))+'</p>'+table(['艇','選手','全国勝率','当地勝率','全国2連対%','当地2連対%','全国3連対%','当地3連対%','F保有'],[(b['entry_number'],b['name'],b.get('national_win_rate'),b.get('local_win_rate'),b.get('national_top_2_percent'),b.get('local_top_2_percent'),b.get('national_top_3_percent'),b.get('local_top_3_percent'),b.get('flying_count')) for b in sorted(info['racers'].values(),key=lambda b:b['entry_number'])])+pages['6艇比較']
        pages['精度・出典']+=table(['当日番組出典','二次資料取得時刻'],[(meta['url'],meta['acquired_at'])])
    elif (data/'lineups.sqlite').is_file():
        line=connect(data/'lineups.sqlite')
        record=line.execute('select * from program_boat where id=? order by lane',(day+code+f'{a.race:02}',)).fetchall()
        line.close()
        if len(record)==6 and all(str(b['racer_id'])==v['racer'] and b['lane']==v['lane'] for b,v in zip(boats,record)):
            pages['6艇比較']=table(['艇','選手','番組全国勝率','当地勝率','F保有'],[(v['lane'],v['name'],v['national'],v['local'],v['f']) for v in record])+pages['6艇比較']
    ext_path=data/'extended.sqlite'
    if ext_path.is_file():
        ext=connect(ext_path)
        yearly=ext.execute("select substr(day,1,4),count(*),sum(raw),sum(included),sum(excluded) from source group by 1").fetchall()
        pages['収録・欠損']+='<h3>2021年以降の結果アーカイブ（独立した二次資料）</h3>'+table(['年','日別原本','収録結果','正常完走','除外'],yearly)
        pages['精度・出典']+=table(['年','公式Kと重なるR','組番相違','払戻欠損','払戻相違'],ext.execute('select * from result_check'))+table(['年','艇番が一致する比較行','登録・実進入・着順の相違行'],ext.execute('select * from entry_check'))+table(['結果アーカイブ改訂','索引作成日時'],ext.execute('select * from provenance'))
        full=[]
        for rid,c in riders.items():
            for days in (30,90,180,365):
                since=(as_day(day)-timedelta(days=days)).strftime('%Y%m%d')
                rr=ext.execute("select finish,st from runner where racer=? and course=? and id>=? and id<?",(rid,c,since,day)).fetchall()
                good=[x['st'] for x in rr if valid_number(x['st'],0,.99)]
                full.append((rid,c,days,len(rr),fmt(rate(sum(x['finish']==1 for x in rr),len(rr))),fmt(rate(sum(x['finish']<=3 for x in rr),len(rr))),len(good),round(mean(good),3) if good else None))
        pages['6艇比較']+='<h3>長期結果アーカイブで同じ期間を照合</h3><p>二次資料の正常完走のみ。展示保存履歴と重複する走もあるため合算はしない。</p>'+table(['登録','コース','日数','完走','1着','3連対','ST件数','平均ST'],full)
        ext.close()
    shapes,corr=start_study(local)
    pages['6艇比較']+='<h3>当地の展示STと本番ST</h3>'+table(['本番コース','両方有効','展示平均','本番平均','相関 r'],corr)+table(['展示隊形','対象R','実1コース逃げ'],[(k,len(rs),fmt(rate(sum(r['method']=='逃げ' and r['winning_course']==1 for r in rs if r['method']),sum(bool(r['method']) for r in rs)))) for k,rs in sorted(shapes.items())])+'<p>展示進入順の内・中・外2艇ずつの平均STを使用。最も遅い組が次の組より0.05秒以上遅いときだけ凹みと分類。閾値の予測能力は未検証。</p>'
    events,angles=motor_events(local,t,cycles)
    pages['モーター']+='<h3>記録された整備前後</h3>'+table(['機番','日','R','交換記録','直前最大3走・2連対','当走から最大3走・2連対'],[(m,d,n,p,fmt(before),fmt(after)) for m,d,n,p,before,after in events])+table(['機番','チルト','2連対'],[(m,tilt,fmt(rr)) for m,tilt,rr in angles])+'<p>正常完走の観測比較。複数の整備が近接すると観測窓が重なる。</p>'
    pg_path=data/'programs.sqlite'
    if ext_path.is_file() and pg_path.is_file():
        con=connect(pg_path)
        con.execute('attach database ? as ext',(ext_path.resolve().as_uri()+'?mode=ro',))
        rates=con.execute("""select p.venue,count(*),sum(r.id is not null)
                         from schedule p left join ext.result r using(id) where p.day between ? and ? group by p.venue""",(a.audit_start,a.audit_end))
        pages['収録・欠損']+='<h3>二次番組表と結果アーカイブの独立照合</h3>'+table(['場','予定掲載R','正常完走結果あり','中止・事故・未収録等 要区分'],[(VENUES[int(v)-1],n,k,n-k) for v,n,k in rates])
        years=[]
        for rid,c in riders.items():
            rows=con.execute("""select p.grade,p.stage,e.finish from ext.runner e join schedule p using(id)
                               where e.racer=? and e.course=? and p.day>=? and p.day<?""",(rid,c,(as_day(day)-timedelta(days=365)).strftime('%Y%m%d'),day))
            by=defaultdict(list)
            for grade,stage,finish in rows:
                tag='準優勝戦' if '準優勝戦' in (stage or '') else '優勝戦' if (stage or '').strip()=='優勝戦' else '予選系' if '予選' in (stage or '') else 'その他'
                by[grade,tag].append(finish)
            for (grade,tag),fs in sorted(by.items(),key=lambda kv:str(kv[0])):
                years.append((rid,c,grade,tag,len(fs),fmt(rate(sum(f==1 for f in fs),len(fs))),fmt(rate(sum(f<=3 for f in fs),len(fs)))))
        pages['6艇比較']+='<h3>同じ実コースでのグレード・競走区分別成績</h3>'+table(['登録','実コース','番組表gradeコード','競走区分','走数','1着','3連対'],years)
        pages['精度・出典']+=table(['二次番組アーカイブ改訂','索引作成日時'],con.execute('select * from provenance'))
        event=con.execute('select grade,title,stage from schedule where id=?',(day+code+f'{a.race:02}',)).fetchone()
        if event:
            grade_names={1:'SG',2:'G1系',3:'G2',4:'G3',5:'一般'}
            pages['ホーム・開催場']+='<p>選択中の番組　'+cell(event['title'])+'　'+cell(event['stage'])+'　'+cell(grade_names.get(event['grade']))+'</p>'
        con.execute('attach database ? as official',(a.db.resolve().as_uri()+'?mode=ro',))
        graded=con.execute("""select grade,deciding_method,count(*),sum(winning_boats like '1-%'),sum(payout_yen>=10000)
            from schedule p join official.race r using(id) where p.venue='08' and p.day<? and grade in (1,2)
            group by 1,2 order by 1,3 desc""",(day,))
        pages['全国24場']+='<h3>常滑・高グレード開催の決まり手</h3><p>番組表の開催グレードと公式KをレースIDで照合。男女併催等は開催全体の分類。</p>'+table(['開催区分','決まり手','完走R','1号艇1着','万舟'],[('SG' if g==1 else 'G1系',m,n,k,h) for g,m,n,k,h in graded])
        pages['収録・欠損']+=table(['二次番組の掲載日','有効な予定R','正常完走R','結果原本あり・正常完走外','結果原本で未照合'],con.execute("""select count(distinct p.day),count(*),sum(r.id is not null),sum(r.id is null and x.id is not null),sum(r.id is null and x.id is null) from schedule p left join ext.result r using(id) left join (select distinct id from ext.exclusion) x using(id) where p.day between ? and ?""",(a.audit_start,a.audit_end)))
        con.close()
    neighbors,eligible=nearest(local,t)
    values=[payout[r[1],r[2]] for r in neighbors if payout[r[1],r[2]] is not None]
    pages['類似レース']+='<details><summary>条件距離で近い履歴を検索（最大20件）</summary><p>同場・過去日の完全入力 '+str(eligible)+'R。級別・展示順位・展示進入・チルト・風速・波高の6項目を等重み。艇番ごとの級別と進入は不一致率、展示順位差は5、チルト差は2度、風速差は5m/s、波高差は10cmで正規化。各距離は1が上限。近い順に表示。</p>'+table(['距離','日付','R','決まり手','確定組','払戻円'],[(round(d,3),rd,rn,m,o,payout[rd,rn]) for d,rd,rn,m,o in neighbors])+table(['払戻取得R','最小円','中央値円','最大円','万舟'],[(len(values),min(values,default=None),median(values) if values else None,max(values,default=None),fmt(rate(sum(v>=10000 for v in values),len(values))))])+'</details>'
    perm={}
    if ext_path.is_file():
        con=connect(ext_path)
        since=(as_day(day)-timedelta(days=365)).strftime('%Y%m%d')
        for b in boats:
            stats={}
            for c,n,k in con.execute("select course,count(*),sum(finish=1) from runner where racer=? and id>=? and id<? group by course",(str(b['racer_id']),since,day)):
                stats[str(c)]=fmt(rate(k,n))
            perm[str(b['lane'])]={'name':b['name'],'stats':stats}
        con.close()
    else:
        for b in boats:
            rows=players[str(b['racer_id'])];stats={}
            for c in range(1,7):
                rr=[r for r in rows if r['course']==c]
                stats[str(c)]=fmt(rate(sum(r['finish']==1 for r in rr),len(rr)))
            perm[str(b['lane'])]={'name':b['name'],'stats':stats}
    order=''.join(str(b['lane']) for b in sorted(boats,key=lambda b:b.get('exhibition_course') if course_ok else b['lane']))
    pages['展開シミュレーション']+='<h3>進入変更を試す</h3><label>内から艇番6つ <input id="order" inputmode="numeric" maxlength="6" value="'+order+'"></label><div id="order_result" aria-live="polite"></div><script type="application/json" id="line_stats">'+json.dumps(perm,ensure_ascii=False).replace('<','\\u003c')+'</script><p>実進入ごとの過去365日内の1着率を再表示。深さや助走距離による当日の変化は未推定。</p>'
    db.close()
    return pages,scen,cv,checks,windows

def render(pages,scen):
    template=Path(__file__).with_name('desk.html').read_text()
    page_html=''.join(f'<section id="p{i}"><h2>{cell(k)}</h2>{v}</section>' for i,(k,v) in enumerate(pages.items()))
    menu=''.join(f'<option value="p{i}">{cell(k)}</option>' for i,k in enumerate(pages))
    return template.replace('@@MENU@@',menu).replace('@@PAGES@@',page_html).replace('@@DATA@@',json.dumps(scen,ensure_ascii=False).replace('<','\\u003c'))

def main():
    ap=argparse.ArgumentParser()
    for k in ('data','db','g1','out'):ap.add_argument('--'+k,required=True,type=Path)
    for k in ('day','venue','audit-start','audit-end'):ap.add_argument('--'+k,required=True)
    ap.add_argument('--race',type=int,required=True); a=ap.parse_args()
    pages,scen,cv,checks,windows=build(a)
    with a.out.open('x',encoding='utf8') as out:out.write(render(pages,scen))
    print(json.dumps([cv['totals'],checks,windows],ensure_ascii=False))

if __name__=='__main__': main()
