"""Isolated, read-only source collection for the 2026-10-20 payout review."""
from pathlib import Path
import sys, json, re, datetime as dt, hashlib, gzip, base64, urllib.request, time, threading, concurrent.futures
from parsers import parse_racelist_boats, parse_beforeinfo, parse_result, parse_payout, textify

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'review'; OUT.mkdir(exist_ok=True)
STATE=ROOT/'reused-state'
DAY='20261020'
LOCK=threading.Lock(); last=0.
def now(): return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat()
def save(path,obj):
    path=OUT/path;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def get(url,key,refresh=False):
    global last
    meta=OUT/'acquisitions'/f'{key}.json'
    if meta.exists() and not refresh:
        m=json.loads(meta.read_text())
        if m.get('status')=='ok': return gzip.decompress(base64.b64decode((OUT/m['raw_path']).read_bytes())).decode('utf-8'),m
    with LOCK:
        time.sleep(max(0,1.2-(time.monotonic()-last)));last=time.monotonic()
    m={'url':url,'requested_at':now(),'published_at':None,'source_family':'BOATRACE_official','usage':'retrospective_review','predictive_input_allowed':False}
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'boat-ai-research-review/1.0','Cache-Control':'no-cache'})
        with urllib.request.urlopen(req,timeout=25) as response:
            b=response.read(8_000_001);m.update(http_status=response.status,server_date=response.headers.get('Date'),final_url=response.geturl())
        if len(b)>8_000_000: raise ValueError('response exceeds limit')
        digest=hashlib.sha256(b).hexdigest();rawpath=f'raw/{digest}.html.gz.b64';(OUT/'raw').mkdir(exist_ok=True)
        (OUT/rawpath).write_bytes(base64.b64encode(gzip.compress(b,mtime=0)))
        m.update(retrieved_at=now(),sha256=digest,raw_path=rawpath,bytes=len(b),status='ok');save(Path('acquisitions')/f'{key}.json',m)
        return b.decode('utf-8'),m
    except Exception as e:
        m.update(retrieved_at=now(),status='error',missing_reason=f'{type(e).__name__}: {e}');save(Path('acquisitions')/f'{key}.json',m)
        return '',m

def pays(raw):
    out=[]
    for table in re.findall('<table[^>]*>(.*?)</table>',raw,re.S):
        venues=re.findall(r'alt="([^"]+)" src="[^\"]*/text_place1_(\d{2})\.png',table)
        for row in re.findall('<tr[^>]*>(.*?)</tr>',table,re.S):
            cells=re.findall('<t[dh][^>]*>(.*?)</t[dh]>',row,re.S)
            if not cells or not re.fullmatch(r'\d+R',textify(cells[0])):continue
            rno=int(textify(cells[0])[:-1]);i=1
            for name,jcd in venues:
                a=cells[i:i+3];i+=3;txt=[textify(x) for x in a]
                lanes=re.findall('[1-6]',txt[0]);p=re.search('[¥￥]([0-9,]+)',txt[1])
                out.append(dict(race_id=f'{DAY}_{jcd}_{rno:02d}',day=DAY,venue=name,jcd=jcd,rno=rno,trifecta='-'.join(lanes) if len(lanes)==3 else None,payout=int(p[1].replace(',','')) if p else None,popularity=int(txt[2]) if txt[2].isdigit() else None,raw_pay_cells=txt))
    assert len(out)==144 and len({x['race_id'] for x in out})==144
    return out

def collect(row):
    rid=row['race_id']; path=OUT/'races'/f'{rid}.json'
    if path.exists(): return rid,'cached'
    row=dict(row); row['recorded_at']=now();row['predictive_input_allowed']=False
    p=STATE/'reused_inputs'/f'{rid}.json';r=STATE/'results'/f'{rid}.json'
    sources={};missing=[]
    if p.exists():
        frozen=json.loads(p.read_text());originals=frozen['official_originals']
        program=originals['racelist']['html'];preview=originals['beforeinfo']['html']
        meta=frozen['meta'];row['input_timing']={'status':'existing_frozen_original','captured_at':meta['captured_at'],'deadline':meta['deadline'],'source_branch':'research-materials-state-v1','source_path':f'reused_inputs/{rid}.json','source_file_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'remote_receipt_verified_in_this_review':False}
        sources['program']=originals['racelist'];sources['preview']=originals['beforeinfo']
        # The complete immutable original already exists in the source branch.
        for v in sources.values(): v.pop('html',None)
    else:
        program,pm=get(f'https://www.boatrace.jp/owpc/pc/race/racelist?hd={DAY}&jcd={row["jcd"]}&rno={row["rno"]}',rid+'_racelist')
        preview,bm=get(f'https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd={DAY}&jcd={row["jcd"]}&rno={row["rno"]}',rid+'_beforeinfo')
        sources.update(program=pm,preview=bm);row['input_timing']={'status':'retrospectively_retrieved_prerace_display','captured_at':None,'retrieved_at':bm.get('retrieved_at'),'predeadline_capture_proven':False}
    boats=parse_racelist_boats(program);ex=parse_beforeinfo(preview)
    for b in boats:
        b.update(ex['boats'].get(b['lane'],{}))
        # Motor numbers are NOT a unique machine identifier across cycles.
        b['motor_cycle_id']=None;b['motor_cycle_missing_reason']='current venue motor cycle not independently verified in this review'
    row['prerace_display']={'boats':boats,'environment':{k:v for k,v in ex.items() if k!='boats'},'sources':sources}
    if len(boats)!=6:missing.append('six_boat_program_parse_incomplete')
    if ex['exhibition_count']!=6:missing.append('six_boat_exhibition_parse_incomplete')
    weather=re.search(r'水面気象情報\s*([^\n]*)',textify(preview));row['prerace_display']['environment']['official_weather_reference']=weather[1] if weather else None
    if r.exists():
        stored=json.loads(r.read_text());details=stored['details'];payout=stored['payout'];rs=stored['acquisition'];row['result_reused']=True
    else:
        raw,rs=get(f'https://www.boatrace.jp/owpc/pc/race/raceresult?hd={DAY}&jcd={row["jcd"]}&rno={row["rno"]}',rid+'_raceresult')
        try: details=parse_result(raw,DAY,row['jcd'],row['rno']);payout=parse_payout(raw)
        except Exception as e:details={};payout={};missing.append(f'result_parse: {e}')
        row['result_reused']=False
    row['outcome']={'details':details,'payout':payout,'source':rs,'usage':'outcome_only'}
    if details:
        if row['trifecta']!=details['trifecta'] or row['payout']!=details['payout_per_100']:missing.append('daily_pay_individual_result_mismatch')
    row['missing_reasons']=missing;save(Path('races')/f'{rid}.json',row)
    return rid,missing or 'ok'

def main():
    raw,meta=get(f'https://www.boatrace.jp/owpc/pc/race/pay?hd={DAY}','daily_pay_'+dt.datetime.now().strftime('%H%M%S'),True)
    rows=pays(raw);save(Path('daily_pay.json'),{'acquisition':meta,'races':rows})
    targets=[r for r in rows if r['payout'] is not None and (r['payout']>=10000 or r['jcd'] in ('03','16','23','12','13'))]
    # Source cadence is globally limited; at most three in-flight reads.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for rid,status in pool.map(collect,targets):print(rid,status,flush=True)
    save(Path('run.json'),{'completed_at':now(),'target_count':len(targets),'settled_count':sum(r['payout'] is not None for r in rows),'manshu_count':sum((r['payout'] or 0)>=10000 for r in rows),'requests_are_read_only':True,'production_files_changed':0})
if __name__=='__main__':main()
