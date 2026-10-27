import fs from 'node:fs';
import path from 'node:path';
const name=process.argv[2]||new URL('../wrangler.json',import.meta.url);
const config=JSON.parse(fs.readFileSync(name));
const isWorkerDev=config.workers_dev===true && config.preview_urls===false;
const domainRoute=config.workers_dev===false && config.preview_urls===false &&
  config.routes?.some(r=>r.custom_domain===true && typeof r.pattern==='string' && r.pattern.includes('.'));
const r2=config.vars?.DATA_BACKEND==='r2';
const checks={
 worker_first:config.assets?.run_worker_first===true,
 preview_disabled:config.preview_urls===false,
 team:/^[a-z0-9-]+$/.test(config.vars?.ACCESS_TEAM||''),
 aud:typeof config.vars?.ACCESS_AUD==='string'&&config.vars.ACCESS_AUD.length>12,
 allowlist:typeof config.vars?.ALLOWED_EMAILS==='string' &&
   config.vars.ALLOWED_EMAILS.split(',').every(x=>/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(x.trim())),
 backend:r2,
 private_r2_binding:config.r2_buckets?.some(x=>x.binding==='ARCHIVE' && typeof x.bucket_name==='string' && x.bucket_name.length>0),
 route:isWorkerDev||domainRoute,
 no_public_fallback:config.preview_urls===false
};
const publicDir=new URL('../public/',import.meta.url);
const actual=fs.readdirSync(publicDir).sort();
const allowed=['app.js','index.html','style.css'];
checks.assets=JSON.stringify(actual)===JSON.stringify(allowed);
for(const [key,ok] of Object.entries(checks))console.log(key,ok?'PASS':'BLOCKED');
if(Object.values(checks).some(ok=>!ok)){
 console.error('NOT READY. Refusing private research data upload/deployment.');
 process.exitCode=1;
}else{
 console.log('Configuration preflight PASS. Still verify Cloudflare Access on Worker and R2 privacy using dashboard.');
}
