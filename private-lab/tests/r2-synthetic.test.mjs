import test from 'node:test';
import assert from 'node:assert/strict';
import {api} from '../src/worker.mjs';

// Non-sensitive, generated fixtures. These run in GitHub CI without owner research data.
function fixtures(objects) {
  let reads=[];
  const env={
    DATA_BACKEND:'r2',DATA_PREFIX:'query',DETAIL_PREFIX:'details',
    ARCHIVE:{async get(key) {
      reads.push(key);
      const value=objects[key];
      return value===undefined?null:{
        json:async()=>structuredClone(value),
        body:new TextEncoder().encode(JSON.stringify(value))
      };
    }}
  };
  const call=async (endpoint)=>{
    const response=await api(new Request('https://lab.test/api/'+endpoint),env);
    return {status:response.status,...await response.json()};
  };
  return {call,reads};
}
const mkRow=(day,venue,rno,payout=1000)=>({
  day,id:day.replaceAll('-','')+venue+String(rno).padStart(2,'0'),
  venue,rno,result:'1-2-3',payout,method:'逃げ',wind:2,wave:2,phase:'post'
});
test('R2 AI research page fails safely with 未取得 instead of attempting nonexistent DB',async()=>{
  const {call,reads}=fixtures({});
  const j=await call('ai');
  assert.equal(j.status,200);
  assert.deepEqual(j.rows,[]);
  assert.match(j.note,/未取得/);
  assert.deepEqual(reads,[]);
});
test('R2 motor number filter matches numeric and string source values',async()=>{
  const {call}=fixtures({
    'query/motors/03.json':[
      {day:'2026-10-01',venue:'03',motor:61,starts:12},
      {day:'2026-10-02',venue:'03',motor:'61',starts:13},
      {day:'2026-10-02',venue:'03',motor:62,starts:14}
    ]
  });
  const j=await call('motors?venue=03&motor=61');
  assert.equal(j.status,200);
  assert.deepEqual(j.rows.map(x=>x.starts),[12,13]);
  const missing=await call('motors');
  assert.equal(missing.status,200);
  assert.equal(missing.rows.length,0);
});
test('R2 8-shard sparse pagination does not drop a race or duplicate a record',async()=>{
  const days=Array.from({length:12},(_,i)=>'2025-01-'+String(12-i).padStart(2,'0'));
  const objs={'query/races/index.json':days.map(day=>({day,venues:['03']}))};
  days.forEach((day,i)=>objs['query/races/'+day+'.json']=[mkRow(day,'03',1,i%3===0?12000:1000)]);
  const {call,reads}=fixtures(objs);
  const a=await call('races?venue=03&high=1');
  assert.equal(a.status,200);
  assert.ok(a.next,'sparse scan should yield continuation');
  const b=await call('races?venue=03&high=1&after='+a.next);
  assert.equal(b.status,200);
  const combined=[...a.rows,...b.rows];
  assert.equal(combined.length,4);
  assert.equal(new Set(combined.map(x=>x.id)).size,4);
  assert.deepEqual(combined.map(x=>x.day),['2025-01-12','2025-01-09','2025-01-06','2025-01-03']);
  assert.ok(reads.filter(key=>key.startsWith('query/races/2025')).length<=12);
});
test('R2 normal 30-result pagination, date bounds and high-payout filter are stable',async()=>{
  const day='2025-01-12';
  // 48 generated rows on one day (24 venues * 2 races).
  const rows=[];
  for(let v=1;v<=24;v++)for(let rno=1;rno<=2;rno++)
    rows.push(mkRow(day,String(v).padStart(2,'0'),rno,v===24?13000:1000));
  rows.sort((a,b)=>b.id.localeCompare(a.id));
  const objs={
    'query/races/index.json':[{day,venues:rows.map(x=>x.venue)}],
    ['query/races/'+day+'.json']:rows
  };
  const {call}=fixtures(objs);
  const a=await call('races');
  assert.equal(a.rows.length,30);
  assert.ok(a.next);
  const b=await call('races?after='+a.next);
  assert.equal(b.rows.length,18);
  assert.equal(b.next,null);
  assert.equal(new Set([...a.rows,...b.rows].map(x=>x.id)).size,48);
  const high=await call('races?high=1&from=2025-01-12&to=2025-01-12');
  assert.equal(high.rows.length,2);
  assert.ok(high.rows.every(r=>r.payout>=10000));
  const no=await call('races?from=2025-01-13&to=2025-01-20');
  assert.equal(no.rows.length,0);
});
test('R2 missing data explicitly returns 404, no other race substitution',async()=>{
  const {call}=fixtures({});
  const data=await call('race?id=202201012402');
  assert.equal(data.status,404);
  assert.equal(data.error,'未取得');
});
