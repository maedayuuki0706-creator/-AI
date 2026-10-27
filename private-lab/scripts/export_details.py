"""Create private R2 objects, never static assets. No upload happens here."""
import sqlite3,json,pathlib,argparse,datetime
p=argparse.ArgumentParser();p.add_argument('--preview',required=True);p.add_argument('--out',required=True);a=p.parse_args()
out=pathlib.Path(a.out).resolve();public=pathlib.Path(__file__).resolve().parents[1]/'public'
if out==public or public in out.parents:raise SystemExit('Refusing public asset output')
out.mkdir(parents=True,exist_ok=True)
c=sqlite3.connect(f'file:{pathlib.Path(a.preview).resolve()}?mode=ro',uri=True);c.row_factory=sqlite3.Row
sources={}
for row in c.execute('SELECT * FROM preview WHERE before_deadline=1'):
 r=dict(row)
 try:
  dt=datetime.datetime.fromisoformat(r['asof']);deadline=datetime.datetime.fromisoformat(r['race_day']+'T'+r['deadline']).replace(tzinfo=datetime.timezone(datetime.timedelta(hours=9)))
  if dt.tzinfo is None or dt>deadline:continue
 except (TypeError,ValueError):continue
 sources.setdefault(r['code'],{})[r['category']]=r
exhib={};odds={}
for r in c.execute('SELECT * FROM exhibition'):exhib.setdefault(r['code'],[]).append(dict(r))
for r in c.execute('SELECT * FROM odds3'):odds.setdefault(r['code'],[]).append(dict(r))
count=0
for code,src in sources.items():
 # Each category's provenance remains visible. Do not infer labels for original_1/2/3.
 data={'id':code,'phase':'pre','source':'第三者BoatraceCSV・公式未照合','snapshots':src,'exhibition':exhib.get(code,[]) if 'previews/tkz' in src or 'previews/stt' in src else [],'odds':odds.get(code,[]) if 'previews/od3' in src else [],'note':'展示項目ごとの時刻はsnapshotsを参照。original_1/2/3のラベルは未取得。'}
 (out/(code+'.json')).write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')));count+=1
print(json.dumps({'objects':count,'bytes':sum(x.stat().st_size for x in out.glob('*.json'))}))
