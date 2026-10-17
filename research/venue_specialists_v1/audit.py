"""Coverage is independent of successful captures; immutable schedules are the denominator."""
from datetime import datetime
import json
from pathlib import Path
from .engine import VENUES,JST


def read(path):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return {}


def coverage_counts(root,day,now=None):
    root=Path(root);now=now or datetime.now(JST);expected={};schedule_errors={}
    for path in sorted((root/'schedules').glob('20*/*.json')):
        inventory=read(path);date=inventory.get('day','')
        if date>day:continue
        for error in inventory.get('errors',[]):schedule_errors[error['venue']]=error
        for code,times in inventory.get('schedules',{}).items():
            schedule_errors.pop(code,None)
            for number,hhmm in enumerate(times,1):
                key=f'{date}_{code}_{number:02}'
                expected[key]=datetime.strptime(date+' '+hhmm,'%Y%m%d %H:%M').replace(tzinfo=JST)
    stats={code:{'scheduled_races':0,'local_forecasts':0,'saved_success':0,'missing_count':0,
                 'upcoming_unconfirmed':0,'missing_race_ids':[],
                 'operational_status':'not_started' if day<v['first_day'] else 'no_verified_schedule',
                 'schedule_error':schedule_errors.get(code)} for code,v in VENUES.items()}
    for key,deadline in expected.items():
        date,code,_=key.split('_');row=stats[code];row['scheduled_races']+=1
        f=read(root/'forecasts'/date/(key+'.json'));receipt=read(root/'receipts'/date/(key+'.json'))
        if f:row['local_forecasts']+=1
        valid=bool(f and receipt.get('digest')==f.get('digest') and receipt.get('race_id')==key and
                   receipt.get('status')=='confirmed_before_deadline')
        if valid:row['saved_success']+=1
        elif (deadline-now).total_seconds()<180:
            row['missing_count']+=1;row['missing_race_ids'].append(key)
        else:row['upcoming_unconfirmed']+=1
        row['operational_status']='degraded_missing' if row['missing_count'] else 'observed'
    return stats
