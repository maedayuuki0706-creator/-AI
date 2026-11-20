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
