"""Official predicted tide tables and venue-specific original foot measurements."""
import argparse,gzip,json,re
from pathlib import Path
from urllib.parse import urljoin
from datetime import timedelta
from .collector import Store,read,write,encode,once,stamp,parsers,digest,now,url

def tides(raw,station):
    # JMA annual fixed-width prediction format: 24 x 3 hourly cm,
    # YY MM DD station, four highs then four lows, hhmm + height (3).
    lines=raw.splitlines();hourly=[];events=[]
    for line in lines:
        if not line.strip():continue
        if len(line)!=136:raise ValueError('Unexpected JMA annual prediction width '+str(len(line)))
        if line[78:80]!=station:raise ValueError('Prediction station mismatch')
        date=f"{2000+int(line[72:74]):04d}-{int(line[74:76]):02d}-{int(line[76:78]):02d}"
        from datetime import datetime
        d=datetime.strptime(date,'%Y-%m-%d').replace(tzinfo=__import__('zoneinfo').ZoneInfo('Asia/Tokyo'))
        for h in range(24):
            v=line[h*3:h*3+3]
            hourly.append({'station':station,'at':(d+timedelta(hours=h)).isoformat(),'height_cm':int(v) if v.strip() else None,'measurement':'astronomical_prediction','datum':'local_tide_prediction_datum','venue_measurement':False,'current_velocity':False})
        for i in range(8):
            cell=line[80+i*7:87+i*7];hhmm=cell[:4];height=cell[4:]
            if hhmm.strip() and hhmm.strip() not in ('9999','----'):
                try:hour,minute=int(hhmm[:2]),int(hhmm[2:])
                except ValueError:continue
                if hour>23 or minute>59:continue
                events.append({'station':station,'at':d.replace(hour=hour,minute=minute).isoformat(),'kind':'high' if i<4 else 'low','height_cm':int(height),'measurement':'astronomical_prediction'})
    return hourly,events

def karatsu_foot(raw):
    tables=re.findall(r'<table\b[^>]*class=["\x27][^"\x27]*oriten[^"\x27]*["\x27][^>]*>(.*?)</table>',raw,re.S|re.I)
    rows=[]
    for table in tables:
        for tr in re.findall(r'<tr\b[^>]*>(.*?)</tr>',table,re.S|re.I):
            cells=[parsers.clean(x) for x in re.findall(r'<td\b[^>]*>(.*?)</td>',tr,re.S|re.I)]
            if len(cells)!=8 or cells[0] not in list('123456'):continue
            def n(i):return float(cells[i]) if re.fullmatch(r'-?\d+(?:\.\d+)?',cells[i]) else None
            rows.append({'lane':int(cells[0]),'exhibition_time':n(3),'lap_time':n(4),'turn_time':n(5),'straight_time':n(6),'venue_rating':n(7)})
    if len(rows)!=6:raise ValueError('No complete current Karatsu original measurements')
    return rows

def import_probe(store,folder):
    result=[]
    for p in sorted(Path(folder).glob('*.json')):
        meta=read(p);key=p.stem
        bodies=[x for x in p.parent.glob(key+'.*') if x.suffix!='.json']
        if len(bodies)!=1:continue
        doc=store.document(bodies[0].read_bytes(),{'url':meta['url'],'retrieved_at':meta['retrieved_at'],'requested_at':None,'http_status':200,'status':'ok','source_family':'JMA' if 'jma' in key else 'BOATRACE_official','published_at':None,'last_modified':meta.get('headers',{}).get('Last-Modified')})
        if key.startswith('jma_annual_'):
            station=key.rsplit('_',1)[1];h,e=tides(bodies[0].read_text(),station)
            once(store.root/'tide_predictions'/(station+'_2026.json.gz'),gzip.compress(encode({'acquisition':doc,'hourly':h,'events':e,'usage':'research only; acquired now, no historical predeadline receipt','station_proxy':True}),mtime=0))
            result.append({'key':key,'hourly':len(h),'extrema':len(e),'acquisition':doc})
        elif key=='karatsu_foot':
            raw=bodies[0].read_text();rows=karatsu_foot(raw)
            store.record('original_foot','20261020_23_12',{'race_id':'20261020_23_12','day':'20261020','venue_code':'23','race_no':12,'acquisition':doc,'data':rows,'usage':'retrospective; retrieved after deadline','source_published_at':None,'measurement_diagram_url':'https://www.boatrace-karatsu.jp/sp/page/yosou/images/img-s03-modal.png','measurement_intervals':'Official diagram retained; no cross-venue numeric comparison'})
            # Each current lane comment remains an attributed short data item;
            # full histories remain only in source evidence, not fabricated.
            text=parsers.textify(raw);section=text.split('選手コメント\n枠\n選手コメント',1)[-1]
            comments=[]
            for m in re.finditer(r'\n([1-6])\n([^\n]+)\n([^\n]+)選手のコメント履歴',section):
                comments.append({'lane':int(m[1]),'comment':m[2],'name':m[3],'source_date':'2026-10-20','retrieved_at':doc['retrieved_at'],'published_at':None,'predictive_input_allowed':False})
            store.record('comments','20261020_23_12',{'race_id':'20261020_23_12','acquisition':doc,'rows':comments})
            result.append({'key':key,'foot_boats':len(rows),'comments':len(comments),'acquisition':doc})
        else:result.append({'key':key,'acquisition':doc,'structured_status':'source evidence only; no invented measurements'})
    write(store.root/'reports/supplement.json',{'checked_at':stamp(),'sources':result});return result

def refresh_daily(store):
    day=now().strftime('%Y%m%d');result=[]
    sources={
        'hamanako_preinspection':'https://www.boatrace-hamanako.jp/modules/raceinfo/?page=index_timerank',
        'karatsu_preinspection':'https://www.boatrace-karatsu.jp/modules/raceinfo/?page=index_timerank',
        'kojima_preinspection':'https://www.kojimaboat.jp/01motor/01motor.htm',
        'edogawa_preinspection':'https://www.boatrace-edogawa.com/sp/index.php?page=raceinfo-motor_cyusen'}
    for key,u in sources.items():
        doc=store.get(u,ttl=1800);entry={'key':key,'acquisition':doc,'checked_at':stamp()}
        if doc['status']=='ok':
            body=store.body(doc)
            entry['status']='waiting_publication' if '次節開催までしばらくお待ちください' in body else 'raw_saved_requires_series_identity'
            entry['missing_reason']='current table not published' if entry['status']=='waiting_publication' else 'must match series, racer and motor before joining'
        store.record('preinspection_checks',day+'_'+key,entry);result.append(entry)
    return result

def complete_results(store,old,day):
    result=[]
    for p in sorted((Path(old)/'inputs'/day).glob('*.json')):
        snap=read(p);m=snap['meta'];key=p.stem;destination=store.root/'results'/(key+'.json')
        if destination.exists():continue
        from datetime import datetime
        at=datetime.strptime(day+' '+m['deadline'],'%Y%m%d %H:%M').replace(tzinfo=now().tzinfo)
        if (now()-at).total_seconds()<180:continue
        doc=store.get(url('raceresult',day,m['jcd'],m['rno']),ttl=600)
        if doc['status']!='ok':result.append({'race_id':key,'status':'unavailable'});continue
        raw=store.body(doc);pay=parsers.parse_payout(raw)
        try:
            details=parsers.parse_result(raw,day,m['jcd'],m['rno'])
            # Six actual entrants must match the original pre-race roster.
            ids={int(b['lane']):str(b['racer_id']) for b in snap['boats']}
            if any(ids[b['lane']]!=b['racer_id'] for b in details['finish']):raise ValueError('Outcome/original roster conflict')
            record={'race_id':key,'day':day,'venue_code':m['jcd'],'race_no':m['rno'],'acquisition':doc,'payout':pay,'details':details,'usage':'outcome_only','predictive_input_allowed':False}
            once(destination,encode(record))
            store.record('result_weather',key,{'race_id':key,'acquisition':doc,'data':__import__('research.materials_v1.collector',fromlist=['preview']).preview(raw),'usage':'outcome_only'})
            result.append({'race_id':key,'status':'complete','boats':6})
        except Exception as exc:result.append({'race_id':key,'status':'details_missing','missing_reason':str(exc)})
    store.record('runs','complete_results',{'checked_at':stamp(),'day':day,'records':result});return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--state',required=True);p.add_argument('--probes');p.add_argument('--daily',action='store_true');a=p.parse_args();s=Store(a.state)
    if a.probes:print(json.dumps(import_probe(s,a.probes),ensure_ascii=False))
    if a.daily:print(json.dumps(refresh_daily(s),ensure_ascii=False))
