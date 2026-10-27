"""Manual authenticated uploader for a NEW private release prefix.
Requires prior owner login, private bucket, Access tests, and an explicit operator flag.
Uses Wrangler's local OAuth session; never accepts a key/password as an argument.
"""
import argparse,pathlib,subprocess,concurrent.futures,json,re,hashlib
p=argparse.ArgumentParser();p.add_argument('--bucket',required=True);p.add_argument('--release',required=True);p.add_argument('--query',required=True);p.add_argument('--details',required=True);p.add_argument('--wrangler',default='wrangler');p.add_argument('--verified-access-and-private-bucket',action='store_true');a=p.parse_args()
if not a.verified_access_and_private_bucket:raise SystemExit('First verify Access allow/deny, disabled preview/workers.dev and private R2 bucket.')
if not re.fullmatch(r'[a-z0-9-]{3,63}',a.bucket) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',a.release):raise SystemExit('Invalid bucket/release')
query=pathlib.Path(a.query).resolve();detail=pathlib.Path(a.details).resolve();manifest=json.loads((query/'upload-manifest.json').read_text());tasks=[]
for o in manifest['objects']:
 f=(query/o['key']).resolve()
 if query not in f.parents or hashlib.sha256(f.read_bytes()).hexdigest()!=o['sha256']:raise SystemExit('Invalid path or changed object; rebuild first')
 tasks.append((f,'query/'+o['key']))
for f in sorted(detail.glob('*.json')):
 if re.fullmatch(r'\d{12}\.json',f.name):tasks.append((f,'details/'+f.name))
log=query/('uploaded-'+a.release+'.json');done=set(json.loads(log.read_text()) if log.exists() else [])
def send(task):
 f,key=task
 r=subprocess.run([a.wrangler,'r2','object','put',a.bucket+'/releases/'+a.release+'/'+key,'--file',str(f),'--content-type','application/json','--remote'],capture_output=True,text=True)
 return key,r.returncode
fail=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 for key,code in pool.map(send,[t for t in tasks if t[1] not in done]):
  if code:fail.append(key)
  else:done.add(key)
  log.write_text(json.dumps(sorted(done)))
  if len(done)%100==0:print('Uploaded',len(done),'of',len(tasks),flush=True)
print(json.dumps({'uploaded':len(done),'planned':len(tasks),'failed':fail}))
if fail:raise SystemExit(1)
print('Upload complete. Only now switch DATA_PREFIX and DETAIL_PREFIX to this release, then validate authenticated counts.')
