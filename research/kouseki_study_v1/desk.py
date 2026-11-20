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
from longitudinal import connect, scenarios, follower, similar, check_g1, evaluate_escape, discover
from relationships import study

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
    norm=lambda s: ''.join(s.split())
    boats=sorted(target['rows'],key=lambda b:b['lane'])
    if any(norm(r[f'艇{i}_選手名'])!=norm(b['name']) for i,b in enumerate(boats,1)):return [],[]
    cols=[]; labels=[]
    for j in range(1,4):
        if not r.get(f'計測項目{j}'): continue
        times=[]
        for i in range(1,7):
            try: v=float(r[f'艇{i}_値{j}'])
            except (ValueError,TypeError): v=None
            times.append(v if valid_number(v,0.01,180) else None)
        cols.append(times);labels.append(r[f'計測項目{j}'])
    return labels,cols

def exhibit(names, cols):
    def td(i,col):
        v=col[i]
        rank=1+sum(a<v for a in col) if all(a is not None for a in col) else None
        return f'<td class="r{rank}">{cell(v)}</td>'
    return '<div class="scroll"><table><tr><th>艇番</th>'+''.join('<th>'+cell(n)+'</th>' for n in names)+'</tr>'+''.join('<tr><td>'+str(i+1)+'</td>'+''.join(td(i,col) for col in cols)+'</tr>' for i in range(6))+'</table></div>'

def build(a):
    data=a.data
    path=data/'exhibition_log'/a.day/f'{a.venue}_{a.race:02}.json'
    t=json.loads(path.read_text()); day=t['day']; code=t['jcd']
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
    profiles=[]
    for rid,rows in sorted(players.items()):
        ss=summarize(rows)
        profiles.append((rid,rows[-1]['name'],len(rows),ss['first_pct'],ss['top3_pct'],ss['st_mean'],summarize(recent(rows))['top3_pct']))
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
    pages['精度・出典']=table(['2026年完走着順 × 保存公式3連単','件数'],sorted(checks.items()))+table(['常滑G1','収録R','1号艇1着','万舟','長期DB照合一致','不一致','照合対象外'],[(k,len(rs),sum(x[1]==1 for x in rs),sum(isinstance(x[2],int) and x[2]>=10000 for x in rs),sum(x[4] is True for x in rs),sum(x[4] is False for x in rs),sum(x[4] is None for x in rs)) for k,rs in g.items()])+table(['資料','対象期間・取得記録'],[('公式K成績（6艇完走）',str(tuple(db.execute('select min(day),max(day),count(*) from race where day<?',(day,)).fetchone()))),('出走・展示保存',path.name+' / '+str(t.get('captured_at'))),('分析対象履歴',str(audit)),('原本の締切前固定','未確認。リプレイ専用'),('未取得・未検証','潮位、事故理由の全件分類、2021年、確率校正、実機Safari、全選手の公式勝率・級別/節区分補正'),('生成日時 UTC',datetime.now(timezone.utc).isoformat())])
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
    pages['精度・出典']+=table(['原本','参照情報'],[('長期資料',a.db.name),('常滑G1',a.g1.name),('当該レース原本',str(path.relative_to(data))),('対象レース出典',t.get('source')),('分割展示','BoatraceCSV・日別CSVと同日監査JSON'),('選手・機力・近況の履歴範囲',min((r['day'] for r in history),default='未取得')+'〜'+max((r['day'] for r in history),default='未取得')),('注意','日数指定は検索窓。保存されていない日も含む。監査と結果照合は対象日以降の記録を含み得るため、レース説明変数には使用しない。')])
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
