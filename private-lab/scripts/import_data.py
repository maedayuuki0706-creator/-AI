"""Offline importer: immutable inputs, atomic replacement, no network or production writes."""
import argparse,sqlite3,pathlib,json,hashlib,datetime,os
ROOT=pathlib.Path(__file__).resolve().parents[1]
def build(source,preview,out):
 out=pathlib.Path(out).resolve();out.parent.mkdir(parents=True,exist_ok=True)
 if out==pathlib.Path(source).resolve() or (preview and out==pathlib.Path(preview).resolve()):raise ValueError('Output must differ from inputs')
 tmp=out.with_suffix('.building');tmp.unlink(missing_ok=True)
 c=sqlite3.connect(tmp,uri=True);c.executescript((ROOT/'schema.sql').read_text());c.execute('ATTACH DATABASE ? AS src',(f'file:{pathlib.Path(source).resolve()}?mode=ro',))
 c.execute("INSERT INTO races SELECT id,substr(day,1,4)||'-'||substr(day,5,2)||'-'||substr(day,7,2),jcd,rno,weather,wind_direction,wind_m,wave_cm,winning_boats,payout_yen,deciding_method,source_file,'post' FROM src.race")
 c.execute("INSERT INTO entries SELECT id,boat,racer_id,name,rank,course,motor,CASE WHEN st GLOB '0.[0-9]*' OR st GLOB '.[0-9]*' THEN CAST(st AS REAL) ELSE NULL END,exhibition FROM src.entry WHERE id IN(SELECT id FROM races)")
 c.execute("INSERT INTO players SELECT e.racer_id,max(name),replace(replace(max(name),' ',''),'　',''),count(*),sum(rank=1),sum(rank<=2),sum(rank<=3),avg(st),min(day),max(day) FROM entries e JOIN races r ON r.id=e.race_id GROUP BY e.racer_id")
 def rows(sql,args=()):
  cur=c.execute(sql,args);return [dict(zip([x[0] for x in cur.description],r)) for r in cur]
 def summary(kind,data):c.execute('INSERT INTO summaries VALUES (?,?)',(kind,json.dumps(data,ensure_ascii=False)))
 summary('water',rows("SELECT venue,wind,wind_direction,wave,count(*) races,sum(substr(result,1,1)='1') inside_wins FROM races GROUP BY venue,wind,wind_direction,wave"))
 summary('manshu',rows("SELECT venue,method,count(*) races,count(payout) payout_known,sum(payout>=10000) high,max(payout) max_payout FROM races GROUP BY venue,method"))
 manifest={'races':c.execute('select count(*) from races').fetchone()[0],'entries':c.execute('select count(*) from entries').fetchone()[0],'players':c.execute('select count(*) from players').fetchone()[0],'from':c.execute('select min(day) from races').fetchone()[0],'to':c.execute('select max(day) from races').fetchone()[0],'excluded':c.execute('select count(*) from src.excluded_race').fetchone()[0],'source_sha256':hashlib.sha256(pathlib.Path(source).read_bytes()).hexdigest(),'built_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'preview_rows':0,'motor_rows':0,'missing':['潮位','モーター交換期と公式使用履歴の照合','AIの締切前予想原本・投資額・払戻照合','公式得点率としての全国/当地勝率','2001〜2026期別データ接続'],'source':'公式K・厳密6艇採用（全開催の網羅ではない）'}
 if preview:
  c.execute('ATTACH DATABASE ? AS pre',(f'file:{pathlib.Path(preview).resolve()}?mode=ro',))
  c.execute('INSERT INTO motors SELECT day,venue,motor,motor_epoch,starts,win_rate,two_rate,three_rate,source_url FROM pre.motor_stats')
  # Source's accepted flag is supplemented with an independent aware-time check.
  for r in c.execute("SELECT p.code,p.race_day,p.venue,p.deadline,p.asof,s.wind,s.wind_direction,s.wave_cm,p.source_url FROM pre.preview p JOIN pre.conditions s ON s.code=p.code WHERE p.category='previews/sui' AND p.before_deadline=1").fetchall():
   try:
    asof=datetime.datetime.fromisoformat(r[4].replace('Z','+00:00'))
    day=r[1];deadline=datetime.datetime.fromisoformat(day+'T'+r[3]);deadline=deadline.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=9))) if deadline.tzinfo is None else deadline
    if asof.tzinfo is None or asof>deadline:continue
   except (ValueError,TypeError):continue
   c.execute("INSERT OR IGNORE INTO previews VALUES (?,?,?,?,?,?,?,?,?,'pre')",r)
  manifest['preview_rows']=c.execute('select count(*) from previews').fetchone()[0];manifest['motor_rows']=c.execute('select count(*) from motors').fetchone()[0]
 summary('manifest',manifest)
 assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 assert not c.execute('PRAGMA foreign_key_check').fetchall()
 c.commit();c.execute('ANALYZE main');c.execute('VACUUM');c.close();os.replace(tmp,out)
 print(json.dumps({**manifest,'database_bytes':out.stat().st_size},ensure_ascii=False,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--preview');p.add_argument('--out',required=True);a=p.parse_args();build(a.source,a.preview,a.out)
