// Smoke-check a PRIVATE, locally downloaded R2 export without uploading its contents.
// Usage: LAB_PRIVATE_R2=/absolute/private/release node scripts/smoke_private_release.mjs
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {api} from '../src/worker.mjs';

const root=process.env.LAB_PRIVATE_R2;
if(!root||!path.isAbsolute(root))throw Error('Set LAB_PRIVATE_R2 to an absolute PRIVATE release folder path.');
const env={DATA_BACKEND:'r2',DATA_PREFIX:'query',DETAIL_PREFIX:'details',
  ARCHIVE:{async get(key){
    // Object names are only supplied by audited API handlers. Keep queries within local release.
    const file=path.resolve(root,key);
    if(!file.startsWith(path.resolve(root)+path.sep))throw Error('R2 path escapes release directory');
    try{const raw=await readFile(file);return {body:raw,json:async()=>JSON.parse(raw.toString('utf8'))};}
    catch(e){if(e.code==='ENOENT')return null;throw e;}
  }}};
const request=async url=>{
  const r=await api(new Request('https://private.invalid/api/'+url),env);
  const body=await r.json();
  assert.equal(r.status,200,url+' status '+r.status);
  return body;
};
const manifest=await request('status');
assert.ok(Number.isInteger(manifest.races)&&manifest.races>0,'race count');
assert.ok(Number.isInteger(manifest.entries)&&manifest.entries===manifest.races*6,'complete six-boat samples');
assert.ok(Number.isInteger(manifest.players)&&manifest.players>0,'player count');
const first=await request('races?high=1');
assert.equal(first.rows.length,30);
assert.ok(first.next);
const second=await request('races?high=1&after='+encodeURIComponent(first.next));
assert.equal(new Set([...first.rows,...second.rows].map(x=>x.id)).size,first.rows.length+second.rows.length);
assert.ok([...first.rows,...second.rows].every(x=>x.payout>=10000));
for(const endpoint of ['races?venue=03&from=2024-01-01&to=2024-12-31',
  'players?q=%E6%AF%92%E5%B3%B6','player?id=4238&venue=03',
  'water?venue=03','manshu?venue=03','motors?venue=03&motor=61',
  'previews?venue=03','archive?id=202610011401','ai'])await request(endpoint);
console.log('PASS: private release smoke: race count',manifest.races,
  'entries',manifest.entries,'players',manifest.players,'API scenarios 12, no race ID overlap.');
console.log('No raw research content, authentication token, or private storage path printed.');
