import fs from 'node:fs';
const team=process.env.CF_ACCESS_TEAM||'';
const aud=process.env.CF_ACCESS_AUD||'';
const allow=process.env.CF_ALLOWED_EMAILS||'';
const valid=x=>typeof x==='string' && x.length>0;
if(!/^[a-z0-9-]+$/.test(team)||!valid(aud)||aud.length<=12||
 !allow.split(',').every(x=>/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(x.trim()))){
 console.error('BLOCKED: Missing Access team, audience or owner allowlist. Do not paste values in GitHub.');
 process.exit(1);
}
const file=new URL('../wrangler.json',import.meta.url);
const config=JSON.parse(fs.readFileSync(file,'utf8'));
config.workers_dev=true;
config.preview_urls=false;
delete config.routes;
config.vars.ACCESS_TEAM=team;
config.vars.ACCESS_AUD=aud;
config.vars.ALLOWED_EMAILS=allow;
config.vars.DATA_BACKEND='r2';
const target=new URL('../wrangler.local.json',import.meta.url);
fs.writeFileSync(target,JSON.stringify(config,null,2)+'\n',{encoding:'utf8',mode:0o600,flag:'w'});
fs.chmodSync(target,0o600);
console.log('Configured private workers.dev target in ignored wrangler.local.json (no secrets printed).');
console.log('NEXT: node scripts/preflight.mjs wrangler.local.json');
