"""Published JMA astronomical hourly levels. Station proxy, not observed surface current."""
from datetime import datetime, timedelta
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=64)
def annual(path):
    if not path.is_file():return {}
    year,station=path.stem.split('-')
    values={}
    for line in path.read_text(encoding='ascii').splitlines():
        if len(line)<80 or line[78:80]!=station or line[72:74]!=year[-2:]:
            raise ValueError('JMA station/year mismatch')
        day=datetime(int(year),int(line[74:76]),int(line[76:78]))
        for hour in range(24):
            raw=line[hour*3:hour*3+3].strip()
            if raw and raw!='999':values[day+timedelta(hours=hour)]=int(raw)
    return values


def tide(folder,profile,day,deadline):
    station=profile.get('station_code')
    if not station or profile.get('provider')!='jma' or not profile.get('tide_enabled'):return None
    try:hour=datetime.strptime(day+' '+deadline,'%Y%m%d %H:%M').replace(minute=0)
    except (TypeError,ValueError):return None
    previous=hour-timedelta(hours=1)
    def value(t):
        return annual(Path(folder)/f'{t.year}-{station}.txt').get(t)
    a,b=value(previous),value(hour)
    if a is None or b is None:return None
    return hour.isoformat(timespec='minutes'),b,b-a,'上げ' if b>a else '下げ' if b<a else '同値'
