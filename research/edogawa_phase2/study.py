"""Reproducible audit/descriptive studies. Actual ST/method never feed predictions.

Original history is untouched. Official replacements keep field-level differences.
Nonofficial/unreconciled races are quarantined from coefficient training.
"""
import argparse, csv, hashlib, json, math
from collections import Counter, defaultdict
from pathlib import Path
from .acquire import put, digest

POSITIONS=['first','second','third','fourth','fifth','sixth']
METHODS=['逃げ','差し','まくり','まくり差し','抜き','恵まれ']
def loadcsv(p): return list(csv.DictReader(Path(p).open(encoding='utf-8-sig')))
def integer(x):
    try: return int(x) if str(x).strip() else None
    except (ValueError,TypeError): return None
def numeric(x):
    try:
        y=float(x);return y if math.isfinite(y) else None
    except (TypeError,ValueError): return None
def wilson(k,n):
    if not n: return None,None
    z=1.96;c=(k/n+z*z/(2*n))/(1+z*z/n);h=z*math.sqrt(k/n*(1-k/n)/n+z*z/(4*n*n))/(1+z*z/n)
    return c-h,c+h
def wind_bucket(v):
    v=numeric(v)
    if v is None: return '不明'
    return '0〜1m' if v<2 else '2〜3m' if v<4 else '4〜5m' if v<6 else '6〜7m' if v<8 else '8m以上'
def wave_bucket(v):
    v=numeric(v)
    return '不明' if v is None else '0〜5cm' if v<=5 else '6〜10cm' if v<=10 else '11〜20cm' if v<=20 else '21cm以上'
def split(day):
    return '学習' if day<='2026-06-30' else '検証' if day<='2026-09-30' else '最終評価'
def writecsv(path,rows,fields=None):
    fields=fields or list(rows[0]) if rows else fields or ['status']
    import io
    out=io.StringIO();w=csv.DictWriter(out,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
    put(path,('\ufeff'+out.getvalue()).encode())

def audit(source, official):
    mapped={};duplicates=[];diff=[];missing=[];records=[]
    for r in source:
        key=r['race_id']
        if key in mapped:
            duplicates.append({'race_id':key,'identical':mapped[key]==r,'retained_source':r['data_source'] if r.get('data_source')=='BOATRACE_official_K' else mapped[key]['data_source']})
            if r.get('data_source')=='BOATRACE_official_K':mapped[key]=r
            continue
        mapped[key]=r
    officialmap={}
    for day in official:
        for r in day.get('races',[]):
            if r['race_id'] in officialmap and officialmap[r['race_id']]!=r:
                raise ValueError('Conflicting official records')
            officialmap[r['race_id']]=r
    extra=[r for k,r in officialmap.items() if k not in mapped]
    for r in extra:
        mapped[r['race_id']]={**r,'data_source':'not_in_original_history','sha256':None}
    for key,original in sorted(mapped.items()):
        base=dict(original)
        for p in POSITIONS: base[p]=integer(base.get(p))
        officialrow=officialmap.get(key);fields={}
        if officialrow and original['data_source']!='not_in_original_history':
            for k in POSITIONS+['method','wind_dir','wind_m','wave_cm','weather']+[f'course{i}_st' for i in range(1,7)]:
                old=base.get(k);new=officialrow.get(k)
                same=numeric(old)==numeric(new) if k in ['wind_m','wave_cm'] or k.endswith('_st') else old==new
                if not same: diff.append({'race_id':key,'field':k,'original':old,'official':new,'resolution':'公式優先','source_sha256':officialrow['sha256']})
        if officialrow:fields=officialrow
        row={**base,**fields,'original_source':original['data_source'],
             'original_sha256':original['sha256'],'source_observed_at_original':None,
             'official_verified':bool(officialrow),'split':split(original['date'])}
        row['finish_complete']=len({row.get(p) for p in POSITIONS if row.get(p) in range(1,7)})==6
        boats=row.get('boats',[])
        row['course_mapping_complete']=len(boats)==6 and {b.get('course') for b in boats}==set(range(1,7)) and {b['lane'] for b in boats}==set(range(1,7))
        abnormal=any(b.get('status') not in [f'{i:02}' for i in range(1,7)] for b in boats)
        row['abnormal_confirmed']=bool(officialrow and abnormal)
        row['normal_eligible']=bool(officialrow and row['finish_complete'] and row['course_mapping_complete'] and not abnormal and not row.get('cancelled'))
        top=[row.get(p) for p in POSITIONS[:3]]
        derived='-'.join(map(str,top)) if all(x in range(1,7) for x in top) and len(set(top))==3 else None
        row['trifecta_from_finish']=derived
        if row.get('trifecta') and row['trifecta']!=derived:
            row['normal_eligible']=False
            missing.append({'race_id':key,'field':'trifecta_consistency','reason':'払戻出目と着順が不一致。要個別確認'})
        row['wind_bucket']=wind_bucket(row.get('wind_m'));row['wave_bucket']=wave_bucket(row.get('wave_cm'))
        row['winner_course']=next((b['course'] for b in boats if b.get('finish')==1),None)
        row['entry_changed']=any(b['lane']!=b.get('course') for b in boats) if row['course_mapping_complete'] else None
        gaps=[]
        if not officialrow: gaps.append('official_reconciliation')
        if not row['finish_complete']: gaps.append('six_numeric_finishes_abnormal' if abnormal else 'six_numeric_finishes_unresolved')
        if not row['course_mapping_complete']: gaps.append('lane_course_mapping')
        for field in ['wind_m','wave_cm','weather','method','payout_per_100']:
            if row.get(field) in [None,'']: gaps.append(field)
        for field in ['tide','current','refund_detail','prerace_snapshot','video_attack_origin','original_acquired_at']:
            gaps.append(field)
        for field in gaps: missing.append({'race_id':key,'field':field,'reason':'異常着順は順位で補完しない' if field=='six_numeric_finishes_abnormal' else '取得証拠なし・推測補完なし'})
        row['missing_fields']=gaps;records.append(row)
    # Official races absent from original are not silently dropped or appended.
    return records,diff,missing,duplicates,extra

def describe(records):
    normal=[r for r in records if r['normal_eligible']]
    course=[];conditional=[];environment=[];racers=[];strows=[];monthly=[];confounding=[]
    for c in range(1,7):
        for changed in ['全体','枠なり','進入変更']:
            rs=[r for r in normal if changed=='全体' or r['entry_changed']==(changed=='進入変更')]
            boats=[(r,next(b for b in r['boats'] if b['course']==c)) for r in rs]
            n=len(boats);counts=Counter(b['finish'] for r,b in boats);lo,hi=wilson(counts[1],n)
            course.append({'コース':c,'進入条件':changed,'標本数':n,'1着数':counts[1],'2着数':counts[2],'3着数':counts[3],
                '1着率':counts[1]/n if n else None,'2着率':counts[2]/n if n else None,'3着率':counts[3]/n if n else None,'1着率95下限':lo,'1着率95上限':hi,
                **{m:sum(r['method']==m and b['finish']==1 for r,b in boats) for m in METHODS}})
    for c in range(1,7):
        for m in METHODS:
            rs=[r for r in normal if r['winner_course']==c and r['method']==m];n=len(rs)
            cnt=Counter((next(b['course'] for b in r['boats'] if b['finish']==2),next(b['course'] for b in r['boats'] if b['finish']==3)) for r in rs)
            for b in range(1,7):
                for d in range(1,7):
                    if len({c,b,d})!=3:continue
                    k=cnt[b,d];lo,hi=wilson(k,n)
                    conditional.append({'1着コース':c,'決まり手':m,'2着コース':b,'3着コース':d,'該当数':k,'条件標本数':n,'条件付き割合':k/n if n else None,'95下限':lo,'95上限':hi,'用途':'事後記述・実戦入力禁止'})
    for field,label in [('wind_bucket','風速'),('wind_dir','風向'),('wave_bucket','波高')]:
        groups=defaultdict(list)
        for r in normal: groups[str(r.get(field) or '不明')].append(r)
        for group,rs in sorted(groups.items()):
            for period in ['全体']+sorted({r['date'][:7] for r in rs}):
                sub=[r for r in rs if period=='全体' or r['date'][:7]==period];n=len(sub);k=sum(r['winner_course']==1 for r in sub);lo,hi=wilson(k,n)
                environment.append({'条件':label,'区分':group,'年月':period,'標本数':n,'1コース1着数':k,'1コース1着率':k/n,'95下限':lo,'95上限':hi,
                    '開催日数':len({r['date'] for r in sub}),'判定':'記述相関のみ・選手構成等の交絡未調整',**{m:sum(r['method']==m for r in sub) for m in METHODS}})
    rb=defaultdict(list)
    for r in normal:
        for b in r['boats']:
            rb[b['racer_id'],b['course']].append((r,b))
        sts=[b['actual_st'] for b in r['boats'] if b.get('actual_st') is not None]
        for b in r['boats']:
            if b.get('actual_st') is None:continue
            rank=1+sum(s<b['actual_st'] for s in sts)
            strows.append({'race_id':r['race_id'],'日付':r['date'],'艇番':b['lane'],'実進入':b['course'],'本番ST秒':b['actual_st'],'ST順位同値同順位':rank,'着順':b['finish'],'選手番号':b['racer_id'],'用途':'本番STは事後情報'})
    for (rid,c),pairs in sorted(rb.items()):
        n=len(pairs);k=sum(b['finish']==1 for r,b in pairs);sts=[b['actual_st'] for r,b in pairs if b.get('actual_st') is not None];mean=sum(sts)/len(sts) if sts else None;lo,hi=wilson(k,n)
        racers.append({'選手番号':rid,'選手名':pairs[-1][1].get('name'),'コース':c,'出走数':n,'1着数':k,'1着率':k/n,'95下限':lo,'95上限':hi,
            '平均本番ST':mean,'本番ST標準偏差':math.sqrt(sum((s-mean)**2 for s in sts)/len(sts)) if sts else None,
            '荒水面出走数':sum((numeric(r['wind_m']) or 0)>=6 or (numeric(r['wave_cm']) or 0)>=15 for r,b in pairs),
            '全国比較':'全国同期間データ未取得','道中逆転':'映像・周回順位未取得','モーター組合せ':'使用期間未監査・係数不採用','判定':'少数標本' if n<30 else '記述統計・係数未検証'})
    for period in sorted({r['date'][:7] for r in records}):
        rs=[r for r in records if r['date'][:7]==period]
        monthly.append({'年月':period,'取得R':len(rs),'公式照合R':sum(r['official_verified'] for r in rs),'正常有効R':sum(r['normal_eligible'] for r in rs),'異常確認R':sum(r['abnormal_confirmed'] for r in rs),'未照合R':sum(not r['official_verified'] for r in rs)})
    # Racer/course/month matching is a sensitivity check, never a causal estimate.
    strata=defaultdict(lambda:defaultdict(list))
    for r in normal:
        wind=numeric(r.get('wind_m'))
        if wind is None or 2<=wind<6:continue
        group='弱風0〜1m' if wind<2 else '強風6m以上'
        for b in r['boats']:strata[b['racer_id'],b['course'],r['date'][:7]][group].append(int(b['finish']==1))
    for (rid,c,month),groups in sorted(strata.items()):
        lo=groups['弱風0〜1m'];hi=groups['強風6m以上']
        if not lo or not hi:continue
        confounding.append({'選手番号':rid,'コース':c,'年月':month,'弱風出走数':len(lo),'強風出走数':len(hi),'弱風1着率':sum(lo)/len(lo),'強風1着率':sum(hi)/len(hi),'差_強風引く弱風':sum(hi)/len(hi)-sum(lo)/len(lo),'限界':'同選手・同コース・同月のみ。開催節・対戦相手・モーター等は未調整。因果断定不可'})
    return {'course':course,'conditional':conditional,'environment':environment,'racers':racers,'actual_st':strows,'monthly':monthly,'confounding':confounding}

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--acquisition',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    raw=Path(a.source).read_bytes();off=Path(a.acquisition).read_bytes();audit_code=Path(__file__).read_bytes();run=digest(raw+off+audit_code)[:16];out=Path(a.out)/run
    records,diffs,missing,dups,extra=audit(loadcsv(a.source),json.loads(off));tables=describe(records)
    summary={'source_rows':len(loadcsv(a.source)),'unique_original_rows':len({r['race_id'] for r in loadcsv(a.source)}),'canonical_rows':len(records),'official_verified':sum(r['official_verified'] for r in records),'normal_eligible':sum(r['normal_eligible'] for r in records),'abnormal_confirmed':sum(r['abnormal_confirmed'] for r in records),'original_incomplete':sum(any(integer(r.get(p)) is None for p in POSITIONS) for r in loadcsv(a.source)),
        'unresolved_original_incomplete':sum('six_numeric_finishes_unresolved' in r['missing_fields'] for r in records),'differences':len(diffs),'duplicate_rows':len(dups),'official_extra_races':len(extra),'split_counts':{s:sum(r['normal_eligible'] and r['split']==s for r in records) for s in ['学習','検証','最終評価']},'source_sha256':digest(raw),'acquisition_sha256':digest(off),'run_id':run,
        'limitations':['潮・潮流未連結','原取得日時は元CSVに存在せず不明','本番ST・決まり手・実進入は事前特徴量に利用禁止','212Rの異常着順は欠落か事故かを公式記録で区別','映像攻め起点ラベルなし','全国成績・モーター使用期間未監査','後付け研究を実予想扱いしない']}
    for name,obj in [('summary',summary),('audited_races',records),('official_extra_races',extra),('analysis_tables',tables)]: put(out/(name+'.json'),json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2).encode())
    for name,rows in [('differences',diffs),('missing',missing),('duplicates',dups)]+list(tables.items()): writecsv(out/(name+'.csv'),rows)
    print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__': main()
