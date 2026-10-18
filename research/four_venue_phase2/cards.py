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
                m=re.match(r'^([1-6])\s+(\d{4})(.+?)(\d{2})([^\d\s]{2,3})(\d{2})([AB][12])\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\d{1,3})\s+([\d.]+)\s+(\d{1,3})\s+([\d.]+)(.*)$',line)
                if not m:continue
                boats.append({'lane':int(m[1]),'racer_id':m[2],'name':re.sub(r'\s+','',m[3]),'age':int(m[4]),'branch':m[5],
                    'weight_kg':int(m[6]),'racer_class':m[7],'national_win_rate':float(m[8]),'national_top2_rate':float(m[9]),
                    'local_win_rate':float(m[10]),'local_top2_rate':float(m[11]),'motor_number':int(m[12]),'motor_top2_rate':float(m[13]),
                    'boat_number':int(m[14]),'boat_top2_rate':float(m[15]),'series_results_raw':m[16].strip(),'average_st':None})
            out.append({'race_id':day.replace('-','')+jcd+f'{int(h[1]):02}','venue_code':jcd,'venue':name,'date':day,
                        'race_no':int(h[1]),'deadline_scheduled':h[2],'boats':boats,'six_boats_parsed':len(boats)==6,
                        **meta,'data_source':'BOATRACE_official_B','prerace_publication_verified':False})
    return out

def run(acquisition,out,probe):
    days=json.loads(Path(acquisition).read_text());root=Path(out);probes={}
    # Reuse the explicitly inspected October17 program probe; never redownload it.
    if probe:
        for f in Path(probe).glob('*.lzh'):
            body=f.read_bytes();probes['2026-10-17']=(body,unpack(body))
    def one(d):
        day=d['day'];path=root/'days'/(day+'.json')
        if path.exists():return json.loads(path.read_text())
        url='https://www1.mbrace.or.jp/od2/B/'+day[:7].replace('-','')+'/b'+day[2:].replace('-','')+'.lzh'
        meta={'source_url':url,'observed_at':datetime.now(timezone.utc).isoformat()}
        # A day with no selected venue K section does not require B acquisition.
        if not any(v['section_present'] for v in d.get('venues',{}).values()):
            result={'day':day,'status':'not_requested_no_selected_K_section','races':[],**meta}
        else:
            try:
                if day in probes:body,txt=probes[day];meta['reuse']='inspected_program_probe'
                else:
                    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'FourVenuePhase2Research/1.0'}),timeout=15) as response:
                        if response.geturl()!=url:raise ValueError('Unexpected redirect')
                        body=response.read(2000001)
                    if len(body)>2000000:raise ValueError('Oversize archive')
                    txt=unpack(body)
                meta['sha256']=digest(body);put(root/'raw'/(meta['sha256']+'.lzh'),body)
                result={'day':day,'status':'parsed','races':parse(day,txt,meta),**meta}
            except Exception as e:result={'day':day,'status':'unavailable_not_imputed','races':[],**meta,'error':str(e)[:200]}
        put(path,json.dumps(result,ensure_ascii=False,sort_keys=True).encode());return result
    records=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for i,r in enumerate(pool.map(one,days),1):
            records.append(r)
            if i%30==0:print('Program days',i,'/365',flush=True)
    body=json.dumps(records,ensure_ascii=False,sort_keys=True).encode();path=root/(digest(body)+'.json');put(path,body)
    print(json.dumps({'path':str(path),'parsed_days':sum(x['status']=='parsed' for x in records),'unavailable_days':sum(x['status']=='unavailable_not_imputed' for x in records),'races':sum(len(x['races']) for x in records)}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--acquisition',required=True);p.add_argument('--out',required=True);p.add_argument('--probe');a=p.parse_args();run(a.acquisition,a.out,a.probe)
