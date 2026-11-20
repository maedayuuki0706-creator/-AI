"""Read pre-race fields from stored program data, keeping unavailable exhibition explicit."""
import json
from pathlib import Path
from analytics import is_six
from longitudinal import connect


def build_entries(folder, out, start, end, revision):
    import tempfile, os, sqlite3
    from collections import Counter
    with tempfile.TemporaryDirectory(dir=out.parent) as temp:
        path=Path(temp)/'lineup.db';c=sqlite3.connect(path)
        try:
            c.execute('create table program_boat(id text,lane integer,racer text,name text,grade integer,motor integer,national real,local real,f integer,primary key(id,lane))')
            c.execute('create table source(revision text)');c.execute('insert into source values(?)',(revision,))
            for f in sorted(folder.glob('????/????????.json')):
                if not start<=f.stem<=end:continue
                programs=json.loads(f.read_bytes())['programs']
                keys=Counter((r.get('race_stadium_number'),r.get('race_number')) for r in programs)
                entries=[]
                for r in programs:
                    v,n=r.get('race_stadium_number'),r.get('race_number')
                    if type(v) is not int or type(n) is not int or not 1<=v<=24 or not 1<=n<=12 or keys[v,n]!=1 or r.get('race_date','').replace('-','')!=f.stem:continue
                    boats=r.get('boats') or []
                    if not is_six([{'lane':b.get('racer_boat_number'),'racer_id':b.get('racer_number')} for b in boats]):continue
                    for b in boats:
                        entries.append((f'{f.stem}{v:02}{n:02}',b['racer_boat_number'],str(b['racer_number']),b.get('racer_name'),b.get('racer_class_number'),b.get('racer_assigned_motor_number'),b.get('racer_national_top_1_percent'),b.get('racer_local_top_1_percent'),b.get('racer_flying_count')))
                c.executemany('insert into program_boat values(?,?,?,?,?,?,?,?,?)',entries)
            c.commit()
        finally:c.close()
        os.link(path,out)


def target_record(data, day, venue, number):
    p=data/'exhibition_log'/day/f'{venue}_{number:02}.json'
    if p.exists():
        t=json.loads(p.read_text())
    else:
        if not (data/'lineups.sqlite').is_file() or not (data/'programs.sqlite').is_file():
            raise FileNotFoundError(p)
        db=connect(data/'lineups.sqlite')
        try:
            key=f'{day}{venue}{number:02}'
            db.execute('attach database ? as pg',((data/'programs.sqlite').resolve().as_uri()+'?mode=ro',))
            event=db.execute('select deadline from pg.schedule where id=?',(key,)).fetchone()
            boats=db.execute('select * from program_boat where id=? order by lane',(key,)).fetchall()
            if not event or len(boats)!=6:raise ValueError('incomplete program')
            t={'day':day,'jcd':venue,'rno':number,'deadline':str(event['deadline'])[-8:-3],'source':'BoatraceOpenAPI/programs v2（事後収録）',
               'rows':[{'lane':b['lane'],'racer_id':b['racer'],'name':b['name'],'motor_number':b['motor'],
                        'current_class':{1:'A1',2:'A2',3:'B1',4:'B2'}.get(b['grade']),
                        'national_win':b['national'],'local_win':b['local'],'f_count':b['f']} for b in boats]}
        finally:db.close()
    if (str(t['day']),str(t['jcd']).zfill(2),t['rno'])!=(day,venue,number) or not is_six(t['rows']):
        raise ValueError('target identity mismatch')
    return t


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser()
    for k in ('folder','out'):ap.add_argument('--'+k,type=Path,required=True)
    for k in ('start','end','revision'):ap.add_argument('--'+k,required=True)
    build_entries(**vars(ap.parse_args()))
