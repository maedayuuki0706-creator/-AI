import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {filterEnvironment,summarizePlayer,entrySimulation,mergeHistory} from '../assets/analysis-core.mjs';
const root=new URL('../data/',import.meta.url);
const load=async p=>JSON.parse(await readFile(new URL(p,root),'utf8'));
test('environment zero is observed, missing is excluded only when filtering',()=>{
 const rows=[[0,0,0,0,0,{wind:0,direction:'北',entry_changed:false}],[0,0,0,0,0,{wind:null}],[0,0,0,0,0,{wind:5,entry_changed:true}]];
 assert.equal(filterEnvironment(rows).length,3);assert.equal(filterEnvironment(rows,{windMax:0}).length,1);
 assert.equal(filterEnvironment(rows,{windMin:0}).length,2);assert.equal(filterEnvironment(rows,{entry:'same'}).length,1);
 assert.equal(filterEnvironment(rows,{direction:'北'}).length,1);
});
test('player abnormal appearances remain in denominator, ST zero and actual course are retained',()=>{
 const rows=[['20261001','03',1,2,1,0,1,0,6.7],['20261002','03',1,2,null,null,1,null,null],['20261003','06',1,1,2,.2,2,6,6.8]];
 const a=summarizePlayer(rows,{venue:'03',course:2});assert.equal(a.n,2);assert.equal(a.firstRate,50);assert.equal(a.unclassified,1);assert.equal(a.st,0);assert.equal(a.stN,1);assert.equal(a.local[7],0);
 assert.equal(summarizePlayer(rows,{course:1}).n,1);assert.equal(summarizePlayer(rows,{from:'20261003'}).n,1);
 assert.equal(summarizePlayer([]).firstRate,null);
});
test('entry mapping uses actual course history and suppresses sparse indices',()=>{
 const ids=['4238','4418','4586','4320','4444','3960'];const histories={'4444':Array.from({length:20},()=>['20261001','03',1,4,1,.1,5,null,6.7])};
 const result=entrySimulation(ids,'123564',histories);assert.equal(result[3].lane,5);assert.equal(result[3].index,120);assert.equal(result[4].index,null);
 assert.throws(()=>entrySimulation(ids,'112345',histories));assert.throws(()=>entrySimulation([...ids.slice(0,5),'4238'],'123456',{}));
});
test('all generated payout, player and field coverage counts reconcile',async()=>{
 const m=await load('history/manifest.json'),q=await load('research/quality.json'),p=await load('research/manifest.json');
 const h=mergeHistory(await Promise.all(m.shards.map(s=>load('history/'+s+'.json'))));
 assert.equal(h.rows.length,m.counts.indexed);assert.equal(h.rejected,0);assert.equal(q.indexed,h.rows.length);
 assert.equal(q.counts.source,q.indexed+q.counts.duplicates+Object.values(q.exclusions).reduce((a,b)=>a+b,0)+(q.counts.conflicting_records??0));
 for(const [field,count] of Object.entries(q.missing_races))assert.equal(h.rows.filter(r=>r[5]?.[field]===null||r[5]?.[field]===undefined).length,count);
 const keys=new Set(h.rows.map(r=>r.slice(0,3).join('|')));let records=0,players=0;
 for(const file of Object.values(p.players)){const bucket=await load('research/players/'+file);for(const rows of Object.values(bucket.data)){players++;records+=rows.length;const unique=new Set();for(const row of rows){const key=row.slice(0,3).join('|');assert.ok(keys.has(key));assert.ok(!unique.has(key));unique.add(key);}}}
 assert.equal(records,q.player_records);assert.equal(players,q.players);
});
test('frozen AI indices contain exactly 120 unique permutations and preserve research flags',async()=>{
 const manifest=await load('research/indices/manifest.json');let n=0;
 for(const f of manifest.files){const payload=await load('research/indices/'+f.file);assert.equal(payload.calibrated,false);assert.equal(payload.prospective_index_verified,false);
  for(const r of payload.races){n++;assert.equal(r.ranks.length,120);assert.equal(new Set(r.ranks.map(x=>x[1])).size,120);for(const row of r.ranks){assert.equal(new Set(row[1].split('-')).size,3);assert.ok(row[2]>=0&&row[2]<=100);assert.ok(row[6]+row[7]-1<=120);}}
 }assert.equal(n,manifest.races);
});
