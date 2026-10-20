"""Timestamped official evidence, existing-state reuse, and prospective gate.

All outputs must be in a separate research state. Existing inputs are read only.
The historical ZIP is referenced, never redownloaded or counted as new races.
"""
from __future__ import annotations
import argparse
import base64
from collections import Counter
from datetime import datetime, timedelta
import gzip
from hashlib import sha256
from itertools import permutations
import json
import os
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo
from research.capture_v1 import parsers

JST = ZoneInfo('Asia/Tokyo')
VENUES = {'03':'江戸川','06':'浜名湖','16':'児島','23':'唐津'}
ROOT = Path(__file__).resolve().parents[2]
ALL_ODDS = {'-'.join(map(str,x)) for x in permutations(range(1,7),3)}

def now(): return datetime.now(JST)
def stamp(): return now().isoformat()
def encode(v): return (json.dumps(v,ensure_ascii=False,sort_keys=True,allow_nan=False,indent=2)+'\n').encode()
def read(p): return json.loads(Path(p).read_bytes())
def digest(b): return sha256(b).hexdigest()
def once(path, body):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=body: raise ValueError('Immutable record conflict: '+str(path))
        return False
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as f: f.write(body); f.flush(); os.fsync(f.fileno())
    return True
def write(path,v):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    q=p.with_name(p.name+'.tmp');q.write_bytes(encode(v));os.replace(q,p)
def url(kind,day,code,rno):
    if kind not in {'racelist','beforeinfo','raceresult','odds3t'}:raise ValueError('Unsupported endpoint')
    datetime.strptime(day,'%Y%m%d')
    if code not in VENUES or not 1<=int(rno)<=12:raise ValueError('Bad identity')
    return 'https://www.boatrace.jp/owpc/pc/race/'+kind+'?'+urllib.parse.urlencode({'hd':day,'jcd':code,'rno':int(rno)})
def deadline(raw,rno):
    text=parsers.textify(raw);pos=text.find('締切予定時刻')
    times=re.findall(r'(?:[01]?\d|2[0-3]):[0-5]\d',text[pos:pos+900]) if pos>=0 else []
    if len(times)<12:raise ValueError('No official twelve-race deadline table')
    return times[int(rno)-1]
def aware(v):
    d=datetime.fromisoformat(v)
    if d.tzinfo is None:raise ValueError('Timezone required')
    return d.astimezone(JST)

class Store:
    def __init__(self,path):
        self.root=Path(path).resolve()
        if self.root==ROOT or ROOT in self.root.parents:raise ValueError('State must be separate from code repository')
        self.root.mkdir(parents=True,exist_ok=True);self.last=0.;self.fetches=0
    def record(self,category,key,value):
        b=encode(value);name=key+'_'+digest(b)[:16]+'.json'
        once(self.root/category/name,b)
        return str(Path(category)/name)
    def document(self,raw,meta):
        b=raw.encode() if isinstance(raw,str) else raw
        sha=digest(b);path='raw/'+sha+'.gz.b64';once(self.root/path,base64.b64encode(gzip.compress(b,mtime=0)))
        m={**meta,'sha256':sha,'raw_path':path,'bytes':len(b),'published_at':meta.get('published_at')}
        self.record('acquisitions',sha[:16],m)
        return m
    def body(self,doc):
        packed=(self.root/doc['raw_path']).read_bytes()
        if doc['raw_path'].endswith('.b64'):packed=base64.b64decode(packed,validate=True)
        b=gzip.decompress(packed)
        if digest(b)!=doc['sha256']:raise ValueError('Raw evidence hash mismatch')
        return b.decode('utf8',errors='replace')
    def get(self,source,ttl=60):
        key=digest(source.encode());p=self.root/'cache'/(key+'.json')
        if p.exists():
            old=read(p)
            if 0<=(now()-aware(old['retrieved_at'])).total_seconds()<ttl:return old
        delay=max(0,1.-(time.monotonic()-self.last))
        if delay:time.sleep(delay)
        self.last=time.monotonic();requested=stamp();self.fetches+=1
        meta={'url':source,'requested_at':requested,'retrieved_at':stamp(),'source_family':'BOATRACE_official'}
        try:
            req=urllib.request.Request(source,headers={'User-Agent':'BoatAI-MaterialsResearch/1.0'})
            with urllib.request.urlopen(req,timeout=20) as r:
                b=r.read(8_000_001);meta.update(http_status=r.status,final_url=r.geturl(),last_modified=r.headers.get('Last-Modified'),server_date=r.headers.get('Date'))
            if not b or len(b)>8_000_000:raise ValueError('Empty/oversized response')
            meta.update(retrieved_at=stamp(),status='ok')
            meta=self.document(b,meta)
        except Exception as exc:
            meta.update(retrieved_at=stamp(),status='unavailable',missing_reason=type(exc).__name__+': '+str(exc)[:250])
            self.record('acquisitions',key[:16],meta)
        write(p,meta);return meta

def program(raw):
    boats=parsers.parse_racelist_boats(raw)
    blocks={}
    for body in re.findall(r'<tbody\b[^>]*>(.*?)</tbody>',raw,re.S|re.I):
        m=re.search(r'is-boatColor([1-6])',body)
        if m and re.search(r'\d{4}\s*/\s*(?:A1|A2|B1|B2)',parsers.textify(body)):blocks[int(m[1])]=body
    for b in boats:
        block=blocks[b['lane']];cells=re.findall(r'<td\b[^>]*>(.*?)</td>',block,re.S|re.I)
        texts=[parsers.textify(x) for x in cells]
        t=parsers.textify(block)
        fl=re.search(r'F\s*(\d+)\s*L\s*(\d+)',t)
        branch=re.search(r'\n([^\n/]+)/([^\n/]+)\n\d+歳',t)
        b.update(flying_count=int(fl[1]) if fl else None,late_count=int(fl[2]) if fl else None,
                 branch=branch[1] if branch else None,birthplace=branch[2] if branch else None,
                 current_series_cells=texts[8:] if len(texts)>8 else [],
                 current_series_schema='official table cells, retained in source order; no synthetic results')
    return boats

def preview(raw):
    p=parsers.parse_beforeinfo(raw)
    t=parsers.textify(raw)
    direction=re.search(r'wind(?:Direction)?\s+is-wind(\d+)',raw,re.I)
    if not direction:direction=re.search(r'is-wind(\d+)',raw)
    p['wind_direction_official_icon']=int(direction[1]) if direction else None
    p['wind_direction_missing_reason']=None if direction else 'icon not found; no compass direction inferred'
    wt=re.search(r'水面気象情報\s*(\d{1,2}:\d{2})',t)
    p['source_weather_time_text']=wt[1] if wt else None
    p['weather_observed_at']=None
    p['weather_time_note']='Source time text retained; acquisition time is not measurement time'
    for b in p['boats'].values():
        # Existing parser only returns the current preview cells. Empty cells are
        # observed no-exchange, but an incomplete table is unknown.
        b.setdefault('parts_exchange',None);b.setdefault('propeller_exchange',None)
        b['parts_cell_status']='no_exchange_text' if not b['parts_exchange'] else 'published_exchange'
        b['propeller_cell_status']='no_exchange_text' if not b['propeller_exchange'] else 'published_exchange'
    return p

def result_environment(raw):
    p=preview(raw)
    return {k:p.get(k) for k in ('wind_speed','wave_cm','air_temp_c','water_temp_c','wind_direction_official_icon','source_weather_time_text')}

def parse_odds(raw):
    # Official 3t layout: first-place headers 1..6, then five second-place
    # blocks, each containing four third-place rows.
    bodies=re.findall(r'<tbody\b[^>]*>(.*?)</tbody>',raw,re.S|re.I)
    out={}
    for body in bodies:
        rows=re.findall(r'<tr\b[^>]*>(.*?)</tr>',body,re.S|re.I)
        if len(rows)!=20:continue
        for index,row in enumerate(rows):
            cells=re.findall(r'<td\b[^>]*>(.*?)</td>',row,re.S|re.I)
            first_row=index%4==0;group=index//4;third_idx=index%4;pos=0
            for head in range(1,7):
                second=[x for x in range(1,7) if x!=head][group]
                third=[x for x in range(1,7) if x not in (head,second)][third_idx]
                if first_row:
                    if pos>=len(cells) or parsers.clean(cells[pos])!=str(second):raise ValueError('Odds second-place identity mismatch')
                    pos+=1
                if pos+1>=len(cells) or parsers.clean(cells[pos])!=str(third):raise ValueError('Odds third-place identity mismatch')
                value=parsers.clean(cells[pos+1]);pos+=2
                if re.fullmatch(r'\d+(?:\.\d+)?',value):out[f'{head}-{second}-{third}']=float(value)
                elif value not in ('-','--','---','欠場'):raise ValueError('Unknown odds cell: '+value)
            if pos!=len(cells):raise ValueError('Unexpected odds layout')
    if set(out)!=ALL_ODDS:raise ValueError(f'Incomplete 120-way market: {len(out)}')
    return out

def import_existing(store,old,code_sha):
    old=Path(old).resolve()
    if old==store.root or old in store.root.parents or store.root in old.parents:raise ValueError('Read-only source must be disjoint')
    count=0;days=Counter();failed=[]
    for p in sorted((old/'inputs').rglob('*.json')):
        s=read(p);m=s['meta'];key=f"{m['day']}_{m['jcd']}_{int(m['rno']):02}"
        dest=store.root/'reused_inputs'/(key+'.json')
        if dest.exists():continue
        try:
            from research.venue_fusion_v1.official_program import from_frozen_official
            from_frozen_official(s,allow_missing_values=True)
            for kind,doc in s['official_originals'].items():
                if digest(doc['html'].encode())!=doc['sha256']:raise ValueError('Existing original hash mismatch')
                a=store.document(doc['html'],{'url':doc['url'],'retrieved_at':doc['observed_at'],'imported_at':stamp(),'reuse_source_commit':code_sha,'source_family':'BOATRACE_official','status':'ok'})
                data=program(doc['html']) if kind=='racelist' else preview(doc['html'])
                store.record('programs' if kind=='racelist' else 'previews',key,{'race_id':key,'day':m['day'],'venue_code':m['jcd'],'race_no':m['rno'],'deadline':m['deadline'],'acquisition':a,'data':data,'usage':'original_predeadline_input','new_race_count':0})
            once(dest,encode(s));count+=1;days[m['day']]+=1
        except Exception as exc:failed.append({'race_id':key,'reason':str(exc)})
    result={'checked_at':stamp(),'source_commit':code_sha,'newly_imported':count,'days':dict(days),'rejected':failed,'read_only_source':True,'new_races_counted':0}
    store.record('runs','reuse',result);return result

def import_existing_results(store,old,code_sha):
    count=0
    for p in sorted((Path(old)/'results').rglob('*.json')):
        r=read(p);key=p.stem;target=store.root/'reused_results'/(key+'.json')
        if target.exists():continue
        raw=r.get('raw_html')
        if not raw:continue
        if digest(raw.encode())!=r['sha256']:raise ValueError('Existing result hash mismatch')
        doc=store.document(raw,{'url':r['source_url'],'retrieved_at':r['observed_at'],'reuse_source_commit':code_sha,'source_family':'BOATRACE_official','status':'ok'})
        day,code,rno=key.split('_')
        try:details=parsers.parse_result(raw,day,code,int(rno));reason=None
        except ValueError:details=None;reason='official original has payout but lacks all-six finish/ST/course details'
        store.record('result_versions',key,{'race_id':key,'day':day,'venue_code':code,'race_no':int(rno),'acquisition':doc,'payout':parsers.parse_payout(raw),'details':details,'details_missing_reason':reason,'usage':'outcome_only'})
        once(target,encode({'source_commit':code_sha,'original_sha256':r['sha256'],'details_missing_reason':reason}));count+=1
    return count

def capture(store,day,code,rno,*,allow_result=True):
    key=f'{day}_{code}_{int(rno):02}'
    reused=store.root/'reused_inputs'/(key+'.json')
    old=read(reused) if reused.exists() else None
    if old:
        hhmm=old['meta']['deadline'];known_at=datetime.strptime(day+' '+hhmm,'%Y%m%d %H:%M').replace(tzinfo=JST)
        if (known_at-now()).total_seconds()<0:
            # A completed input already has its original timestamped pages.
            # Do not refetch it as a supposed new pre-race observation.
            for target in (600,300,180):
                path=store.root/'odds_targets'/day/(key+f'_{target}.json')
                if not path.exists():once(path,encode({'race_id':key,'target_seconds':target,'status':'missed','recorded_at':stamp(),'missing_reason':'collector first started after target; no historical acquisition receipt'}))
            return {'race_id':key,'status':'reused_completed_original','http_requests':0}
    card=store.get(url('racelist',day,code,rno),ttl=300)
    if card['status']!='ok':return {'race_id':key,'status':'missing_card','reason':card.get('missing_reason')}
    raw=store.body(card);boats=program(raw)
    if len(boats)!=6:return {'race_id':key,'status':'unpublished_or_no_race','program_boats':len(boats)}
    hhmm=deadline(raw,rno);at=datetime.strptime(day+' '+hhmm,'%Y%m%d %H:%M').replace(tzinfo=JST)
    remaining=(at-now()).total_seconds()
    store.record('programs',key,{'race_id':key,'day':day,'venue_code':code,'race_no':rno,'deadline':hhmm,'acquisition':card,'data':boats,'usage':'predeadline' if remaining>0 else 'retrospective'})
    frozen=store.root/'fusion_inputs'/(key+'.json')
    # The input freeze and three model cards are created in a result-free phase.
    if 0<=remaining<=1200:
        # Main-core requires two contemporaneous pages; cached roster must be
        # renewed rather than mixing an old roster with a new preview.
        card=store.get(url('racelist',day,code,rno),ttl=60);raw=store.body(card);boats=program(raw)
        before=store.get(url('beforeinfo',day,code,rno),ttl=45)
        if before['status']=='ok':
            pr=preview(store.body(before));store.record('previews',key,{'race_id':key,'day':day,'venue_code':code,'race_no':rno,'deadline':hhmm,'acquisition':before,'data':pr,'usage':'predeadline'})
            if remaining>=180 and not frozen.exists() and pr['exhibition_count']==6 and pr['entry_observed']:
                for b in boats:b.update(pr['boats'][b['lane']]);b.update(course=b['predicted_course'],exhibition_st=b.get('exhibition_st_timing'))
                captured=stamp();snapshot={'meta':{'day':day,'jcd':code,'rno':rno,'deadline':hhmm,'captured_at':captured},'boats':boats,
                    'environment':{k:v for k,v in pr.items() if k!='boats'},
                    'official_originals':{k:{'html':store.body(d),'url':d['url'],'sha256':d['sha256'],'observed_at':d['retrieved_at']} for k,d in [('racelist',card),('beforeinfo',before)]}}
                from research.venue_fusion_v1.prospective import build_live,save_local_only
                result=build_live(snapshot)
                once(frozen,encode(snapshot));save_local_only(result,store.root/'fusion_forecasts'/(key+'.json'))
                # Persist all six explanations from the same pinned engines;
                # they remain hypotheses until a separate video review.
                from research.venue_fusion_v1.official_program import from_frozen_official
                from research.venue_fusion_v1 import engine as hybrid
                from prediction_engine import analyze_race
                main=analyze_race(from_frozen_official(snapshot)['payload'])
                lanes=hybrid._build_with_ranking(snapshot,hybrid._ordered_cards(main['trifecta']),mode='live',now=stamp())
                once(store.root/'fusion_scenarios'/(key+'.json'),encode({'race_id':key,'input_digest':result['input_digest'],'generated_at':stamp(),'lanes':lanes['lanes'],'formations':lanes['formation_candidates'],'actual_attack_verified':False}))
                if code=='23':
                    from .supplement import collect_live_karatsu
                    collect_live_karatsu(store,snapshot)
    if day==now().strftime('%Y%m%d'):
        for target in (600,300,180):
            goal=store.root/'odds_targets'/day/(key+f'_{target}.json')
            if goal.exists():continue
            if target<=remaining<=target+35:
                oddsdoc=store.get(url('odds3t',day,code,rno),ttl=0)
                record={'race_id':key,'target_seconds':target,'deadline_at':at.isoformat(),'acquisition':oddsdoc,'status':'missing'}
                try:
                    if oddsdoc['status']!='ok':raise ValueError(oddsdoc.get('missing_reason'))
                    record['odds']=parse_odds(store.body(oddsdoc));record['remaining_seconds_at_receipt']=(at-aware(oddsdoc['retrieved_at'])).total_seconds()
                    if record['remaining_seconds_at_receipt']<0:raise ValueError('Market received after cutoff')
                    if abs(record['remaining_seconds_at_receipt']-target)>45:raise ValueError('Outside +/-45 second target window; retain raw but do not call it target odds')
                    record['status']='ok'
                except Exception as exc:record['missing_reason']=str(exc)
                once(goal,encode(record))
            elif remaining<target:
                once(goal,encode({'race_id':key,'target_seconds':target,'status':'missed','recorded_at':stamp(),'missing_reason':'target passed before this independent collector acquired market; never reconstruct historical odds'}))
    # No result is requested while creating any input/forecast. Separate files,
    # separate parsing, and after the official deadline only.
    if allow_result and remaining < -180 and not (store.root/'results'/(key+'.json')).exists():
        res=store.get(url('raceresult',day,code,rno),ttl=300)
        if res['status']=='ok':
            body=store.body(res);payout=parsers.parse_payout(body)
            if payout['status']!='pending':
                try:details=parsers.parse_result(body,day,code,rno)
                except ValueError:details=None
                record={'race_id':key,'day':day,'venue_code':code,'race_no':rno,'acquisition':res,'payout':payout,'details':details,'usage':'outcome_only','preview_input_allowed':False}
                store.record('result_versions',key,record)
                if details:once(store.root/'results'/(key+'.json'),encode(record))
                store.record('result_weather',key,{'race_id':key,'acquisition':res,'data':result_environment(body),'phase':'result','usage':'outcome_only'})
    return {'race_id':key,'status':'captured','remaining_seconds':round(remaining),'frozen':frozen.exists()}

def grade(store):
    totals={};rows=[]
    for p in (store.root/'fusion_forecasts').glob('*.json'):
        f=read(p);receipt=store.root/'remote_receipts'/(p.stem+'.json');result=store.root/'results'/p.name
        if not receipt.exists() or not result.exists():continue
        rc=read(receipt);r=read(result)
        if not rc.get('confirmed_before_deadline') or rc.get('forecast_sha256')!=digest(p.read_bytes()):continue
        d=r.get('details');pay=r['payout']
        if not d or pay['status']!='settled' or pay['refund_lanes'] or any(b['status']!='finished' for b in d['finish']):continue
        row={'race_id':p.stem,'receipt':rc,'models':{}}
        for name,card in f['model_cards'].items():
            hit=d['trifecta'] in card;returned=d['payout_per_100'] if hit else 0
            v=totals.setdefault(name,{'races':0,'hits':0,'stake_yen':0,'return_yen':0})
            v['races']+=1;v['hits']+=hit;v['stake_yen']+=1000;v['return_yen']+=returned
            row['models'][name]={'hit':hit,'return_yen':returned}
        rows.append(row)
    for v in totals.values():v['roi_pct']=round(100*v['return_yen']/v['stake_yen'],2)
    output={'generated_at':stamp(),'prospective_graded_races':len(rows),'models':totals,'rows':rows,'promote_to_production':False,'minimum_forward_gate':'100R then 300R, calendar-separated; no automatic adoption'}
    write(store.root/'reports/prospective.json',output);return output

def main():
    p=argparse.ArgumentParser();p.add_argument('--state',required=True,type=Path);p.add_argument('--reuse',type=Path);p.add_argument('--source-sha',default='unknown');p.add_argument('--day',default=now().strftime('%Y%m%d'));p.add_argument('--venues',default='03,06,16,23');p.add_argument('--races',default='1,2,3,4,5,6,7,8,9,10,11,12');p.add_argument('--reuse-only',action='store_true')
    a=p.parse_args();store=Store(a.state);start=stamp();reused=import_existing(store,a.reuse,a.source_sha) if a.reuse else None
    if a.reuse:import_existing_results(store,a.reuse,a.source_sha)
    rows=[]
    if not a.reuse_only:
        for code in a.venues.split(','):
            for rno in map(int,a.races.split(',')):
                try:rows.append(capture(store,a.day,code,rno))
                except Exception as exc:rows.append({'day':a.day,'venue_code':code,'race_no':rno,'status':'error','reason':str(exc)})
    graded=grade(store);record={'started_at':start,'completed_at':stamp(),'http_requests':store.fetches,'reuse':reused,'captures':rows,'prospective_graded':graded['prospective_graded_races']}
    store.record('runs','collection',record);print(json.dumps(record,ensure_ascii=False))

if __name__=='__main__':main()
