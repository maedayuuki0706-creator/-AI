"""Build private R2 query indexes from the verified local search DB.
Not raw source files, not public assets. Atomic generation directory, explicit user upload.
"""
import argparse,pathlib,sqlite3,json,collections,hashlib
p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--out',required=True);a=p.parse_args()
out=pathlib.Path(a.out).resolve();public=pathlib.Path(__file__).resolve().parents[1]/'public'
if out==public or public in out.parents:raise SystemExit('Private output only')
out.mkdir(parents=True,exist_ok=True);c=sqlite3.connect(f'file:{pathlib.Path(a.db).resolve()}?mode=ro',uri=True);c.row_factory=sqlite3.Row
objects=[]
def put(key,data):
 b=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode();f=out/key;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(b);objects.append({'key':key,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
races={};months=collections.defaultdict(list);days=collections.defaultdict(dict)
for row in c.execute('SELECT * FROM races ORDER BY day DESC,id DESC'):
 r=dict(row);races[r['id']]=r;months[r['day']].append({k:r[k] for k in ['id','day','venue','rno','result','payout','method','wind','wave','phase']});days[r['day']][r['id']]={'race':r,'entries':[]}
players=collections.defaultdict(list)
for row in c.execute('SELECT * FROM entries ORDER BY race_id,boat'):
 e=dict(row);r=races[e['race_id']];days[r['day']][r['id']]['entries'].append(e);players[e['racer_id']].append({k:e[k] for k in ['race_id','boat','rank','course','st']}|{'day':r['day'],'venue':r['venue']})
month_index=[]
for month,rows in months.items():
 put('races/'+month+'.json',rows);month_index.append({'day':month,'venues':sorted(set(r['venue'] for r in rows))})
put('races/index.json',month_index)
for day,data in days.items():put('days/'+day+'.json',data)
player_rows=[dict(r) for r in c.execute('SELECT * FROM players ORDER BY id')];put('players/index.json',player_rows)
for pl in player_rows:put('players/'+pl['id']+'.json',{'player':pl,'entries':players[pl['id']]})
for row in c.execute('SELECT * FROM summaries'):
 data=json.loads(row['json']);put('summaries/'+row['kind']+'.json',data)
 if row['kind'] in ('water','manshu'):
  for i in range(1,25):put('summaries/'+row['kind']+'-'+str(i).zfill(2)+'.json',[r for r in data if r['venue']==str(i).zfill(2)])
for table in ['motors','previews']:
 rows=[dict(r) for r in c.execute('SELECT * FROM '+table+' ORDER BY day DESC')]
 put(table+'/all.json',rows if table=='previews' else [])
 for i in range(1,25):put(table+'/'+str(i).zfill(2)+'.json',[r for r in rows if r['venue']==str(i).zfill(2)])
(out/'upload-manifest.json').write_text(json.dumps({'objects':objects,'count':len(objects),'bytes':sum(x['bytes'] for x in objects)},indent=2))
print(json.dumps({'objects':len(objects),'bytes':sum(x['bytes'] for x in objects),'largest_object_bytes':max(x['bytes'] for x in objects)}))
