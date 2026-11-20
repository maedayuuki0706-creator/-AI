"""Observed roles, adjacent starts and rider-adjusted motor outcomes in prior races."""
from collections import defaultdict
from statistics import mean
from analyst_context import METHODS, rate, valid_number


def study(history, target, cycles):
    code=target['jcd']; day=target['day']
    known=[c for c in cycles if c['jcd']==code and c['start_date']<=day<=(c.get('end_date') or day)]
    start=known[0]['start_date'] if len(known)==1 else None
    # For a motor observation, use the driver's earlier-day performance at the same course.
    # Exclude starts on that motor at the same venue/cycle from the reference history.
    all_starts=defaultdict(list); motor_history=defaultdict(list)
    roles=defaultdict(list); starts=defaultdict(list)
    for r in sorted(history,key=lambda r:(r['day'],r['race_no'],r['venue'])):
        ordered=sorted(r['rows'],key=lambda b:b['actual_course'])
        for j,b in enumerate(ordered):
            key=str(b['racer_id']),j+1
            cycle_motor=(r['venue'],b.get('motor_number')) if start and r['venue']==code and r['day']>=start else None
            if cycle_motor and cycle_motor[1] is not None:
                other=[won for d,m,won in all_starts[key] if d<r['day'] and m!=cycle_motor]
                motor_history[cycle_motor[1]].append((b['finish']<=2,mean(other) if other else None,b.get('tilt'),r['day']))
            all_starts[key].append((r['day'],cycle_motor,b['finish']<=2))
            roles[key].append((r['method'],r['winning_course'],b['finish']))
            if j and valid_number(b.get('actual_st'),0,.99) and valid_number(ordered[j-1].get('actual_st'),0,.99):
                starts[key].append(b['actual_st']-ordered[j-1]['actual_st'])
    return roles,starts,motor_history

def start_study(races):
    """Descriptive exhibition shape from within-pair ST means. Cutoffs are hypotheses."""
    from statistics import correlation
    groups=defaultdict(list);paired=defaultdict(list)
    for r in races:
        entries=r['rows']
        for b in entries:
            x,y=b.get('exhibition_st'),b.get('actual_st')
            if valid_number(x,-.99,.99) and valid_number(y,0,.99):paired[b['actual_course']].append((x,y))
        if sorted(str(b.get('exhibition_course')) for b in entries)!=list('123456'):continue
        sts=[b.get('exhibition_st') for b in sorted(entries,key=lambda b:b['exhibition_course'])]
        if not all(valid_number(x,-.99,.99) for x in sts):continue
        means=[mean(sts[j:j+2]) for j in (0,2,4)]
        if max(sts)-min(sts)<=.05:group='横一線（6艇幅≤0.05秒）'
        else:
            j=means.index(max(means))
            group=('内凹み','中凹み','外凹み')[j] if means[j]-sorted(means)[1]>=.05 else '判別保留'
        groups[group].append(r)
    result=[]
    for course,pairs in sorted(paired.items()):
        x,y=zip(*pairs)
        corr=correlation(x,y) if len(set(x))>1 and len(set(y))>1 else None
        result.append((course,len(pairs),round(mean(x),3),round(mean(y),3),round(corr,3) if corr is not None else None))
    return groups,result


def motor_events(local,target,cycles):
    valid=[v for v in cycles if v['jcd']==target['jcd'] and v['start_date']<=target['day']<=(v.get('end_date') or target['day'])]
    if len(valid)!=1:return [],[]
    motors={b.get('motor_number') for b in target['rows'] if b.get('motor_number') is not None}
    uses=defaultdict(list)
    for r in sorted(local,key=lambda x:(x['day'],x['race_no'])):
        if r['day']<valid[0]['start_date']:continue
        for b in r['rows']:
            if b.get('motor_number') in motors:uses[b['motor_number']].append((r['day'],r['race_no'],b))
    events=[];angles=[]
    for motor,records in sorted(uses.items()):
        by_tilt=defaultdict(list)
        for i,(day,rno,b) in enumerate(records):
            if valid_number(b.get('tilt'),-1,4):by_tilt[b['tilt']].append(b['finish'])
            part=b.get('parts_exchange') or b.get('propeller_exchange')
            if part:
                before=records[max(0,i-3):i];after=records[i:i+3]
                def summary(group):
                    return rate(sum(x['finish']<=2 for _,_,x in group),len(group))
                events.append((motor,day,rno,str(part),summary(before),summary(after)))
        for angle,fs in sorted(by_tilt.items()):angles.append((motor,angle,rate(sum(f<=2 for f in fs),len(fs))))
    return events,angles
