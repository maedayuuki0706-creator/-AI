"""One-off official gap acquisition. All output remains retrospective research.

No production imports, schedulers, predictions, odds decisions, or notifications.
JMA station heights are nearby proxies, not racecourse current measurements.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import gzip
from html import unescape
import json
from pathlib import Path
import re
import threading
import time
import urllib.request

from .collect import JST, atomic, digest, encode, load_baseline, save_json, stamp

STATIONS = {'03': ('TK', '東京'), '16': ('UN', '宇野'), '06': ('MI', '舞阪')}
URLS = {
    'jma_explanation': 'https://www.data.jma.go.jp/kaiyou/db/tide/genbo/explanation.html',
    'jma_format': 'https://www.data.jma.go.jp/kaiyou/db/tide/genbo/format.html',
    'jma_stations': 'https://www.data.jma.go.jp/kaiyou/db/tide/genbo/station.php',
    'motor_edogawa': 'https://www.boatrace-edogawa.com/sp/index.php?page=raceinfo-motor_seiseki',
    'motor_edogawa_2025': 'https://www.boatrace-edogawa.com/uploads/pdf/edo20251005.pdf',
    'motor_edogawa_2026_pdf': 'https://www.boatrace-edogawa.com/uploads/pdf/edo20261007.pdf',
    'motor_hamanako': 'https://www.boatrace-hamanako.jp/sp/index.php?page=datafile-motorrank',
    'motor_hamanako_2025': 'https://boatrace-hamanako.jp/uploads/cdn/news/001951/20260130_monthly.pdf',
    'motor_hamanako_maintenance': 'https://www.boatrace-hamanako.jp/uploads/cdn/pdf/motorpdf/chukanseibi/chukanseibi.pdf',
    'motor_karatsu': 'https://www.boatrace-karatsu.jp/modules/datafile/',
    'motor_karatsu_2025': 'https://www.boatrace-karatsu.jp/uploads/monthly/monthly_202601.pdf',
    'motor_kojima_2025': 'https://www.kojimaboat.jp/00info/2025.htm',
    'motor_kojima_2024': 'https://www.kojimaboat.jp/00info/2024.htm',
    'preinspection_kojima': 'https://www.kojimaboat.jp/01motor/01motor.htm',
    'preinspection_karatsu': 'https://www.boatrace-karatsu.jp/modules/raceinfo/?page=index_timerank',
    'preinspection_hamanako': 'https://www.boatrace-hamanako.jp/modules/raceinfo/?page=index_timerank',
    'preinspection_edogawa': 'https://www.boatrace-edogawa.com/sp/index.php?page=raceinfo-motor_cyusen',
    'edogawa_calendar': 'https://www.boatrace-edogawa.com/sp/index.php?page=raceinfo-index',
    'edogawa_series': 'https://www.boatrace-edogawa.com/sp/index.php?page=yosou-race_index',
}


class Evidence:
    """Content-addressed official raw evidence and immutable acquisition receipts."""
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.Lock()
        self.next_request = 0.

    def cached(self, key):
        path=self.root/'sources'/(key+'.json')
        if not path.is_file():return {'key':key,'status':'not_acquired'}, None
        meta=json.loads(path.read_bytes())
        if meta['status']!='ok':return meta,None
        body=gzip.decompress((self.root/meta['raw_path']).read_bytes())
        if digest(body)!=meta['sha256']:raise ValueError('Cached gap evidence mismatch')
        return meta,body

    def read(self, key, url, seed=None):
        index = self.root/'sources'/(key+'.json')
        if index.exists():
            m = json.loads(index.read_bytes())
            if m['status'] == 'ok':
                b = gzip.decompress((self.root/m['raw_path']).read_bytes())
                if digest(b) != m['sha256']:
                    raise ValueError('Gap evidence SHA mismatch')
                return m, b
            return m, None
        m = {'key': key, 'url': url, 'observed_at': stamp(), 'official': True,
             'prospective_verified': False, 'status': 'unavailable'}
        try:
            if seed and Path(seed).is_file():
                b = Path(seed).read_bytes()
                m['observed_at'] = datetime.fromtimestamp(Path(seed).stat().st_mtime, JST).isoformat()
                m['imported_verified_probe'] = True
            else:
                with self.lock:
                    wait = max(0., self.next_request-time.monotonic())
                    if wait: time.sleep(wait)
                    self.next_request = time.monotonic()+1.
                req = urllib.request.Request(url, headers={'User-Agent': 'BoatAI-DataResearch/1.0'})
                with urllib.request.urlopen(req, timeout=35) as r:
                    b = r.read(16_000_001)
                    m['final_url'] = r.geturl()
                    m['last_modified'] = r.headers.get('Last-Modified')
            if not b or len(b) > 16_000_000:
                raise ValueError('Empty/oversized gap evidence')
            sha = digest(b)
            m.update(status='ok', sha256=sha, bytes=len(b), raw_path='raw/'+sha+'.gz')
            atomic(self.root/m['raw_path'], gzip.compress(b, mtime=0))
        except Exception as e:
            b = None
            m.update(error_type=type(e).__name__, error=str(e)[:250])
        save_json(self.root/'receipts'/(key+'_'+digest(encode(m))[:16]+'.json'), m)
        save_json(index, m)
        return m, b


def hourly_url(year, month, station):
    ym = f'{year:04}{month:02}'
    if ym <= '202608':
        return f'https://www.data.jma.go.jp/kaiyou/data/db/tide/genbo/{year}/{ym}/hry{ym}{station}.txt', 'final'
    return f'https://www.data.jma.go.jp/kaiyou/data/db/tide/sokuho/{ym}/z_hry{ym}{station}.txt', 'provisional'


def parse_hourly(body, year, month, station):
    """JMA fixed-width 0..23 JST; blank missing, 0 valid. No datum conversion."""
    out = {}
    for line in body.decode('ascii').splitlines():
        if not line.strip(): continue
        if len(line) not in (80, 136):
            raise ValueError(f'Unexpected hourly line width {len(line)}')
        yy, mm, dd = (int(line[a:b]) for a,b in ((72,74),(74,76),(76,78)))
        if (yy,mm,line[78:80]) != (year%100, month, station):
            raise ValueError('JMA station/month identity mismatch')
        day = datetime(year,mm,dd,tzinfo=JST)
        for hour in range(24):
            cell = line[hour*3:hour*3+3]
            value = int(cell) if cell.strip() else None
            if value is not None and not -999 < value < 999:
                raise ValueError('Invalid tide height')
            key = (day+timedelta(hours=hour)).isoformat()
            if key in out: raise ValueError('Duplicate station hour')
            out[key] = value
    if not out: raise ValueError('No hourly observations')
    return out


def clean(html):
    return ' '.join(unescape(re.sub(r'<[^>]*>', ' ', html)).split())


def parse_preinspection(body, venue):
    raw = body.decode('utf-8')
    if '次節開催までしばらくお待ちください' in clean(raw): return []
    result = []
    for tr in re.findall(r'<tr\b[^>]*>(.*?)</tr>', raw, re.S|re.I):
        cells = [clean(c) for c in re.findall(r'<td\b[^>]*>(.*?)</td>',tr,re.S|re.I)]
        if venue == '16' and len(cells) == 10:
            number = re.search(r'touban=(\d{4})',tr)
            if not number or not cells[1].isdigit(): continue
            racer,motor,timing = number[1],int(cells[1]),float(cells[3])
            if racer not in cells[2]: raise ValueError('Kojima racer identity mismatch')
        elif venue == '23' and len(cells)==10 and re.fullmatch(r'\d{4}',cells[1]):
            number = re.search(r'toban=(\d{4})',tr)
            if not number or number[1] != cells[1]: raise ValueError('Karatsu racer identity mismatch')
            racer,motor,timing = cells[1],int(cells[4]),float(cells[9])
        elif venue == '03' and len(cells)==7 and re.fullmatch(r'\d{4}',cells[0]):
            racer,motor,timing = cells[0],int(cells[2]),float(cells[6])
        else: continue
        if not 5 < timing < 10 or not 1 <= motor <= 999:
            raise ValueError('Invalid preinspection observation')
        result.append({'racer_id':racer,'motor_number':motor,'preinspection_time':timing})
    if len(result)<6 or len({x['racer_id'] for x in result}) != len(result):
        raise ValueError('Unverified/incomplete preinspection table')
    return result


def months(start, end):
    y,m=map(int,start[:7].split('-')); last=tuple(map(int,end[:7].split('-')))
    while (y,m)<=last:
        yield y,m
        y,m=(y+1,1) if m==12 else (y,m+1)


def link_tide(race, observation_map, baseline=None):
    venue=race['venue_code']
    if venue not in STATIONS: return None, 'freshwater_tide_not_applicable'
    day=race['day']
    scheduled=(baseline or {}).get('deadline_scheduled')
    if scheduled:
        when=datetime.fromisoformat(day+'T'+scheduled).replace(tzinfo=JST)
        anchor_source='official_program_scheduled_deadline'
    elif race.get('closed_at'):
        when=datetime.fromisoformat(race['closed_at'])
        when=when.replace(tzinfo=JST) if when.tzinfo is None else when.astimezone(JST)
        if when.date().isoformat()!=day: raise ValueError('Deadline day mismatch')
        anchor_source='archived_api_closed_at_not_actual_start'
    else: return None, 'deadline_unavailable'
    at=when.replace(minute=0,second=0,microsecond=0)
    station,name=STATIONS[venue]
    value=observation_map.get(station,{}).get(at.isoformat())
    if value is None or value['height_cm'] is None:
        return None, 'station_hour_missing_or_not_yet_published'
    return {**value,'station':station,'station_name':name,'anchor':when.isoformat(),
            'anchor_source':anchor_source,'age_minutes':(when-at).total_seconds()/60,
            'proxy_for_venue':True,'venue_point_measurement':False,
            'measurement':'smoothed_observed_height_above_local_gauge_datum_cm',
            'prospective_verified':False,'release_delayed_until_following_day_or_later':True}, 'linked_station_proxy'


def link_motor(race, catalog):
    candidates=[x for x in catalog if x['venue_code']==race['venue_code']
                and x['valid_from']<=race['day']<=x['valid_through']]
    if len(candidates)>1: raise ValueError('Overlapping motor cycles')
    if not candidates: return None
    fact=candidates[0]
    return {**fact,'motor_keys':[f"{race['venue_code']}:{fact['cycle_id']}:{b['motor_number']}"
                                 if b['motor_number'] is not None else None for b in race['boats']],
            'individual_motor_first_use_date_verified':False}


def enrich(data, motor_catalog, series_catalog):
    data=Path(data); root=data/'gaps'; cache=Evidence(root)
    observations={};errors=[];source_counts={}
    for y,m in months('2025-10-18','2026-10-19'):
        for st,name in STATIONS.values():
            key=f'jma_{y:04}{m:02}_{st}';url,quality=hourly_url(y,m,st)
            meta,body=cache.cached(key)
            if body is None:
                errors.append({'key':key,'error':'source_unavailable'});continue
            try: parsed=parse_hourly(body,y,m,st)
            except ValueError as exc:
                errors.append({'key':key,'error':str(exc)});continue
            station=observations.setdefault(st,{})
            for at,value in parsed.items():
                if not '2025-10-18'<=at[:10]<='2026-10-19':continue
                station[at]={'height_cm':value,'observation_time':at,'quality':quality,
                             'source_sha256':meta['sha256'],'source_key':key}
            source_counts[key]={'quality':quality,'hours':len(parsed),
                               'present':sum(v is not None for v in parsed.values())}
    atomic(root/'station_observations.json.gz',gzip.compress(encode(observations),mtime=0))
    motors=json.loads(Path(motor_catalog).read_bytes())
    for fact in motors:
        for reference in fact['references']:
            meta=json.loads((root/'sources'/(reference['key']+'.json')).read_bytes())
            if meta.get('sha256')!=reference['sha256']:
                raise ValueError('Motor date claim needs its reviewed source hash')
    save_json(root/'motor_cycles.json',motors)
    series=json.loads(Path(series_catalog).read_bytes()); preinspection=[]
    for profile in series:
        key=profile['source_key'];meta,body=cache.cached(key)
        if body is None: continue
        if meta['sha256']!=profile['source_sha256']:
            raise ValueError('Series bounds need the reviewed source hash')
        for reference in profile.get('calendar_references',[]):
            if cache.cached(reference['key'])[0].get('sha256')!=reference['sha256']:
                raise ValueError('Series calendar evidence mismatch')
        rows=parse_preinspection(body,profile['venue_code'])
        preinspection.append({**profile,'observed_at':meta['observed_at'],'rows':rows,
                              'prospective_verified':False})
    save_json(root/'preinspection_series.json',preinspection)
    baseline,_=load_baseline();records=[];unmatched=[]
    counts={'races':0,'station_proxy_linked_races':0,'freshwater_tide_not_applicable_races':0,
            'station_proxy_missing_races':0,'motor_cycle_linked_races':0,'motor_exact_fleet_start_races':0,
            'motor_month_precision_races':0,'motor_conflicting_start_races':0,
            'preinspection_matched_boats':0,'preinspection_six_boat_matched_races':0}
    per_venue={}
    for path in sorted((data/'days').glob('*.json.gz')):
        for race in json.loads(gzip.decompress(path.read_bytes()))['races']:
            counts['races']+=1
            tide,status=link_tide(race,observations,baseline.get(race['race_id']))
            counts['station_proxy_linked_races']+=tide is not None
            counts['freshwater_tide_not_applicable_races']+=status=='freshwater_tide_not_applicable'
            counts['station_proxy_missing_races']+=status not in ('linked_station_proxy','freshwater_tide_not_applicable')
            venue=per_venue.setdefault(race['venue_code'],{'races':0,'station_proxy_linked':0,'preinspection_boats':0})
            venue['races']+=1;venue['station_proxy_linked']+=tide is not None
            motor=link_motor(race,motors)
            counts['motor_cycle_linked_races']+=motor is not None
            if motor:
                counts['motor_exact_fleet_start_races']+=motor['start_precision']=='day'
                counts['motor_month_precision_races']+=motor['start_precision']=='month'
                counts['motor_conflicting_start_races']+=motor['start_precision']=='conflicting_days'
            matched=[]
            for series in preinspection:
                if series['venue_code']!=race['venue_code'] or not series.get('join_verified'):continue
                if not series['first_day']<=race['day']<=series['last_day']:continue
                index={r['racer_id']:r for r in series['rows']}
                for boat in race['boats']:
                    found=index.get(boat['racer_id'])
                    if found and found['motor_number']==boat['motor_number']:
                        matched.append({**found,'lane':boat['lane'],'source_sha256':series['source_sha256'],
                                        'series_first_day':series['first_day'],
                                        'captured_after_historical_race':True})
                    else:
                        unmatched.append({'race_id':race['race_id'],'lane':boat['lane'],
                            'racer_id':boat['racer_id'],'program_motor':boat['motor_number'],
                            'table_motor':found['motor_number'] if found else None,
                            'reason':'motor_mismatch' if found else 'racer_absent_from_current_table'})
            if len({x['lane'] for x in matched})!=len(matched):
                raise ValueError('Overlapping preinspection series produces duplicate lane')
            counts['preinspection_matched_boats']+=len(matched)
            counts['preinspection_six_boat_matched_races']+=len(matched)==6
            venue['preinspection_boats']+=len(matched)
            records.append({'race_id':race['race_id'],'tide_station_proxy':tide,'tide_link_status':status,
                            'motor_fleet_cycle':motor,'preinspection':matched,
                            'current_observation':None,'video_attack_origin':None,'prerace_receipt':None,
                            'usage':'retrospective_research_only','production_eligible':False})
    if len({r['race_id'] for r in records})!=len(records):raise ValueError('Duplicate enrichment race')
    atomic(root/'race_enrichment.json.gz',gzip.compress(encode(records),mtime=0))
    save_json(root/'preinspection_unmatched.json',unmatched)
    summary={'generated_at':stamp(),'counts':counts,'per_venue':per_venue,'jma_sources':source_counts,
             'station_hours_present':{st:sum(v['height_cm'] is not None for v in rows.values())
                                      for st,rows in observations.items()},'errors':errors,
             'preinspection_source_rows':{x['venue_code']:len(x['rows']) for x in preinspection},
             'preinspection_in_series_unmatched_boats':len(unmatched),
             'original_race_count_added':0,'production_eligible':False,
             'limitations':['Station height is a nearby proxy, not racecourse tide or current',
                'JMA smoothed daily retrospective data is released after racing; no pre-deadline claim',
                'Local gauge datum retained; no conversion to astronomical tide datum or common elevation',
                'Preinspection only current captured series; historical full-year coverage remains missing',
                'Fleet cycle date does not verify individual engine first-use or continuous unmodified engine identity',
                'Motor day conflicts/month precision retained; no fabricated exact dates',
                'Actual flow and video attack labels remain absent; historical receipt cannot be reconstructed']}
    save_json(root/'summary.json',summary)
    return summary


def acquire(data, probe_dir=None):
    root=Path(data)/'gaps'; cache=Evidence(root)
    seeds={'motor_edogawa':'motor_edogawa.html','motor_hamanako':'motor_hamanako.html',
           'motor_karatsu':'motor_karatsu.html','preinspection_kojima':'preinspection_kojima.html',
           'preinspection_karatsu':'preinspection_karatsu.html','preinspection_hamanako':'preinspection_hamanako.html',
           'preinspection_edogawa':'preinspection_edogawa_valid.html'}
    jobs=[]
    for y,m in months('2025-10-18','2026-10-19'):
        for st,name in STATIONS.values():
            u,q=hourly_url(y,m,st)
            jobs.append((f'jma_{y:04}{m:02}_{st}',u,None))
    for key,url in URLS.items():
        seed=Path(probe_dir)/seeds[key] if probe_dir and key in seeds else None
        jobs.append((key,url,seed))
    def get(job):
        meta,body=cache.read(*job)
        print(json.dumps({'key':meta['key'],'status':meta['status'],'bytes':meta.get('bytes')},ensure_ascii=False),flush=True)
        return meta
    with ThreadPoolExecutor(max_workers=2) as pool: metas=list(pool.map(get,jobs))
    save_json(root/'acquisition.json',{'observed_at':stamp(),'sources':metas,'research_only':True})
    return metas


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',required=True);p.add_argument('--probe-dir')
    p.add_argument('--motor-catalog');p.add_argument('--series-catalog');p.add_argument('--offline',action='store_true')
    a=p.parse_args()
    if not a.offline: acquire(a.data,a.probe_dir)
    if a.motor_catalog and a.series_catalog:
        print(json.dumps(enrich(a.data,a.motor_catalog,a.series_catalog),ensure_ascii=False))


if __name__=='__main__':main()
