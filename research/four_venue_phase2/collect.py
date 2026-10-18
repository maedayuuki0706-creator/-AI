"""One national K download per day, reusing the prior Edogawa audit cache.

Two bounded GET workers, content-addressed immutable evidence, resumable daily
checkpoints. A missing archive is NOT evidence that a venue held no races.
The unchanged audited Edogawa parser is adapted by selecting a venue section;
original bytes, URL, timestamp and hash always refer to the untouched K archive.
"""
import argparse, hashlib, json, re, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from research.edogawa_phase2.acquire import put, digest, unpack, parse_text
from research.edogawa_history.backfill_365days import date_urls

VENUES={'03':'江戸川','16':'児島','23':'唐津','06':'浜名湖'}
START=date(2025,10,18);END=date(2026,10,17)

def parse_venue(day,txt,meta,jcd):
    if jcd not in VENUES: raise ValueError('Unsupported venue')
    section=re.search(r'(?ms)^'+jcd+r'KBGN\s*$(.*?)^'+jcd+r'KEND\s*$',txt)
    if not section:return [],{'section_present':False,'race_headers':0,'parsed_races':0}
    selected='03KBGN\n'+section[1]+'\n03KEND\n'
    rows=parse_text(day,selected,meta['source_url'],meta['sha256'],meta['observed_at'])
    headers=re.findall(r'(?m)^\s*(\d{1,2})R\s+.*?H\s*\d{4}m',section[1])
    for row in rows:
        row['race_id']=day.replace('-','')+jcd+f"{row['race_no']:02}"
        row.update(venue_code=jcd,venue=VENUES[jcd],data_source='BOATRACE_official_K',
                   attack_origin_actual=None,tide=None,current=None)
        # No pre-race average ST/class or motor period is provided by K.
        for b in row['boats']:b.update(average_st=None,racer_class=None)
    if len(rows)!=len(headers):raise ValueError('Header/record count mismatch')
    if len({r['race_no'] for r in rows})!=len(rows):raise ValueError('Duplicate official race')
    return rows,{'section_present':True,'race_headers':len(headers),'parsed_races':len(rows),
                 'cancellation_mentions':section[1].count('中止')+section[1].count('不成立')}

def collect(root,reuse,workers=2,retry_failed=False):
    root,reuse=Path(root),Path(reuse)
    days=[(START+timedelta(days=i)).isoformat() for i in range((END-START).days+1)]
    def get(day):
        path=root/'days'/f'{day}.json'
        if path.exists():
            old=json.loads(path.read_text())
            if old['status']=='parsed' or not retry_failed:return old
        cached=reuse/'official_days'/f'{day}.json'
        if cached.exists():
            meta=json.loads(cached.read_text());sha=meta.get('sha256')
            body=(reuse/'raw'/f'{sha}.lzh').read_bytes()
            if digest(body)!=sha:raise ValueError('Reused raw digest mismatch')
            meta={**meta,'reuse':'Edogawa_PR36_982110b','raw_path':f'data/research_edogawa_phase2/20261018/raw/{sha}.lzh',
                  'raw_zip':'data/research_edogawa_phase2/20261018/official_raw_archives.zip'}
            decoded=reuse/'decoded'/f'{sha}.txt'
            txt=decoded.read_text() if decoded.exists() else unpack(body)
        else:
            url=date_urls(date.fromisoformat(day))[1];stamp=datetime.now(timezone.utc).isoformat()
            meta={'day':day,'source_url':url,'observed_at':stamp,'reuse':False}
            try:
                req=urllib.request.Request(url,headers={'User-Agent':'FourVenuePhase2Research/1.0'})
                with urllib.request.urlopen(req,timeout=15) as response:
                    if response.geturl()!=url:raise ValueError('Unexpected redirect')
                    body=response.read(2000001)
                if len(body)>2000000:raise ValueError('Oversize archive')
                sha=digest(body);put(root/'raw'/f'{sha}.lzh',body)
                txt=unpack(body)
                meta.update(sha256=sha,raw_path=f'data/research_four_venue_phase2/20251018_20261017/raw/{sha}.lzh')
            except Exception as e:
                meta.update(status='archive_unavailable_not_no_race',error=str(e)[:300])
                target=path if not path.exists() else root/'retries'/f'{day}_{digest(stamp.encode())[:10]}.json'
                put(target,json.dumps(meta,ensure_ascii=False,sort_keys=True).encode());return meta
        # Parsing calls an in-memory legacy import adapter, so it occurs below
        # on the main thread, not in the GET workers.
        return meta,txt,path
    out=[]
    with ThreadPoolExecutor(max_workers=max(1,min(2,workers))) as pool:
        for i,item in enumerate(pool.map(get,days),1):
            if isinstance(item,tuple):
                meta,txt,path=item
                try:
                    meta['venues']={}
                    for jcd in VENUES:
                        rows,coverage=parse_venue(meta['day'],txt,meta,jcd)
                        meta['venues'][jcd]={**coverage,'races':rows}
                    meta['status']='parsed'
                except Exception as e:meta.update(status='parse_failed',error=str(e))
                target=path if not path.exists() else root/'retries'/f"{meta['day']}_{meta['sha256'][:12]}.json"
                put(target,json.dumps(meta,ensure_ascii=False,sort_keys=True).encode())
            else:meta=item
            out.append(meta)
            if i%20==0:print(json.dumps({'calendar_days_processed':i,'of':len(days)}),flush=True)
    summary={'start':str(START),'end':str(END),'calendar_days':365,'parsed_days':sum(d['status']=='parsed' for d in out),
             'reused_days':sum(bool(d.get('reuse')) for d in out),'new_download_days':sum(d['status']=='parsed' and not d.get('reuse') for d in out),
             'failed_days':[d['day'] for d in out if d['status']!='parsed'],
             'venues':{j:{'name':name,'race_rows':sum(len(d.get('venues',{}).get(j,{}).get('races',[])) for d in out),
                          'held_days':sum(bool(d.get('venues',{}).get(j,{}).get('races')) for d in out)} for j,name in VENUES.items()}}
    summary['acquisition_digest']=digest(json.dumps(out,sort_keys=True,ensure_ascii=False).encode())
    put(root/'acquisition'/f"{summary['acquisition_digest']}.json",json.dumps(out,sort_keys=True,ensure_ascii=False).encode())
    put(root/'acquisition'/f"{summary['acquisition_digest']}_summary.json",json.dumps(summary,sort_keys=True,ensure_ascii=False,indent=2).encode())
    print(json.dumps(summary,ensure_ascii=False),flush=True);return out,summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--reuse',required=True);p.add_argument('--retry-failed',action='store_true');a=p.parse_args()
    collect(a.out,a.reuse,retry_failed=a.retry_failed)
