import test from 'node:test';
import assert from 'node:assert/strict';
import {gzipSync} from 'node:zlib';
import {winpathQuery} from '../src/winpath-api.mjs';

const count=(n,w,method,loss={},extra={})=>({
 n,w,t2:w,t3:w,sn:n,ss:n*0.13,method,loss,in_escape:0,...extra
});
const person={id:'4238',name:'検証選手',rows:{
 'all|all|course|1':count(10,7,{'逃げ':6,'抜き':1},{'まくり':2,'差し':1}),
 '2025|07|course|2':count(5,1,{'差し':1},{'逃げ':3,'まくり':1},{in_escape:3}),
 'all|all|frame|1':count(10,7,{'逃げ':6,'抜き':1},{'まくり':2,'差し':1})
}};
const encoded=gzipSync(Buffer.from(JSON.stringify(person))).toString('base64');
const store={
 'release/winpaths/p084.json':{'4238':encoded},
 'release/winpaths/baseline.json':{rows:{
   'all|all|course|1':count(100,55,{'逃げ':53,'抜き':2},{'まくり':25,'差し':20}),
   '2025|07|course|2':count(100,20,{'差し':12,'まくり':8},{'逃げ':60,'まくり差し':20},{in_escape:60}),
   'all|all|frame|1':count(100,55,{'逃げ':53,'抜き':2},{'まくり':25,'差し':20})
 }}
};
const env={DATA_BACKEND:'r2',DATA_READY:'1',DATA_PREFIX:'release',ARCHIVE:{
 async get(key){return store[key]?{json:async()=>store[key]}:null}
}};
test('1-course escape and loss denominators are not conflated',async()=>{
 const j=await winpathQuery(new Request('https://private.invalid/api/winpaths?ids=4238&basis=course&lanes=1&frames=1'),env);
 assert.equal(j.rows[0].sample.winRate,70);
 assert.equal(j.rows[0].sample.escapeRate,60);
 assert.equal(j.rows[0].sample.beatenByMakuriRate,66.7); // two losses out of three
 assert.equal(j.rows[0].sample.beatenBySashiRate,33.3);
 assert.equal(j.rows[0].sample.lostCount,3);
});
test('2-course nigashi rate counts in escapes against all course-2 starts',async()=>{
 const j=await winpathQuery(new Request('https://private.invalid/api/winpaths?ids=4238&basis=course&venue=07&period=2025&lanes=2&frames=5'),env);
 assert.equal(j.rows[0].frame,5);
 assert.equal(j.rows[0].sample.nigashiRate,60);
 assert.equal(j.rows[0].sample.winRate,20);
 assert.equal(j.rows[0].sample.sashiRate,20);
});
test('rejects invalid input and unready dataset',async()=>{
 await assert.rejects(()=>winpathQuery(new Request('https://private.invalid/api/winpaths?ids=4238,___'),env));
 const j=await winpathQuery(new Request('https://private.invalid/api/winpaths?ids=4238'),{...env,DATA_READY:'0'});
 assert.ok(j.error);
});
