// Optional private integration test. Neither fixtures nor records belong in git.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {api} from '../src/worker.mjs';
import {database} from '../scripts/local.mjs';
const root=process.env.LAB_PACKED;
const enabled=!!root&&!!process.env.LAB_DB;
const env={DATA_BACKEND:'r2',R2_PACKED:'1',DATA_PREFIX:'query',ARCHIVE:{async get(key){try{const bytes=await readFile(path.join(root,key));return {json:async()=>JSON.parse(bytes)};}catch(e){if(e.code==='ENOENT')return null;throw e;}}}};
const call=async(route,e=env)=>(await api(new Request('https://test.invalid/api/'+route),e)).json();
const stable=x=>JSON.parse(JSON.stringify(x,(k,v)=>k==='avg_st'&&v!==null?Number(v.toFixed(9)):v));
test('private packed API matches SQLite races, player groups, wind and high payouts',{skip:!enabled},async()=>{
 const db=database(process.env.LAB_DB);
 try{
  for(const route of ['races?high=1','races?venue=03&from=2024-01-01&to=2024-12-31','race?id=202201012402','water?venue=03&wind=2','manshu?venue=03'])assert.deepEqual(stable(await call(route)),stable(await call(route,{DB:db})),route);
  for(const route of ['player?id=4238','player?id=4238&venue=03&from=2024-01-01&to=2024-12-31']){const a=await call(route),b=await call(route,{DB:db});assert.deepEqual(stable(a.stats),stable(b.stats),route);assert.equal(a.player.starts,b.player.starts);}
  assert.equal((await call('players?q=毒島')).rows[0].id,'4238');
  const m=await call('status');assert.equal(m.races,205269);assert.equal(m.entries,1231614);assert.equal(m.players,1794);
 }finally{db.close();}
});
test('private packed pages, missing records and unavailable 2026/AI data',{skip:!enabled},async()=>{
 const a=await call('races?high=1'),b=await call('races?high=1&after='+a.next);
 assert.equal(new Set([...a.rows,...b.rows].map(r=>r.id)).size,60);
 assert.equal((await call('races?from=1900-01-01&to=1900-12-31')).rows.length,0);
 assert.equal((await call('race?id=190001010101')).error,'未取得');
 for(const route of ['motors?venue=03&motor=61','previews?venue=03','ai'])assert.deepEqual((await call(route)).rows,[]);
});
