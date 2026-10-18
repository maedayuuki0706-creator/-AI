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
        for r in records:
            r.update(venue_code=jcd,venue=name)
            # K has exhibition values but no archived pre-race publication time.
            r['historical_prerace_available']=False
            card=cardmap.get(r['race_id']);r['program_archive']=card
            if card:
                r['deadline_scheduled']=card['deadline_scheduled']
                bylanes={b['lane']:b for b in card['boats']}
                for b in r['boats']:
                    p=bylanes.get(b['lane'])
                    if p and p['racer_id']==b['racer_id']:
                        b['program']=p;b['racer_class']=p['racer_class']
                        for k in ['motor_number','boat_number']:
                            if b.get(k) is not None and b[k]!=p[k]:diffs.append({'race_id':r['race_id'],'field':'B_vs_K_'+str(b['lane'])+'_'+k,'original':p[k],'official':b[k],'resolution':'B番組とK確定を両方保存。変更理由は未確認','source_sha256':r['sha256']})
                    else:missing.append({'race_id':r['race_id'],'field':'program_racer_identity_'+str(b['lane']),'reason':'B/K選手ID不一致またはB解析不足。級別等を結合しない'})
            for field in ['average_st','tide_observation_match','motor_service_period','preinspection']:
                missing.append({'race_id':r['race_id'],'field':field,'reason':'公式Kに事前原本・対応観測証拠なし。補完しない'})
            if any(b.get('racer_class') is None for b in r['boats']):missing.append({'race_id':r['race_id'],'field':'racer_class','reason':'B/Kで同一艇・同一選手を確認できず'})
        tables=study.describe(records);tables['motors']=motor_table(records)
        summary={'場コード':jcd,'場':name,'取得R':len(records),'開催日数':len({r['date'] for r in records}),
                 '公式確認日数':sum(d['status']=='parsed' for d in days),'取得失敗日数':sum(d['status']!='parsed' for d in days),
                 '正常有効R':sum(r['normal_eligible'] for r in records),'異常確認R':sum(r['abnormal_confirmed'] for r in records),
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
        put(root/jcd/'summary.json',json.dumps(summary,ensure_ascii=False,indent=2).encode())
    coverage=[]
    for d in days:
        for jcd,name in VENUES.items():
            v=d.get('venues',{}).get(jcd,{})
            coverage.append({'日付':d['day'],'場':name,'場コード':jcd,'状態':d['status'],
                             '公式節あり':v.get('section_present'),'R数':len(v.get('races',[])),
                             '解釈':'取得失敗・非開催扱い禁止' if d['status']!='parsed' else '公式節なし' if not v.get('section_present') else '公式節確認',
                             '取得日時':d['observed_at'],'取得元':d['source_url'],'SHA256':d.get('sha256'),
                             '再利用':bool(d.get('reuse'))})
    combined['coverage']=coverage;combined['summary']=summaries
    for name,rows in combined.items():study.writecsv(root/(name+'.csv'),rows)
    put(root/'analysis_tables.json',json.dumps(dict(combined),ensure_ascii=False,sort_keys=True).encode())
    put(root/'audited_races.json',json.dumps(allrecords,ensure_ascii=False,sort_keys=True).encode())
    manifest={'run_id':run_id,'acquisition_digest':digest(raw),'program_acquisition_digest':digest(cardraw) if cardraw else None,'venues':summaries,
              'calendar_days':365,'new_download_days':sum(not d.get('reuse') and d['status']=='parsed' for d in days),
              'reused_days':sum(bool(d.get('reuse')) for d in days),'failed_days':[d['day'] for d in days if d['status']!='parsed'],
              'unfilled':['平均STの事前原本','潮位/潮流の観測点・時刻・単位結合','返還明細','映像攻め起点','前検','モーター使用期間','B/K選手照合失敗時の級別'],
              'source':'BOATRACE公式K。江戸川の元ミラーCSVは別に保存・公式値を優先',
              'phase1_complete':False,'phase2_complete':False}
    put(root/'summary.json',json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2).encode())
    # DB stores raw observed JSON as well as indexed identities; no missing imputation.
    db=root/'four_venue_history.sqlite'
    if not db.exists():
        con=sqlite3.connect(db)
        con.executescript('CREATE TABLE races (race_id TEXT PRIMARY KEY, day TEXT, venue_code TEXT, venue TEXT, normal_eligible INTEGER, method TEXT, wind_m REAL, wind_dir TEXT, wave_cm REAL, source_url TEXT, observed_at TEXT, source_sha256 TEXT, record_json TEXT); CREATE INDEX race_filter ON races(venue_code,day,method,wind_m); CREATE TABLE boats(race_id TEXT,lane INTEGER,racer_id TEXT,name TEXT,course INTEGER,finish INTEGER,actual_st REAL,motor_number INTEGER,boat_number INTEGER,exhibition_time REAL,status TEXT,record_json TEXT,PRIMARY KEY(race_id,lane)); CREATE INDEX boat_filter ON boats(racer_id,course,motor_number); CREATE TABLE calendar(day TEXT,venue_code TEXT,status TEXT,record_json TEXT,PRIMARY KEY(day,venue_code));')
        for r in allrecords:
            con.execute('INSERT INTO races VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(r['race_id'],r['date'],r['venue_code'],r['venue'],int(r['normal_eligible']),r['method'],r.get('wind_m'),r.get('wind_dir'),r.get('wave_cm'),r['source_url'],r.get('observed_at'),r['sha256'],json.dumps(r,ensure_ascii=False)))
            for b in r['boats']:
                con.execute('INSERT INTO boats VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(r['race_id'],b['lane'],b['racer_id'],b.get('name'),b.get('course'),b.get('finish'),b.get('actual_st'),b.get('motor_number'),b.get('boat_number'),b.get('exhibition_time'),b['status'],json.dumps(b,ensure_ascii=False)))
        for r in coverage:con.execute('INSERT INTO calendar VALUES(?,?,?,?)',(r['日付'],r['場コード'],r['状態'],json.dumps(r,ensure_ascii=False)))
        con.commit();con.close()
    print(json.dumps({'study':str(root),**manifest},ensure_ascii=False),flush=True);return root

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--acquisition',required=True);p.add_argument('--edogawa-source',required=True);p.add_argument('--out',required=True);p.add_argument('--cards');a=p.parse_args()
    run(a.acquisition,a.edogawa_source,a.out,a.cards)
