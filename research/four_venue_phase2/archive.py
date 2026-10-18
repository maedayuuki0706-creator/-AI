"""Deterministic research packaging. Does not upload or modify existing logs."""
import argparse,gzip,io,json,sqlite3,zipfile
from pathlib import Path
from .collect import VENUES
from research.edogawa_phase2.acquire import put,digest

def archive_zip(path,items):
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,body in sorted(items):
            info=zipfile.ZipInfo(name,date_time=(2026,10,18,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o644<<16;z.writestr(info,body)
    put(path,data.getvalue())

def run(study,report,root):
    study,report,root=Path(study),Path(report),Path(root);summary=json.loads((study/'summary.json').read_text())
    source=sqlite3.connect(study/'four_venue_history.sqlite');manifest={'study':str(study),'files':[],'databases':{}}
    schema=[r[0] for r in source.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND type IN ('table','index') ORDER BY type DESC,name")]
    for jcd,name in VENUES.items():
        db=study/jcd/'history.sqlite'
        if not db.exists():
            dest=sqlite3.connect(db)
            for sql in schema:dest.execute(sql)
            for table in ['races','boats','calendar','audit_missing','audit_differences','planned_without_result']:
                query='SELECT * FROM '+table+' WHERE venue_code=?' if table!='boats' else 'SELECT b.* FROM boats b JOIN races r ON b.race_id=r.race_id WHERE r.venue_code=?'
                cursor=source.execute(query,(jcd,));rs=cursor.fetchall();cols=len(cursor.description)
                dest.executemany('INSERT INTO '+table+' VALUES('+','.join('?' for _ in range(cols))+')',rs)
            dest.commit();dest.close()
        con=sqlite3.connect(db);manifest['databases'][jcd]={'venue':name,'races':con.execute('SELECT count(*) FROM races').fetchone()[0],'boats':con.execute('SELECT count(*) FROM boats').fetchone()[0],'integrity':con.execute('PRAGMA integrity_check').fetchone()[0]};con.close()
        items=[]
        for p in sorted((study/jcd).iterdir()):
            if p.suffix not in ['.csv','.json','.sqlite']:continue
            body=p.read_bytes();items.append((p.name+'.gz',gzip.compress(body,mtime=0)))
        bundle=study/f'venue_{jcd}_database_analysis.zip';archive_zip(bundle,items)
        manifest['files'].append({'path':str(bundle),'sha256':digest(bundle.read_bytes()),'bytes':bundle.stat().st_size})
    source.close()
    for folder in [root/'programs/raw']:
        files=sorted(folder.glob('*.lzh'));parts=[[],[]]
        for i,f in enumerate(files):parts[i%2].append(('raw/'+f.name,f.read_bytes()))
        for i,items in enumerate(parts,1):
            revision=summary['program_acquisition_digest'][:12]
            p=root/'programs'/f'official_B_raw_{revision}_{i}.zip';archive_zip(p,items);manifest['files'].append({'path':str(p),'sha256':digest(p.read_bytes()),'bytes':p.stat().st_size})
    archive_zip(study/'retrospective_replays.zip',[(p.name,p.read_bytes()) for p in (study/'replays').glob('*.json')])
    # Large machine-readable tables remain individual gzip files for reuse.
    for p in [study/'audited_races.json',study/'analysis_tables.json',report/'workbook_data.json']:
        put(Path(str(p)+'.gz'),gzip.compress(p.read_bytes(),mtime=0))
    for name in ['missing','differences','coverage','program_only','historical_validation','paired_comparison']:
        p=study/(name+'.csv');put(Path(str(p)+'.gz'),gzip.compress(p.read_bytes(),mtime=0))
    put(study/'artifact_manifest.json',json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2).encode())
    print(json.dumps(manifest,ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--study',required=True);p.add_argument('--report',required=True);p.add_argument('--root',required=True);a=p.parse_args();run(a.study,a.report,a.root)
