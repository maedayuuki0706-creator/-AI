"""Emit bounded SQL batches for manual D1 import; never contacts Cloudflare.
Budget is conservative (80k estimated row/index writes per file), not a billing guarantee.
Do not apply more than ONE file per day on free tier without checking actual dashboard usage.
"""
import sqlite3,pathlib,argparse,json
p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--out',required=True);a=p.parse_args()
out=pathlib.Path(a.out).resolve();root=pathlib.Path(__file__).resolve().parents[1]
if out==root/'public' or root/'public' in out.parents:raise SystemExit('Private output only')
out.mkdir(parents=True,exist_ok=True)
c=sqlite3.connect(f'file:{pathlib.Path(a.db).resolve()}?mode=ro',uri=True)
tables=['races','entries','players','motors','previews','summaries'];files=[];lines=[];budget=0
# Includes PK and maintained indexes, plus conservative margin. Validate live metrics.
cost={'races':8,'entries':4,'players':4,'motors':4,'previews':4,'summaries':3}
def flush():
 global lines,budget
 if not lines:return
 name=f'{len(files)+1:03d}.sql';(out/name).write_text('\n'.join(lines)+'\n');files.append({'file':name,'estimated_row_writes':budget,'rows':len(lines)});lines=[];budget=0
def quote(v):
 if v is None:return 'NULL'
 if isinstance(v,(int,float)):return str(v)
 return "'"+str(v).replace("'","''")+"'"
for table in tables:
 for row in c.execute('SELECT * FROM '+table):
  if budget+cost[table]>80000:flush()
  lines.append('INSERT OR IGNORE INTO '+table+' VALUES('+','.join(map(quote,row))+');');budget+=cost[table]
flush();(out/'plan.json').write_text(json.dumps({'files':files,'warning':'Schema first. Initial import only; one batch/day at most, check real quota. No automatic remote writes. Summaries last.'},indent=2));print(json.dumps({'batches':len(files),'estimated_total_writes':sum(x['estimated_row_writes'] for x in files)}))
