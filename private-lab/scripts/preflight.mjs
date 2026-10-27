import fs from 'node:fs';import path from 'node:path';
const config=JSON.parse(fs.readFileSync(process.argv[2]||new URL('../wrangler.json',import.meta.url)));
const checks={worker_first:config.assets?.run_worker_first===true,workers_dev_disabled:config.workers_dev===false,preview_disabled:config.preview_urls===false,team:/^[a-z0-9-]+$/.test(config.vars?.ACCESS_TEAM||''),aud:!!config.vars?.ACCESS_AUD,allowlist:!!config.vars?.ALLOWED_EMAILS,database:config.vars?.DATA_BACKEND==='r2'||config.d1_databases?.every(d=>d.database_id!=='00000000-0000-0000-0000-000000000000'),custom_domain:config.routes?.some(r=>r.custom_domain===true)};
for(const [k,v] of Object.entries(checks))console.log(k,v?'PASS':'BLOCKED');
const publicDir=new URL('../public/',import.meta.url);const allowed=new Set(['index.html','app.js','style.css']);for(const name of fs.readdirSync(publicDir)){if(!allowed.has(name)){checks.assets=false;console.log('unexpected asset BLOCKED',path.basename(name));}}
if(Object.values(checks).some(v=>!v))process.exitCode=1;
