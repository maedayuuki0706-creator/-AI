import test from 'node:test';import assert from 'node:assert/strict';import {fusionQuery} from '../web/fusion-api.mjs';
test('read-only route validates identity and isolates namespace',async()=>{
 let key;const env={ARCHIVE:{get:async k=>(key=k,{body:'{"mode":"retrospective_replay"}'})}};
 assert.equal(await fusionQuery(new Request('https://lab.test/api/other'),env),undefined);
 assert.equal((await fusionQuery(new Request('https://lab.test/api/fusion?id=../../secret'),env)).status,400);
 assert.equal((await fusionQuery(new Request('https://lab.test/api/fusion?id=20261031_16_12',{method:'POST'}),env)).status,405);
 let r=await fusionQuery(new Request('https://lab.test/api/fusion?id=20261031_16_12'),env);
 assert.equal(r.status,200);assert.equal(key,'research/ultimate_fusion_v2/replay/20261031_16_12.json');assert.equal(r.headers.get('Cache-Control'),'private, no-store');
 assert.equal((await fusionQuery(new Request('https://lab.test/api/fusion?id=20261031_16_12'),{})).status,503);
});
