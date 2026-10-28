import test from 'node:test';
import assert from 'node:assert/strict';
import {packageWorker} from '../scripts/package_worker.mjs';
test('connector package uses canonical auth and embeds only three assets',async()=>{
 const pkg=await packageWorker();assert.equal(pkg.main_module,'entry.mjs');
 assert.deepEqual(pkg.files.map(f=>f.name),['src/worker.mjs','src/auth.mjs','src/r2-api.mjs','src/packed-r2.mjs','embedded-assets.mjs','entry.mjs']);
 const module=await import('data:text/javascript;base64,'+Buffer.from(pkg.files.find(f=>f.name==='embedded-assets.mjs').content).toString('base64'));
 for(const path of ['/','/index.html','/app.js','/style.css'])assert.equal((await module.assets.fetch(new Request('https://local.test'+path))).status,200);
 for(const path of ['/src/auth.mjs','/data/search.sqlite','/anything'])assert.equal((await module.assets.fetch(new Request('https://local.test'+path))).status,404);
 assert.equal(await (await module.assets.fetch(new Request('https://local.test/app.js',{method:'HEAD'}))).text(),'');
});
