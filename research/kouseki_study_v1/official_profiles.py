"""Official half-year summaries and post-race secondary program snapshots."""
import json


def racer_terms(folder, day, riders):
    reports=[]
    for p in sorted(folder.glob('????-?.txt')):
        year,half=p.stem.split('-')
        active=year+('0101' if half=='1' else '0701')
        if active>day:continue
        meta=json.loads(p.with_suffix('.json').read_text())
        for row in p.read_bytes().splitlines():
            rid=row[:4].decode('ascii')
            if rid not in riders:continue
            if len(row)!=416 or row[174:179].decode()!=year+half:raise ValueError('term file identity')
            start=row[179:187].decode();end=row[187:195].decode()
            if end>=day:continue
            c=riders[rid];i=82+13*(c-1);j=198+34*(c-1)
            n=int(row[i:i+3])
            reports.append((rid,p.stem,start,end,row[39:41].decode().strip(),int(row[58:62])/100,
                int(row[72:75]),c,n,int(row[j:j+3]),int(row[j+3:j+6]),int(row[j+6:j+9]),
                int(row[i+7:i+10])/100 if n else None,int(row[i+10:i+13])/100 if n else None,meta['url']))
    return reports


def program(data,target):
    folder=data/'program_source';day=target['day'];p=folder/(day+'.json')
    if not p.exists():return None
    info=json.loads(p.read_text())['programs']['stadiums'].get(str(int(target['jcd'])),{}).get('races',{}).get(str(target['rno']))
    if not info:return None
    if (info['date'].replace('-',''),info['stadium_number'],info['race_number'])!=(day,int(target['jcd']),target['rno']):return None
    boats=info['racers']
    if any(str(boats.get(str(b['lane']),{}).get('number'))!=str(b['racer_id']) for b in target['rows']):return None
    return info,json.loads((folder/(day+'.meta.json')).read_text())
