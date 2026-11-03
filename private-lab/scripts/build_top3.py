"""Read-only export of saved official logs. Never promotes replay data to forecasts."""
import json, sys, hashlib
from pathlib import Path
source=Path(sys.argv[1]); out=Path(__file__).resolve().parents[1]/'public'/'research-data';out.mkdir(exist_ok=True)
index=[];days={};rejected=0
fields=['lane','racer_id','name','current_class','exhibition_course','exhibition_time','exhibition_st','tilt','motor_number','wind_m','wave_cm','actual_course','actual_st','finish']
for p in sorted((source/'data/exhibition_log').glob('*/*.json')):
 d=json.loads(p.read_text()); rows=d.get('rows',[])
 if len(rows)!=6 or sorted(r.get('lane',0) for r in rows)!=list(range(1,7)) or len({str(r.get('racer_id')) for r in rows})!=6:
  rejected+=1;continue
 day=str(d['day']);venue=str(d['jcd']).zfill(2);rno=int(d['rno']);key=f'{day}_{venue}_{rno:02}'
 item=dict(id=key,day=day,venue=venue,rno=rno,captured_at=d.get('captured_at'),updated_at=d.get('updated_at'),deadline=d.get('deadline'),source=d.get('source'),source_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),mode='historical_archive',boats=[{k:r.get(k) for k in fields} for r in sorted(rows,key=lambda x:x['lane'])])
 days.setdefault(day,{})[key]=item;index.append({k:item[k] for k in ['id','day','venue','rno']})
for day,races in days.items():(out/f'{day}.json').write_text(json.dumps(races,ensure_ascii=False,separators=(',',':')))
(out/'index.json').write_text(json.dumps(dict(races=index,days=sorted(days),count=len(index),rejected=rejected,mode='historical_archive'),ensure_ascii=False,separators=(',',':')))
example=source/'research/ultimate_fusion_v2/reports/20261102/example.json'
if example.exists():(out/'scenario.json').write_text(example.read_text())
print(json.dumps({'races':len(index),'days':len(days),'venues':len(set(x['venue'] for x in index)),'rejected':rejected}))
