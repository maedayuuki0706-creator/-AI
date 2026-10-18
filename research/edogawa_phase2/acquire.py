"""Bounded, resumable official K archive audit. Raw files are content-addressed.

Reuses the existing history parser for race boundaries/finishes; enriches its
discarded fields from the same official text. libarchive is an OS dependency.
Only explicit CLI execution performs GETs. Never edits source history.
"""
import argparse, csv, ctypes, ctypes.util, hashlib, json, re, urllib.request, unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, date
from pathlib import Path
from research.edogawa_history import backfill_365days as history

def digest(b): return hashlib.sha256(b).hexdigest()
def put(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as f: f.write(body)
    except FileExistsError:
        if path.read_bytes() != body: raise ValueError('Immutable collision: '+str(path))

def unpack(body):
    lib=ctypes.CDLL(ctypes.util.find_library('archive'))
    lib.archive_read_new.restype=ctypes.c_void_p
    for fn in ['archive_read_support_format_all','archive_read_support_filter_all','archive_read_free']:
        getattr(lib,fn).argtypes=[ctypes.c_void_p]
    lib.archive_read_open_memory.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t]
    lib.archive_read_next_header.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)]
    lib.archive_entry_pathname.argtypes=[ctypes.c_void_p];lib.archive_entry_pathname.restype=ctypes.c_char_p
    lib.archive_read_data.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t];lib.archive_read_data.restype=ctypes.c_ssize_t
    a=lib.archive_read_new();buf=ctypes.create_string_buffer(body)
    try:
        lib.archive_read_support_filter_all(a);lib.archive_read_support_format_all(a)
        if lib.archive_read_open_memory(a,buf,len(body))!=0: raise ValueError('Invalid official archive')
        ent=ctypes.c_void_p()
        while lib.archive_read_next_header(a,ctypes.byref(ent))==0:
            name=lib.archive_entry_pathname(ent).decode()
            out=bytearray();chunk=ctypes.create_string_buffer(65536)
            while True:
                n=lib.archive_read_data(a,chunk,len(chunk))
                if n<0: raise ValueError('Archive decompression failed')
                if n==0: break
                out.extend(chunk.raw[:n])
                if len(out)>20000000: raise ValueError('Archive too large')
            if name.upper().endswith('.TXT'): return bytes(out).decode('cp932',errors='strict')
        raise ValueError('No TXT in official archive')
    finally: lib.archive_read_free(a)

def parse_text(day, txt, url, body_sha, observed_at):
    # Preserve existing boundary/finish parser, with a tiny in-memory LHA adapter.
    import sys, types
    class Archive:
        def __init__(self,*args): pass
        def infolist(self): return [types.SimpleNamespace(filename='K.TXT')]
        def read(self,*args): return txt.encode('cp932')
    previous=sys.modules.get('lhafile')
    sys.modules['lhafile']=types.SimpleNamespace(Lhafile=Archive)
    try: rows=history.official(date.fromisoformat(day),b'parsed-official-text',url)
    finally:
        if previous is None: sys.modules.pop('lhafile',None)
        else: sys.modules['lhafile']=previous
    section=re.search(r'(?ms)^03KBGN\s*$(.*?)^03KEND\s*$',txt)
    if not section: return []
    blocks=re.split(r'(?m)(?=^\s*\d{1,2}R\s+.*?H\s*\d{4}m)',section[1])
    byno={r['race_no']:r for r in rows}
    for block in blocks:
        h=re.match(r'\s*(\d{1,2})R\s+',block)
        if not h or int(h[1]) not in byno: continue
        row=byno[int(h[1])];boats=[]
        for line in block.splitlines():
            m=re.match(r'^\s*(\d{2}|F\d?|S\d|L\d?|K\d)\s+([1-6])\s+(\d{4})\s+(.+)',line)
            if not m: continue
            # Fixed-width K tail: motor, boat, exhibition, actual course, actual ST.
            tail=re.search(r'\s(\d{1,3})\s+(\d{1,3})\s+(\d\.\d{2})\s+([1-6])\s+([FfLl]?[0-9.\-]+)(?:\s|$)',m[4])
            boats.append({'lane':int(m[2]),'racer_id':m[3],
                'finish':int(m[1]) if m[1].isdigit() else None,'status':m[1],
                'name':history.clean(m[4][:tail.start()]) if tail else None,
                'motor_number':int(tail[1]) if tail else None,
                'boat_number':int(tail[2]) if tail else None,
                'exhibition_time':float(tail[3]) if tail else None,
                'course':int(tail[4]) if tail else None,
                'actual_st':(-float(tail[5][1:]) if tail[5].upper().startswith('F') else history.num(tail[5],float)) if tail else None,
                'actual_st_raw':tail[5] if tail else None})
        pay=re.search(r'3連単\s+([1-6])\s*-\s*([1-6])\s*-\s*([1-6])\s+(\d+)',unicodedata.normalize('NFKC',block))
        row.update(boats=boats,source_url=url,sha256=body_sha,observed_at=observed_at,
            trifecta='-'.join(pay.group(i) for i in (1,2,3)) if pay else None,
            payout_per_100=int(pay[4]) if pay else None,
            refund_status='unknown',cancelled='不成立' in block or '中止' in block)
    return rows

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--out',required=True);p.add_argument('--workers',type=int,default=2)
    a=p.parse_args();root=Path(a.out)
    src=list(csv.DictReader(Path(a.source).open(encoding='utf-8-sig')))
    dates=sorted({x['date'] for x in src})
    def get(day):
        d=date.fromisoformat(day);url=history.date_urls(d)[1];cached=root/'official_days'/f'{day}.json'
        if cached.exists(): return day,json.loads(cached.read_text())
        observed=datetime.now(timezone.utc).isoformat()
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'Edogawa-Phase2-Research/1.0'})
            with urllib.request.urlopen(req,timeout=15) as response:
                if response.geturl()!=url: raise ValueError('Redirect rejected')
                body=response.read(2000001)
            if len(body)>2000000: raise ValueError('Too large')
            sha=digest(body);put(root/'raw'/f'{sha}.lzh',body)
            txt=unpack(body);put(root/'decoded'/f'{sha}.txt',txt.encode())
            # Parsing is deliberately outside workers (existing parser imports an adapter).
            result={'status':'downloaded','day':day,'source_url':url,'sha256':sha,'observed_at':observed}
        except Exception as e:
            result={'status':'unavailable','day':day,'source_url':url,'observed_at':observed,'error':str(e)[:300]}
        put(cached,json.dumps(result,ensure_ascii=False,sort_keys=True).encode())
        return day,result
    results=[]
    with ThreadPoolExecutor(max_workers=max(1,min(2,a.workers))) as ex:
        for i,(day,record) in enumerate(ex.map(get,dates),1):
            if record['status']=='downloaded':
                txt=(root/'decoded'/f"{record['sha256']}.txt").read_text()
                try: record['races']=parse_text(day,txt,record['source_url'],record['sha256'],record['observed_at']);record['status']='parsed'
                except Exception as e: record['status']='parse_failed';record['error']=str(e)
            results.append(record)
            if i%20==0: print('Official days',i,'/',len(dates),flush=True)
    body=json.dumps(results,ensure_ascii=False,sort_keys=True).encode();put(root/'acquisition'/f'{digest(body)}.json',body)
    print(json.dumps({'days':len(results),'parsed':sum(r['status']=='parsed' for r in results),'sha256':digest(body)}),flush=True)

if __name__=='__main__': main()
