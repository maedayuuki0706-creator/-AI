"""Official-only bounded GETs. Independent of all production delivery modules."""
from datetime import datetime,timedelta
from hashlib import sha256
from pathlib import Path
import argparse,json,re,time,urllib.parse,urllib.request
from . import parsers
from ..core import fit,predict
from research.ultimate_fusion_v1 import engine as e
BASE='https://www.boatrace.jp/owpc/pc/race/'
PREFIX='data/ultimate_fusion_forward_v2'

def url(kind,day,code=None,rno=1):
    datetime.strptime(day,'%Y%m%d')
    if kind not in ('index','racelist','beforeinfo','odds3t'):raise ValueError('unsupported_endpoint')
    q={'hd':day}
    if code is not None:
        e.identity(day,code,rno);q.update(jcd=str(code).zfill(2),rno=int(rno))
    return BASE+kind+'?'+urllib.parse.urlencode(q)

class Client:
    def __init__(self,clock=None):self.clock=clock or (lambda:datetime.now(e.JST));self.last=0
    def read(self,kind,day,code=None,rno=1):
        target=url(kind,day,code,rno);pause=2-(time.monotonic()-self.last)
        if pause>0:time.sleep(pause)
        self.last=time.monotonic();start=self.clock()
        req=urllib.request.Request(target,headers={'User-Agent':'BoatAI-Independent-Research/2.0','Accept-Language':'ja'})
        with urllib.request.urlopen(req,timeout=12) as res:
            if res.geturl()!=target:raise ValueError('unexpected_redirect')
            body=res.read(2_000_001)
        if len(body)>2_000_000:raise ValueError('response_too_large')
        return {'url':target,'requested_at':e.aware(start).isoformat(),'retrieved_at':e.aware(self.clock()).isoformat(),
                'published_at':None,'body_sha256':sha256(body).hexdigest(),'html':body.decode('utf-8',errors='strict')}

def deadlines(html):
    text=parsers.textify(html);pos=text.find('締切予定時刻')
    if pos<0:raise ValueError('official_deadlines_missing')
    values=re.findall(r'(?:[01]?\d|2[0-3]):[0-5]\d',text[pos:pos+900])
    if len(values)<12:raise ValueError('official_deadlines_incomplete')
    return [f'{int(v.split(":")[0]):02}:{v.split(":")[1]}' for v in values[:12]]

def freeze(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    body=json.dumps(obj,ensure_ascii=False,sort_keys=True,allow_nan=False)+'\n'
    try:
        with path.open('x',encoding='utf-8') as f:f.write(body)
    except FileExistsError:
        if path.read_text()!=body:raise ValueError('immutable_file_conflict')
    return path

def assemble(day,code,rno,pages,history,now):
    now=e.aware(now);key=e.identity(day,code,rno)
    if now.strftime('%Y%m%d')!=day:raise ValueError('not_today')
    for kind in ('racelist','beforeinfo','odds3t'):
        p=pages[kind];taken=e.aware(p['retrieved_at'])
        if p['url']!=url(kind,day,code,rno):raise ValueError('source_race_mismatch')
        if p['body_sha256']!=sha256(p['html'].encode()).hexdigest():raise ValueError('raw_body_tampered')
        if not e.aware(p['requested_at'])<=taken<=now or (now-taken).total_seconds()>180:raise ValueError('source_time_invalid')
    deadline=deadlines(pages['racelist']['html'])[int(rno)-1]
    if any(deadlines(pages[k]['html'])[int(rno)-1]!=deadline for k in ('beforeinfo','odds3t')):raise ValueError('deadline_disagreement')
    if now>e._deadline(day,deadline)-timedelta(minutes=3):raise ValueError('too_late_to_predict')
    boats=parsers.parse_racelist_boats(pages['racelist']['html']);e.boats_six(boats)
    preview=parsers.parse_beforeinfo(pages['beforeinfo']['html'])
    if preview.get('exhibition_count')!=6 or not preview.get('entry_observed'):raise ValueError('exhibition_not_ready')
    odds=parsers.parse_odds(pages['odds3t']['html'])
    if set(odds)!=set(e.COMBOS):raise ValueError('incomplete_official_odds')
    rows=[];obs=[]
    for b in boats:
        v=preview['boats'][b['lane']]
        rows.append({**{k:b.get(k) for k in ('lane','racer_id','name','motor_number','boat_number')},
                     'exhibition_course':v.get('predicted_course'),'exhibition_time':v.get('exhibition_time'),
                     'exhibition_st':v.get('exhibition_st_timing'),'tilt':v.get('tilt'),
                     'wind_m':preview.get('wind_speed'),'wave_cm':preview.get('wave_cm')})
        for field,keyname in [('national_win_rate','win_rate'),('local_win_rate','local_win_rate'),('avg_st','avg_st')]:
            if b.get(keyname) is not None:
                p=pages['racelist'];obs.append({'race_id':key,'lane':b['lane'],'racer_id':b['racer_id'],
                    'field':field,'value':b[keyname],'source_url':p['url'],'retrieved_at':p['retrieved_at'],
                    'available_at':p['retrieved_at'],'published_at':None})
    snap=e.prepare_live({'day':day,'jcd':code,'rno':int(rno),'deadline':deadline,'captured_at':now.isoformat(),'rows':rows},observed_at=now)
    model=fit(history,day,str(code).zfill(2))
    if model['training_races']<30:raise ValueError('insufficient_training_history')
    report=predict(snap,model,obs,now=now.isoformat())
    for row in report['trifecta']:row['official_odds']=odds[row['combination']]
    report['odds_provenance']={k:v for k,v in pages['odds3t'].items() if k!='html'}
    report['sha256']=e.digest({k:v for k,v in report.items() if k!='sha256'})
    bundle={'schema':'ultimate-fusion-capture-v1','race_id':key,'created_at':now.isoformat(),
            'deadline_at':snap['deadline_at'],'status':'prospective_uncheckpointed','report':report,
            'pages':pages,'training_model':model}
    bundle['sha256']=e.digest(bundle);return bundle

def pilot(history_root,out,client=None):
    client=client or Client();day=client.clock().strftime('%Y%m%d')
    history=[json.loads(p.read_text()) for p in Path(history_root).rglob('*.json')]
    index=client.read('index',day);codes=sorted(set(re.findall(r'(?:\?|&amp;|&)jcd=(\d{2})',index['html']))&e.VENUE_CODES)
    attempts=[]
    # At most 24 card reads and two candidate captures; stops after one successful bundle.
    tried=0
    for code in codes:
        try:
            card=client.read('racelist',day,code);now=client.clock()
            candidates=[i for i,t in enumerate(deadlines(card['html']),1) if timedelta(minutes=5)<e._deadline(day,t)-now<timedelta(minutes=25)]
            if not candidates:continue
            rno=candidates[0];key=e.identity(day,code,rno);path=Path(out)/PREFIX/'captures'/day/(key+'.json')
            if path.exists():continue
            tried+=1
            pages={k:client.read(k,day,code,rno) for k in ('racelist','beforeinfo','odds3t')}
            bundle=assemble(day,code,rno,pages,history,client.clock());freeze(path,bundle)
            attempts.append({'status':'captured_uncheckpointed','race_id':key,'path':str(path),'sha256':bundle['sha256']});break
        except Exception as exc:attempts.append({'venue':code,'status':'not_captured','reason':str(exc)[:200]})
        if tried>=2:break
    return {'day':day,'checked_at':client.clock().isoformat(),'attempts':attempts,'venues_listed':codes,
            'status':'captured_uncheckpointed' if any(x['status']=='captured_uncheckpointed' for x in attempts) else 'no_eligible_capture','pilot_only':True}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--history-root',default='data/exhibition_log');p.add_argument('--out',required=True);p.add_argument('--audit',required=True);a=p.parse_args()
    try:result=pilot(a.history_root,a.out)
    except Exception as exc:result={'status':'acquisition_failed','reason':str(exc)[:250]}
    freeze(a.audit,result);print(json.dumps(result,ensure_ascii=False))
