"""Build independent schedule and grade index from a pinned public program snapshot."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile


def build(files,out,start,end,revision):
    if out.exists():raise FileExistsError(out)
    with tempfile.TemporaryDirectory(dir=out.parent) as d:
        p=Path(d)/'p.sqlite'
        c=sqlite3.connect(p)
        try:
            c.executescript("""
                CREATE TABLE schedule(id TEXT PRIMARY KEY,day TEXT,venue TEXT,race_no INTEGER,
                  grade INTEGER,title TEXT,stage TEXT,deadline TEXT);
                CREATE TABLE source(day TEXT PRIMARY KEY,sha256 TEXT,raw INTEGER,accepted INTEGER,invalid INTEGER);
                CREATE TABLE provenance(revision TEXT,generated_utc TEXT);
            """)
            c.execute('insert into provenance values(?,?)',(revision,datetime.now(timezone.utc).isoformat()))
            for f in sorted(files.glob('[0-9]'*4+'/'+'[0-9]'*8+'.json')):
                if not start<=f.stem<=end:continue
                raw=f.read_bytes(); races=json.loads(raw)['programs']
                keys=Counter((r.get('race_stadium_number'),r.get('race_number')) for r in races)
                rows=[]
                for r in races:
                    v,n=r.get('race_stadium_number'),r.get('race_number')
                    if (str(r.get('race_date')).replace('-','')!=f.stem or keys[v,n]!=1 or type(v) is not int
                        or not 1<=v<=24 or type(n) is not int or not 1<=n<=12):continue
                    rows.append((f'{f.stem}{v:02}{n:02}',f.stem,f'{v:02}',n,r.get('race_grade_number'),
                                 r.get('race_title'),r.get('race_subtitle'),r.get('race_closed_at')))
                c.executemany('insert into schedule values(?,?,?,?,?,?,?,?)',rows)
                c.execute('insert into source values(?,?,?,?,?)',(f.stem,hashlib.sha256(raw).hexdigest(),len(races),len(rows),len(races)-len(rows)))
            c.execute('create index by_day on schedule(day,venue)')
            c.commit()
        finally:c.close()
        os.link(p,out)


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    for name in ('files','out'):ap.add_argument('--'+name,type=Path,required=True)
    for name in ('start','end','revision'):ap.add_argument('--'+name,required=True)
    build(**vars(ap.parse_args()))
