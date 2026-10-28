"""Generate private immutable, compressed win-path profiles from official historical outcomes.

All observations are POST-race. No course attribution is inferred from frame number.
Never commit generated packs to a public repository.
"""
import argparse,base64,collections,datetime,gzip,json,pathlib,sqlite3,hashlib
METHODS=('逃げ','差し','まくり','まくり差し','抜き','恵まれ')
CUTOFF='20250101'

def aggregate(path,out):
    con=sqlite3.connect(f'file:{pathlib.Path(path).resolve()}?mode=ro',uri=True)
    con.row_factory=sqlite3.Row
    players={}
    baseline={}
    counts={'observations':0,'winners':0,'unknown_methods':collections.Counter()}
    def key(v,dim,lane,period):return f'{period}|{v}|{dim}|{lane}'
    def update(t, k, rank, method, course, st):
        z=t.get(k)
        if z is None:
            z={'n':0,'w':0,'t2':0,'t3':0,'sn':0,'ss':0,'method':{},'loss':{},'in_escape':0}
            t[k]=z
        z['n']+=1;z['w']+=(rank==1);z['t2']+=(rank<=2);z['t3']+=(rank<=3)
        if st is not None:
            z['sn']+=1;z['ss']+=st
        if rank==1:z['method'][method]=z['method'].get(method,0)+1
        else:z['loss'][method]=z['loss'].get(method,0)+1
        if course==2 and method=='逃げ':z['in_escape']+=1
    sql='''SELECT r.day,r.jcd venue,r.deciding_method method,e.racer_id id,e.name name,e.boat frame,e.course course,e.rank rank,e.st st
      FROM entry e JOIN race r ON e.id=r.id ORDER BY e.id,e.boat'''
    for row in con.execute(sql):
        id=str(row['id']); day=row['day']; venue=str(row['venue']).zfill(2); method=row['method']; rank=int(row['rank']); frame=row['frame'];course=row['course']
        if not (1<=rank<=6 and isinstance(frame,int) and 1<=frame<=6 and isinstance(course,int) and 1<=course<=6):raise ValueError('invalid lane/rank')
        counts['observations']+=1;counts['winners']+=rank==1
        if method not in METHODS:counts['unknown_methods'][str(method)]+=1
        try:st=float(row['st']) if row['st'] and row['st'][0] in '.0123456789' else None
        except (ValueError,TypeError):st=None
        profile=players.setdefault(id,{'id':id,'name':row['name'],'rows':{}})['rows']
        for period in (['all','2025'] if day>=CUTOFF else ['all']):
            for v in ('all',venue):
                for dim,lane in [('frame',frame),('course',course)]:
                    k=key(v,dim,lane,period)
                    update(profile,k,rank,method,course,st)
                    update(baseline,k,rank,method,course,st)
    # NOTE baseline 'all' aggregates are intentionally per entry, not per race.
    dest=pathlib.Path(out).resolve();dest.mkdir(parents=True,exist_ok=True)
    pack_counts=[]; pack_sizes=[];checksums={}
    for index,items in __import__('itertools').groupby(sorted(players.items()),lambda kv:int(kv[0])//50):
        pack={}
        for pid,data in items:
            payload=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()
            pack[pid]=base64.b64encode(gzip.compress(payload,compresslevel=1,mtime=0)).decode()
        target=dest/(f'p{index:03d}.json')
        wire=json.dumps(pack,ensure_ascii=False,separators=(',',':')).encode()
        target.write_bytes(wire)
        pack_counts.append((index,len(pack)));pack_sizes.append((index,len(wire)))
        checksums[target.name]=hashlib.sha256(wire).hexdigest()
    (dest/'baseline.json').write_text(json.dumps({'periods':['all','2025'],'from':'2022-01-01','to':'2025-12-31','races':counts['winners'],'players':len(players),'rows':baseline},ensure_ascii=False,separators=(',',':')))
    summary={'players':len(players),'observations':counts['observations'],'winning_entries':counts['winners'],'methods_not_matched':dict(counts['unknown_methods']),'packs':len(pack_counts),'packed_player_bytes':sum(s for _,s in pack_sizes),'baseline_bytes':(dest/'baseline.json').stat().st_size,'pack_counts':pack_counts,'max_bytes':max(s for _,s in pack_sizes),'sha256':checksums}
    (dest/'manifest.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k not in ('sha256','pack_counts')},ensure_ascii=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--out',required=True);a=p.parse_args();aggregate(a.db,a.out)