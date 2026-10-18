"""Official B program archive: registration/class/rates and scheduled deadline.

Stored separately from K outcomes. Publication/as-of snapshots are not invented;
download timestamps are the actual present acquisition time. Average ST is not
part of this format and remains missing.
"""
import argparse,json,re,unicodedata,urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from .collect import VENUES
from research.edogawa_phase2.acquire import unpack,put,digest

def parse(day,txt,meta):
    out=[];txt=unicodedata.normalize('NFKC',txt)
    for jcd,name in VENUES.items():
        sec=re.search(r'(?ms)^'+jcd+r'BBGN\s*$(.*?)^'+jcd+r'BEND\s*$',txt)
        if not sec:continue
        blocks=re.split(r'(?m)(?=^\s*\d{1,2}R\s+)',sec[1])
        for block in blocks:
            h=re.match(r'\s*(\d{1,2})R\s+.*?電話投票締切予定\s*(\d{2}:\d{2})',block)
            if not h:continue
            boats=[]
            for line in block.splitlines():
                m=re.match(r'^([1-6])\s+(\d{4})(.+?)(\d{2})([^\d\s]{2,3})(\d{2})([AB][12])(.*)$',line)
                if not m:continue
                # B fields are fixed width. At 100.00%, whitespace disappears
                # (e.g. boat 67 + 100.00 becomes " 67100.00"). Never split it
                # with a greedy digit regex or interpret it as boat 671.
                tail=m[8];edges=[0,5,11,16,22,25,31,34,40]
                fields=[tail[edges[i]:edges[i+1]].strip() for i in range(8)]
                try:
                    values=[float(x) if i not in [4,6] else int(x) for i,x in enumerate(fields)]
                except ValueError:continue
                if any(not 0<=values[i]<=100 for i in [1,3,5,7]):raise ValueError('Invalid B rate range')
                boats.append({'lane':int(m[1]),'racer_id':m[2],'name':re.sub(r'\s+','',m[3]),'age':int(m[4]),'branch':m[5],
                    'weight_kg':int(m[6]),'racer_class':m[7],'national_win_rate':values[0],'national_top2_rate':values[1],
                    'local_win_rate':values[2],'local_top2_rate':values[3],'motor_number':values[4],'motor_top2_rate':values[5],
                    'boat_number':values[6],'boat_top2_rate':values[7],'series_results_raw':tail[40:].strip(),'average_st':None})
            out.append({'race_id':day.replace('-','')+jcd+f'{int(h[1]):02}','venue_code':jcd,'venue':name,'date':day,
                        'race_no':int(h[1]),'deadline_scheduled':h[2],'boats':boats,'six_boats_parsed':len(boats)==6,
                        **meta,'data_source':'BOATRACE_official_B','prerace_publication_verified':False})
    return out

def reparse(acquisition,out):
    original=Path(acquisition).read_bytes();days=json.loads(original);root=Path(out)
    for d in days:
        if d['status']!='parsed':continue
        body=(root/'raw'/(d['sha256']+'.lzh')).read_bytes()
        if digest(body)!=d['sha256']:raise ValueError('B raw digest mismatch')
        meta={k:v for k,v in d.items() if k not in ['day','races','status']}
        d['races']=parse(d['day'],unpack(body),meta)
    body=json.dumps(days,ensure_ascii=False,sort_keys=True).encode();path=root/(digest(body)+'.json');put(path,body)
    print(json.dumps({'path':str(path),'GETs':0,'races':sum(len(d['races']) for d in days),'six_boat_races':sum(r['six_boats_parsed'] for d in days for r in d['races'])}),flush=True)

def run(acquisition,out,probe,retry_failed=False):
    days=json.loads(Path(acquisition).read_text());root=Path(out);probes={}
    # Reuse the explicitly inspected October17 program probe; never redownload it.
    if probe:
        for f in Path(probe).glob('*.lzh'):
            body=f.read_bytes();probes['2026-10-17']=(body,unpack(body))
    def one(d):
        day=d['day'];path=root/'days'/(day+'.json')
        resolved=root/'resolved_days'/(day+'.json')
        for p in sorted((root/'retries'/day).glob('*.json')):
            record=json.loads(p.read_text())
            if record['status']=='parsed':return record
        old=json.loads(resolved.read_text()) if resolved.exists() else json.loads(path.read_text()) if path.exists() else None
        if old and old['status']=='parsed':return old
        if old and old['status']=='unavailable_not_imputed' and not retry_failed:return old
        url='https://www1.mbrace.or.jp/od2/B/'+day[:7].replace('-','')+'/b'+day[2:].replace('-','')+'.lzh'
        meta={'source_url':url,'observed_at':datetime.now(timezone.utc).isoformat()}
        # Do not equate absence in results with absence of a scheduled meeting.
        # Prior unrequested checkpoints are resolved additively on the next run.
        try:
            if day in probes:body,txt=probes[day];meta['reuse']='inspected_program_probe'
            else:
                with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'FourVenuePhase2Research/1.0'}),timeout=15) as response:
                    if response.geturl()!=url:raise ValueError('Unexpected redirect')
                    body=response.read(2000001)
                if len(body)>2000000:raise ValueError('Oversize archive')
                meta['sha256']=digest(body);put(root/'raw'/(meta['sha256']+'.lzh'),body)
                txt=unpack(body)
            meta['sha256']=digest(body);put(root/'raw'/(meta['sha256']+'.lzh'),body)
            result={'day':day,'status':'parsed','races':parse(day,txt,meta),**meta}
        except Exception as e:result={'day':day,'status':'unavailable_not_imputed','races':[],**meta,'error':str(e)[:200]}
        body=json.dumps(result,ensure_ascii=False,sort_keys=True).encode()
        dest=(root/'retries'/day/(digest(body)+'.json')) if resolved.exists() else resolved if old else path
        put(dest,body);return result
    records=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for i,r in enumerate(pool.map(one,days),1):
            records.append(r)
            if i%30==0:print('Program days',i,'/365',flush=True)
    body=json.dumps(records,ensure_ascii=False,sort_keys=True).encode();path=root/(digest(body)+'.json');put(path,body)
    print(json.dumps({'path':str(path),'parsed_days':sum(x['status']=='parsed' for x in records),'unavailable_days':sum(x['status']=='unavailable_not_imputed' for x in records),'races':sum(len(x['races']) for x in records)}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--acquisition',required=True);p.add_argument('--out',required=True);p.add_argument('--probe');p.add_argument('--retry-failed',action='store_true');p.add_argument('--reparse',action='store_true');a=p.parse_args()
    if a.reparse:reparse(a.acquisition,a.out)
    else:run(a.acquisition,a.out,a.probe,a.retry_failed)
