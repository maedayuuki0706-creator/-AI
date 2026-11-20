"""Venue-specific original splits matched to actual courses and finishes by identity."""
import csv
from collections import defaultdict
from statistics import mean
from analyst_context import valid_number


def columns(row,boats):
    norm=lambda s:''.join(s.split())
    if any(norm(row.get(f'艇{i}_選手名',''))!=norm(b['name']) for i,b in enumerate(boats,1)):
        return {}
    result={}
    for j in range(1,4):
        key=row.get(f'計測項目{j}')
        if not key:continue
        if key in result:return {}
        values=[]
        for i in range(1,7):
            try:value=float(row[f'艇{i}_値{j}'])
            except (KeyError,ValueError,TypeError):value=None
            values.append(value if valid_number(value,.01,180) else None)
        result[key]=values
    return result


def cohorts(folder, venue, cutoff, history):
    races={(r['day'],r['race_no']):r for r in history if r['venue']==venue}
    by_course=defaultdict(list)
    for file in sorted(folder.glob('????????.csv')):
        if file.stem>=cutoff or venue=='03':continue
        with file.open(encoding='utf-8-sig') as stream:
            matched=defaultdict(list)
            for row in csv.DictReader(stream):
                key=row.get('レースコード','')
                if len(key)!=12 or key[:10]!=file.stem+venue or not key[10:].isdigit():continue
                matched[int(key[10:])].append(row)
            for n,rows in matched.items():
                r=races.get((file.stem,n))
                if not r or len(rows)!=1:continue
                boats=sorted(r['rows'],key=lambda b:b['lane'])
                for metric,times in columns(rows[0],boats).items():
                    if any(t is None for t in times):continue
                    for b,t in zip(boats,times):
                        top=1+sum(x<t for x in times)<=2
                        by_course[metric,b['actual_course'],top].append(b['finish'])
    return by_course

def audit_splits(folder, days):
    """Compare split CSV identities with known schedules; keep Edogawa separate."""
    import json
    from collections import Counter
    totals=defaultdict(Counter)
    retry=[]
    for day in days:
        d=day['day']
        if day['manifest_status']!='complete':continue
        csv_file=folder/(d+'.csv')
        counts=Counter()
        if csv_file.exists():
            with csv_file.open(encoding='utf-8-sig') as f:
                counts.update(r.get('レースコード') for r in csv.DictReader(f))
        err=folder/(d+'.acquisition_error.audit.json')
        info=json.loads(err.read_text()) if err.exists() else {}
        cancelled={str(v).zfill(2) for v in info.get('cancelled_listed',[])}
        for r in day['races']:
            v,n=r['venue'],r['race_no']
            if v=='03':continue
            key=f'{d}{v}{n:02}'; totals[v]['scheduled']+=1
            if counts[key]==1:
                totals[v]['saved']+=1
            elif v in cancelled:
                totals[v]['cancel_notice']+=1
            else:
                state=('duplicate' if counts[key]>1 else 'missing_row' if csv_file.exists()
                       else 'acquisition_error' if err.exists() else 'no_daily_file')
                totals[v][state]+=1
                retry.append((d,v,n,state))
    return totals,retry
