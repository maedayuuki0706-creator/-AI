import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {mergeHistory,filterHistory,summarizeHistory,rankPlayers} from '../assets/analysis-core.mjs';

test('reject invalid, refunded/malformed and duplicate archived outcomes', () => {
 const part={counts:{source:4,skip:1},rows:[
  ['20261008','09',1,'1-2-3',1200],['20261008','09',1,'1-2-3',1200],
  ['20261008','09',2,'2-3-4',10800],['20261008','09',3,'1-1-2',500]
 ]};
 const history=mergeHistory([part]);
 assert.equal(history.rows.length,2);
 assert.equal(history.rejected,2);
 assert.equal(history.source,4);
 assert.equal(history.skipped,1);
 assert.equal(filterHistory(history.rows,{venue:'09',manshu:true}).length,1);
 assert.equal(filterHistory(history.rows,{first:'1'}).length,1);
 assert.equal(summarizeHistory(history.rows).manshu,1);
 assert.equal(summarizeHistory([]).rate,null);
});

test('course rank preserves zero versus missing, supports name and ST sorting', () => {
 const payload={data:{
 '4238':{name:'毒島 誠',class:'A1',branch:'群馬',course_win:[80,0,null,2,0,0],win:8.1,avg_st:0.13},
 '4418':{name:'茅原 悠紀',class:'A1',branch:'岡山',course_win:[71,21,30,4,5,0],win:8.2,avg_st:0.14}
 }};
 assert.equal(rankPlayers(payload,{course:1})[0].id,'4238');
 assert.equal(rankPlayers(payload,{course:2})[0].id,'4418');
 assert.equal(rankPlayers(payload,{course:2,minimum:0}).length,2);
 assert.equal(rankPlayers(payload,{course:3}).length,1);
 assert.equal(rankPlayers(payload,{course:1,query:'毒島'})[0].id,'4238');
 assert.equal(rankPlayers(payload,{course:1,sort:'national'})[0].id,'4418');
});

test('verified history assets reconcile with manifest and UI', async () => {
 const root=new URL('../',import.meta.url);
 const manifest=JSON.parse(await readFile(new URL('data/history/manifest.json',root),'utf8'));
 assert.ok(manifest.shards.length>=1);
 const shards=await Promise.all(manifest.shards.map(async name=>JSON.parse(await readFile(new URL('data/history/'+name+'.json',root),'utf8'))));
 const result=mergeHistory(shards);
 assert.ok(result.rows.length>0);
 assert.equal(result.source,result.rows.length+result.skipped+result.rejected);
 assert.equal(summarizeHistory(result.rows).heads.reduce((a,b)=>a+b,0),result.rows.length);
 const page=await readFile(new URL('analysis/index.html',root),'utf8');
 for(const id of ['history-form','h-venue','history-chart','player-form','player-rows','player-detail']) assert.ok(page.includes('id="'+id+'"'));
 assert.ok(page.includes('analysis.mjs'));
});
