import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import worker from '../src/worker.mjs';

const bootstrap=JSON.parse(fs.readFileSync(new URL('../wrangler.bootstrap.json',import.meta.url)));
test('bootstrap works on workers.dev without a paid domain, but refuses every anonymous request',async()=>{
  assert.equal(bootstrap.workers_dev,true);
  assert.equal(bootstrap.preview_urls,false);
  assert.equal(bootstrap.assets.run_worker_first,true);
  assert.equal(bootstrap.r2_buckets,undefined);
  assert.equal(bootstrap.vars.ACCESS_TEAM,'');
  assert.equal(bootstrap.vars.ACCESS_AUD,'');
  assert.equal(bootstrap.vars.ALLOWED_EMAILS,'');
  for(const path of ['/','/index.html','/app.js','/style.css','/api/status','/api/race?id=202201012402']){
    let hit=false;
    const env={...bootstrap.vars,ASSETS:{fetch:()=>{hit=true;return new Response('UNSAFE');}}};
    const res=await worker.fetch(new Request('https://boat-private-lab.example.workers.dev'+path),env);
    assert.equal(res.status,403,path);
    assert.equal(hit,false,path);
  }
});
