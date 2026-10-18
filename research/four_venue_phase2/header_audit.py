"""Verify venue-section dates against requested K archive date, using cached bytes."""
import argparse,json,re,unicodedata
from pathlib import Path
from .collect import cached_body,VENUES
from research.edogawa_phase2.acquire import unpack,put

def run(acquisition,root,reuse,out,kind='K'):
    rows=[]
    for d in json.loads(Path(acquisition).read_text()):
        if d['status']!='parsed':continue
        txt=unicodedata.normalize('NFKC',unpack(cached_body(root,reuse,d['sha256'])))
        for j in VENUES:
            sec=re.search(r'(?ms)^'+j+kind+r'BGN\s*$(.*?)^'+j+kind+r'END\s*$',txt)
            if not sec:continue
            m=re.search(r'(\d{4})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})',sec[1]) if kind=='K' else re.search(r'(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日',sec[1])
            actual=f'{int(m[1]):04}-{int(m[2]):02}-{int(m[3]):02}' if m else None
            rows.append({'requested':d['day'],'venue_code':j,'header_day':actual,'matched':actual==d['day'],
                         'parsed_races':d['venues'][j]['parsed_races'] if kind=='K' else sum(r['venue_code']==j for r in d['races']),
                         'cancellation_mentions':d.get('venues',{}).get(j,{}).get('cancellation_mentions',0),
                         'source_sha256':d['sha256']})
    put(Path(out),json.dumps(rows,ensure_ascii=False,sort_keys=True).encode())
    print(json.dumps({'venue_day_headers':len(rows),'matched':sum(r['matched'] for r in rows),'unmatched_count':sum(not r['matched'] for r in rows),
                      'zero_race_sections':[r for r in rows if not r['parsed_races']]},ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--acquisition',required=True);p.add_argument('--root',required=True);p.add_argument('--reuse',required=True);p.add_argument('--out',required=True);p.add_argument('--kind',choices=['K','B'],default='K');a=p.parse_args();run(a.acquisition,a.root,a.reuse,a.out,a.kind)
