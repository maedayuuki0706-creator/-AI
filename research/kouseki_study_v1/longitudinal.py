"""Read-only official K archive. The unit is one complete race with actual courses."""
import sqlite3
from collections import defaultdict
from itertools import groupby
from pathlib import Path
from statistics import median

from analyst_context import rate


def connect(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def scenarios(db, cutoff):
    """Predeclared hypothesis: course 5 finishes second on a course 4 sweep.
    Compare with other methods of course 4 wins. Split before looking at outcomes.
    """
    query = """
      SELECT r.jcd,r.deciding_method,w.course AS attacker,s.course AS second,
             t.course AS third,r.day >= '20250101' AS holdout,count(*) AS n
      FROM race r JOIN entry w ON w.id=r.id AND w.rank=1
      JOIN entry s ON s.id=r.id AND s.rank=2 JOIN entry t ON t.id=r.id AND t.rank=3
      WHERE r.day < ? GROUP BY 1,2,3,4,5,6
    """
    groups = defaultdict(list)
    for row in db.execute(query, (cutoff,)):
        groups[row['jcd']].append(dict(row))
    return groups


def follower(rows, holdout, sweep):
    sample = [r for r in rows if r['attacker'] == 4 and r['holdout'] == holdout
              and bool(r['deciding_method'] == 'まくり') == sweep]
    return rate(sum(r['n'] for r in sample if r['second'] == 5), sum(r['n'] for r in sample))


def similar(history, target):
    """Exact venue & six class labels. Distance is mean absolute exhibition rank gap."""
    ordered = lambda r: sorted(r, key=lambda b: b['lane'])
    lineup = ordered(target['rows'])
    def features(boats):
        times = [b.get('exhibition_time') for b in boats]
        if any(type(x) not in (int,float) or not 4 <= x <= 10 for x in times):
            return None
        grades = tuple(b.get('current_class') for b in boats)
        if not all(g in ('A1','A2','B1','B2') for g in grades):
            return None
        return grades, [1 + sum(y < x for y in times) for x in times]
    f = features(lineup)
    matches = []
    for r in history:
        if r['venue'] != target['jcd'] or r['day'] >= target['day'] or not f:
            continue
        g = features(ordered(r['rows']))
        if not g or f[0] != g[0]:
            continue
        distance = sum(abs(a-b) for a,b in zip(f[1],g[1]))/6
        matches.append((round(distance,3),r['day'],r['race_no'],r['method'],
                        '-'.join(str(b['lane']) for b in sorted(r['rows'],key=lambda b:b['finish'])[:3])))
    return sorted(matches)


def check_g1(db, workbook, cutoff):
    from openpyxl import load_workbook
    book = load_workbook(workbook, read_only=True, data_only=True)
    events = defaultdict(list)
    for row in book['全288R'].values:
        if len(row)<15 or type(row[2]) is not int:
            continue
        event,day,n,*_ = row
        day=str(day).replace('-','')
        if day>=cutoff:
            continue
        result=db.execute("SELECT winning_boats,payout_yen,deciding_method FROM race WHERE id=?",
                          (f"{day}08{n:02}",)).fetchone()
        events[event].append((day,row[3],row[10],row[11],None if not result else
                              tuple(result)==(row[9],row[10],row[11]),row[14]))
    book.close()
    return events

def evaluate_escape(db, cutoff):
    """One fixed benchmark: train venue escape prevalence through 2024, score 2025."""
    import math
    split = '20250101'
    results = db.execute("""
        SELECT jcd,day>=? AS test,count(*),sum(course=1 AND deciding_method='逃げ')
        FROM race JOIN entry USING(id) WHERE rank=1 AND day<? GROUP BY 1,2
    """,(split,cutoff))
    by_venue=defaultdict(dict)
    for v,h,n,k in results: by_venue[v][h]=(n,k)
    scores=[]
    total_n=sum(x[0][0] for x in by_venue.values() if 0 in x)
    total_k=sum(x[0][1] for x in by_venue.values() if 0 in x)
    for v,x in sorted(by_venue.items()):
        if not (0 in x and 1 in x):continue
        train,win=x[0];n,k=x[1]
        def loss(p):
            return ((k*(1-p)**2+(n-k)*p**2)/n,
                    -(k*math.log(p)+(n-k)*math.log1p(-p))/n)
        p=(win+1)/(train+2)
        scores.append((v,train,n,p,k/n,*loss(p),*loss((total_k+1)/(total_n+2))))
    return scores


def discover(db, cutoff):
    """Select one cell using development observations only, then test the frozen cell."""
    q="""SELECT jcd,wind_m>=4 AS windy,day>='20250101' AS test,
                count(*) n,sum(course=1 AND deciding_method='逃げ') k
         FROM race JOIN entry USING(id) WHERE rank=1 AND wind_m>=0 AND day<?
         GROUP BY 1,2,3"""
    cells={(v,w,h):(n,k) for v,w,h,n,k in db.execute(q,(cutoff,))}
    def difference(v,h):
        a,ka=cells[v,1,h]; b,kb=cells[v,0,h]
        return ka/a-kb/b
    candidates=[v for v in sorted({c[0] for c in cells})
                if all(cells.get((v,w,0),(0,0))[0]>=100 for w in (0,1))]
    if not candidates:return []
    v=min(candidates,key=lambda v:difference(v,0))
    return [(v,h,w,rate(k,n)) for h in (0,1) for w in (0,1)
            for n,k in [cells.get((v,w,h),(0,0))]]
