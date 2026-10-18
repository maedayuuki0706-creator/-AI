"""Per-venue official audit and descriptive analysis, with an auditable database."""
import argparse,csv,json,sqlite3
from collections import Counter,defaultdict
from pathlib import Path
from .collect import VENUES
from research.edogawa_phase2 import study
from research.edogawa_phase2.acquire import put,digest

def motor_table(records):
    groups=defaultdict(list)
    for r in records:
        if not r['normal_eligible']:continue
        for b in r['boats']:
            if b.get('motor_number') is not None:groups[b['motor_number'],r['date'][:7]].append((r,b))
    rows=[]
    for (motor,month),pairs in sorted(groups.items()):
        n=len(pairs);k=sum(b['finish']<=2 for r,b in pairs);lo,hi=study.wilson(k,n)
        rows.append({'モーター番号':motor,'年月':month,'出走数':n,'2連対数':k,'2連対率':k/n,'95下限':lo,'95上限':hi,
                     '選手数':len({b['racer_id'] for r,b in pairs}),'判定':'番号再利用・交換日未監査。月内記述のみ・性能係数に採用不可'})
    return rows

def abnormal_conditional(records):
    groups=defaultdict(Counter)
    for r in records:
        if not r['abnormal_confirmed'] or r.get('dead_heat_confirmed'):continue
        bs=[next((b for b in r['boats'] if b.get('finish')==p),None) for p in [1,2,3]]
        if any(not b or b.get('course') is None for b in bs):continue
        c,b,d=[x['course'] for x in bs]
        if len({c,b,d})!=3:continue
        groups[c,r['method']][b,d]+=1
    rows=[]
    for c in range(1,7):
        for method in study.METHODS:
            cnt=groups[c,method];n=sum(cnt.values())
            for b in range(1,7):
                for d in range(1,7):
                    if len({c,b,d})!=3:continue
                    k=cnt[b,d];lo,hi=study.wilson(k,n)
                    rows.append({'集計群':'事故等確認・上位3艇進入確認のみ','1着コース':c,'決まり手':method,'2着コース':b,'3着コース':d,
                                 '該当数':k,'条件標本数':n,'条件付き割合':k/n if n else None,'95下限':lo,'95上限':hi,'用途':'事後記述・通常と分離・学習不採用'})
    return rows

def run(acquisition,source,out,cards=None):
    raw=Path(acquisition).read_bytes();days=json.loads(raw)
    if len(days)!=365 or len({x['day'] for x in days})!=365:raise ValueError('365 unique calendar checkpoints required')
    cardraw=Path(cards).read_bytes() if cards else b''
    carddays=json.loads(cardraw) if cardraw else []
    cardmap={r['race_id']:r for d in carddays for r in d['races']}
    run_id=digest(raw+cardraw+Path(__file__).read_bytes())[:16];root=Path(out)/run_id
    allrecords=[];combined=defaultdict(list);summaries=[]
    for jcd,name in VENUES.items():
        off=[{**d,'races':d.get('venues',{}).get(jcd,{}).get('races',[])} for d in days]
        original=study.loadcsv(source) if jcd=='03' else []
        records,diffs,missing,dups,extra=study.audit(original,off)
        fresh_ids={r['race_id'] for r in records if r['original_source']=='not_in_original_history'}
        missing=[m for m in missing if not (m['field']=='original_acquired_at' and m['race_id'] in fresh_ids)]
        for r in records:
            r.update(venue_code=jcd,venue=name)
            if r['original_source']=='not_in_original_history':
                r['source_observed_at_original']=r.get('observed_at')
                r['missing_fields']=[x for x in r['missing_fields'] if x!='original_acquired_at']
            r['six_boat_status_observed']=len(r['boats'])==6 and {b['lane'] for b in r['boats']}==set(range(1,7))
            # K has exhibition values but no archived pre-race publication time.
            r['historical_prerace_available']=False
            if r.get('dead_heat_confirmed'):
                r['normal_eligible']=False;r['trifecta_from_finish']=None
                r['missing_fields']=[x for x in r['missing_fields'] if x!='six_numeric_finishes_unresolved']
                missing[:]=[x for x in missing if not (x['race_id']==r['race_id'] and x['field'] in ['six_numeric_finishes_unresolved','trifecta_consistency'])]
                r['exclusion_reason']='公式同着。全6艇の記録はあるが単一の1〜6着に補完しない'
            card=cardmap.get(r['race_id']);r['program_archive']=card
            if card:
                r['deadline_scheduled']=card['deadline_scheduled']
                bylanes={b['lane']:b for b in card['boats']}
                for b in r['boats']:
                    p=bylanes.get(b['lane'])
                    if p and p['racer_id']==b['racer_id']:
                        b['program']=p;b['racer_class']=p['racer_class']
                        if not b.get('name'):
                            b['K_name_original']=b.get('name');b['name']=p['name'];b['name_source']='BOATRACE_official_B_same_racer_id'
                        for k in ['motor_number','boat_number']:
                            if b.get(k) is not None and b[k]!=p[k]:diffs.append({'race_id':r['race_id'],'field':'B_vs_K_'+str(b['lane'])+'_'+k,'original':p[k],'official':b[k],'resolution':'B番組とK確定を両方保存。変更理由は未確認','source_sha256':r['sha256']})
                    else:missing.append({'race_id':r['race_id'],'field':'program_racer_identity_'+str(b['lane']),'reason':'B/K選手ID不一致またはB解析不足。級別等を結合しない'})
            for field in ['average_st','tide_observation_match','motor_service_period','preinspection']:
                missing.append({'race_id':r['race_id'],'field':field,'reason':'公式Kに事前原本・対応観測証拠なし。補完しない'})
                r['missing_fields'].append(field)
            if any(b.get('racer_class') is None for b in r['boats']):
                missing.append({'race_id':r['race_id'],'field':'racer_class','reason':'B/Kで同一艇・同一選手を確認できず'});r['missing_fields'].append('racer_class')
        tables=study.describe(records);tables['motors']=motor_table(records)
        tables['conditional']=[{'集計群':'通常6艇',**r} for r in tables['conditional']]+abnormal_conditional(records)
        summary={'場コード':jcd,'場':name,'取得R':len(records),'開催日数':len({r['date'] for r in records}),
                 '公式確認日数':sum(d['status']=='parsed' for d in days),'取得失敗日数':sum(d['status']!='parsed' for d in days),
                 '正常有効R':sum(r['normal_eligible'] for r in records),'異常確認R':sum(r['abnormal_confirmed'] for r in records),
                 '同着R':sum(r.get('dead_heat_confirmed',False) for r in records),
                 '進入変更R':sum(r['entry_changed'] is True for r in records),'未照合R':sum(not r['official_verified'] for r in records),
                 '番組表結合R':sum(bool(r.get('program_archive')) for r in records),'級別6艇確認R':sum(len(r['boats'])==6 and all(b.get('racer_class') for b in r['boats']) for r in records),
                 '元CSV取得R':len(original),'元CSV着順不足R':sum(any(study.integer(r.get(p)) is None for p in study.POSITIONS) for r in original),
                 '元CSVにない公式R':len(extra) if original else None,'差分数':len(diffs),
                 '学習R':sum(r['normal_eligible'] and r['split']=='学習' for r in records),
                 '検証R':sum(r['normal_eligible'] and r['split']=='検証' for r in records),
                 '最終評価R':sum(r['normal_eligible'] and r['split']=='最終評価' for r in records),
                 '原本保存率':None,'改良版締切前実測R':0,'改善判定':'並行実測不足・判定不能'}
        summaries.append(summary);allrecords.extend(records)
        for table,rows in {**tables,'differences':diffs,'missing':missing,'duplicates':dups}.items():
            augmented=[{'場':name,'場コード':jcd,**r} for r in rows]
            combined[table].extend(augmented);study.writecsv(root/jcd/(table+'.csv'),augmented)
        put(root/jcd/'races.json',json.dumps(records,ensure_ascii=False,sort_keys=True).encode())
    coverage=[];program_only=[];result_ids={r['race_id'] for r in allrecords}
    daymap={d['day']:d for d in days}
    for key,r in sorted(cardmap.items()):
        kd=daymap[r['date']];kv=kd.get('venues',{}).get(r['venue_code'],{});notice=kv.get('cancellation_mentions',0)
        iscancel=r['race_no'] in kv.get('cancelled_race_numbers',[]);isvoid=r['race_no'] in kv.get('void_race_numbers',[])
        if key not in result_ids:program_only.append({'race_id':key,'日付':r['date'],'場':r['venue'],'R':r['race_no'],
            '締切予定':r['deadline_scheduled'],'状態':'公式中止' if iscancel else '公式不成立' if isvoid else '公式B番組あり・K結果なし',
            '理由':'公式K払戻欄で中止を確認' if iscancel else '公式K払戻欄で不成立を確認' if isvoid else '開催中止等の個別理由は未確認。非開催/正常レースと推測しない',
            'K中止記載件数':notice,
            'K取得元':kd['source_url'],'K_SHA256':kd['sha256'],
            '取得元':r['source_url'],'取得日時':r['observed_at'],'SHA256':r['sha256']})
    for d in days:
        for jcd,name in VENUES.items():
            v=d.get('venues',{}).get(jcd,{})
            coverage.append({'日付':d['day'],'場':name,'場コード':jcd,'状態':d['status'],
                             '公式節あり':v.get('section_present'),'R数':len(v.get('races',[])),
                             '解釈':'取得失敗・非開催扱い禁止' if d['status']!='parsed' else '公式節なし' if not v.get('section_present') else '公式節確認',
                             '取得日時':d['observed_at'],'取得元':d['source_url'],'SHA256':d.get('sha256'),
                             '再利用':bool(d.get('reuse')),
                             '番組予定R':sum(r['date']==d['day'] and r['venue_code']==jcd for r in cardmap.values()),
                             '番組のみR':sum(r['日付']==d['day'] and r['場']==name for r in program_only)})
    for s in summaries:
        s['公式中止R']=sum(r['場']==s['場'] and r['状態']=='公式中止' for r in program_only)
        s['結果未解明予定R']=sum(r['場']==s['場'] and r['状態']=='公式B番組あり・K結果なし' for r in program_only)
        put(root/s['場コード']/'summary.json',json.dumps(s,ensure_ascii=False,indent=2).encode())
    combined['coverage']=coverage;combined['summary']=summaries;combined['program_only']=program_only
    for name,rows in combined.items():study.writecsv(root/(name+'.csv'),rows)
    put(root/'analysis_tables.json',json.dumps(dict(combined),ensure_ascii=False,sort_keys=True).encode())
    put(root/'audited_races.json',json.dumps(allrecords,ensure_ascii=False,sort_keys=True).encode())
    manifest={'run_id':run_id,'acquisition_digest':digest(raw),'program_acquisition_digest':digest(cardraw) if cardraw else None,'venues':summaries,
              'calendar_days':365,'new_download_days':sum(not d.get('reuse') and d['status']=='parsed' for d in days),
              'reused_days':sum(bool(d.get('reuse')) for d in days),'failed_days':[d['day'] for d in days if d['status']!='parsed'],
              'program_only_races':len(program_only),'program_status_counts':dict(Counter(d['status'] for d in carddays)),
              'program_only_status_counts':dict(Counter(r['状態'] for r in program_only)),
              'program_unavailable_days':[d['day'] for d in carddays if d['status']!='parsed'],
              'unfilled':['平均STの事前原本','潮位/潮流の観測点・時刻・単位結合','返還明細','映像攻め起点','前検','モーター使用期間','B/K選手照合失敗時の級別'],
              'source':'BOATRACE公式K。江戸川の元ミラーCSVは別に保存・公式値を優先',
              'phase1_complete':False,'phase2_complete':False}
    put(root/'summary.json',json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2).encode())
    # DB stores raw observed JSON as well as indexed identities; no missing imputation.
    db=root/'four_venue_history.sqlite'
    if not db.exists():
        con=sqlite3.connect(db)
        con.executescript('CREATE TABLE races (race_id TEXT PRIMARY KEY, day TEXT, venue_code TEXT, venue TEXT, normal_eligible INTEGER, method TEXT, wind_m REAL, wind_dir TEXT, wave_cm REAL, source_url TEXT, observed_at TEXT, source_sha256 TEXT, record_json TEXT); CREATE INDEX race_filter ON races(venue_code,day,method,wind_m); CREATE TABLE boats(race_id TEXT,lane INTEGER,racer_id TEXT,name TEXT,course INTEGER,finish INTEGER,actual_st REAL,motor_number INTEGER,boat_number INTEGER,exhibition_time REAL,status TEXT,record_json TEXT,PRIMARY KEY(race_id,lane)); CREATE INDEX boat_filter ON boats(racer_id,course,motor_number); CREATE TABLE calendar(day TEXT,venue_code TEXT,status TEXT,record_json TEXT,PRIMARY KEY(day,venue_code));')
        con.executescript('CREATE TABLE audit_missing(race_id TEXT,venue_code TEXT,field TEXT,reason TEXT); CREATE INDEX missing_race ON audit_missing(race_id,field); CREATE TABLE audit_differences(race_id TEXT,venue_code TEXT,field TEXT,record_json TEXT); CREATE TABLE planned_without_result(race_id TEXT PRIMARY KEY,day TEXT,venue_code TEXT,record_json TEXT);')
        for r in allrecords:
            con.execute('INSERT INTO races VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(r['race_id'],r['date'],r['venue_code'],r['venue'],int(r['normal_eligible']),r['method'],r.get('wind_m'),r.get('wind_dir'),r.get('wave_cm'),r['source_url'],r.get('observed_at'),r['sha256'],json.dumps(r,ensure_ascii=False)))
            for b in r['boats']:
                con.execute('INSERT INTO boats VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(r['race_id'],b['lane'],b['racer_id'],b.get('name'),b.get('course'),b.get('finish'),b.get('actual_st'),b.get('motor_number'),b.get('boat_number'),b.get('exhibition_time'),b['status'],json.dumps(b,ensure_ascii=False)))
        for r in coverage:con.execute('INSERT INTO calendar VALUES(?,?,?,?)',(r['日付'],r['場コード'],r['状態'],json.dumps(r,ensure_ascii=False)))
        for r in combined['missing']:con.execute('INSERT INTO audit_missing VALUES(?,?,?,?)',(r['race_id'],r['場コード'],r['field'],r['reason']))
        for r in combined['differences']:con.execute('INSERT INTO audit_differences VALUES(?,?,?,?)',(r['race_id'],r['場コード'],r['field'],json.dumps(r,ensure_ascii=False)))
        for r in program_only:con.execute('INSERT INTO planned_without_result VALUES(?,?,?,?)',(r['race_id'],r['日付'],r['race_id'][8:10],json.dumps(r,ensure_ascii=False)))
        con.commit();con.close()
    print(json.dumps({'study':str(root),**manifest},ensure_ascii=False),flush=True);return root

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--acquisition',required=True);p.add_argument('--edogawa-source',required=True);p.add_argument('--out',required=True);p.add_argument('--cards');a=p.parse_args()
    run(a.acquisition,a.edogawa_source,a.out,a.cards)
