"""Index immutable daily Boatrace Open API v2 files; cross-check official K records."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import os

from analytics import as_day


def import_file(db, p):
    day=p.stem; raw=p.read_bytes(); result=json.loads(raw)['results']
    counts=Counter((r.get('race_stadium_number'),r.get('race_number')) for r in result)
    included=excluded=0
    for r in result:
        v,n=r.get('race_stadium_number'),r.get('race_number')
        rid=f'{day}{v:02}{n:02}' if type(v) is int and type(n) is int else ''
        boats=r.get('boats') or []
        try:
            if (str(r['race_date']).replace('-','')!=day or counts[v,n]!=1 or not rid
                or not 1<=v<=24 or not 1<=n<=12 or len(boats)!=6):
                raise ValueError('identity_or_lineup')
            for k in ('racer_boat_number','racer_course_number','racer_place_number'):
                if sorted(b[k] for b in boats)!=list(range(1,7)):raise ValueError(k)
            if len({b['racer_number'] for b in boats})!=6 or not all(str(b['racer_number']).isdigit() and len(str(b['racer_number']))==4 for b in boats):
                raise ValueError('racer_id')
            ordered=sorted(boats,key=lambda b:b['racer_place_number'])
            combo='-'.join(str(b['racer_boat_number']) for b in ordered[:3])
            matches=[x for x in (r.get('payouts') or {}).get('trifecta',[]) if x.get('combination')==combo]
            pay=matches[0].get('payout') if len(matches)==1 else None
            if type(pay) is not int or pay<=0:pay=None
            entries=[(rid,b['racer_boat_number'],str(b['racer_number']),b['racer_course_number'],b['racer_place_number'],b.get('racer_start_timing')) for b in boats]
        except (ValueError,KeyError,TypeError) as e:
            excluded+=1;db.execute('insert into exclusion values(?,?,?)',(day,rid,str(e)));continue
        db.execute('insert into result values(?,?,?,?,?,?)',(rid,day,f'{v:02}',n,combo,pay))
        db.executemany('insert into runner values(?,?,?,?,?,?)',entries);included+=1
    db.execute('insert into source values(?,?,?,?,?)',(day,hashlib.sha256(raw).hexdigest(),len(result),included,excluded))


def build(files, official, out, start, end, revision):
    as_day(start);as_day(end)
    if start>end or out.exists(): raise ValueError('invalid interval or output already exists')
    # Link after a successful transaction; a partial or concurrent run cannot replace output.
    with tempfile.TemporaryDirectory(dir=out.parent) as folder:
        tmp=Path(folder)/'index.sqlite'
        db=sqlite3.connect(tmp.as_uri() if tmp.is_absolute() else tmp.resolve().as_uri(),uri=True)
        try:
            db.executescript("""
                CREATE TABLE result(id TEXT PRIMARY KEY,day TEXT,venue TEXT,race_no INTEGER,combo TEXT,pay INTEGER);
                CREATE TABLE runner(id TEXT,boat INTEGER,racer TEXT,course INTEGER,finish INTEGER,st REAL,PRIMARY KEY(id,boat));
                CREATE TABLE source(day TEXT PRIMARY KEY,sha256 TEXT,raw INTEGER,included INTEGER,excluded INTEGER);
                CREATE TABLE exclusion(day TEXT,id TEXT,reason TEXT);
                CREATE TABLE provenance(revision TEXT,indexed_at TEXT);
            """)
            db.execute('insert into provenance values(?,?)',(revision,datetime.now(timezone.utc).isoformat()))
            for p in sorted(files.glob('[0-9]'*4+'/'+'[0-9]'*8+'.json')):
                if start<=p.stem<=end:import_file(db,p)
            db.execute('create index by_racer on runner(racer,id)')
            db.execute("attach database ? as k",(official.resolve().as_uri()+'?mode=ro',))
            db.executescript("""
                CREATE TABLE result_check AS SELECT substr(r.day,1,4) year,count(*) overlap,
                sum(r.combo!=k.winning_boats) combo_mismatch,sum(r.pay IS NULL) missing_pay,
                sum(r.pay!=k.payout_yen) pay_mismatch FROM result r JOIN k.race k USING(id) GROUP BY 1;
                CREATE TABLE entry_check AS SELECT substr(e.id,1,4) year,count(*) overlap,
                sum(e.racer!=k.racer_id OR e.course!=k.course OR e.finish!=k.rank) mismatch
                FROM runner e JOIN k.entry k ON e.id=k.id AND e.boat=k.boat GROUP BY 1;
            """)
            db.commit()
        finally:db.close()
        os.link(tmp,out)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('files','official','out'):parser.add_argument('--'+name,type=Path,required=True)
    for name in ('start','end','revision'):parser.add_argument('--'+name,required=True)
    build(**vars(parser.parse_args()))
