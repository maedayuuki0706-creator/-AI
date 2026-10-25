// Run: node viewer/tests/browser_research.cjs /path/to/generated-preview
// Requires Playwright WebKit. Optional WEBKIT_EXECUTABLE for a local installation.
const {webkit,devices}=require('playwright');
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(process.argv[2]||'viewer');
const manifest=JSON.parse(fs.readFileSync(path.join(root,'data/history/manifest.json')));
const output=path.resolve(process.env.QA_OUTPUT||'/tmp/boat-browser-qa');fs.mkdirSync(output,{recursive:true});
const types={'.html':'text/html; charset=utf-8','.json':'application/json','.mjs':'text/javascript','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'};
const server=http.createServer((req,res)=>{let p=path.join(root,decodeURIComponent(req.url.split('?')[0]));if(!p.startsWith(root+path.sep)&&p!==root){res.writeHead(403);return res.end();}
 try{if(fs.statSync(p).isDirectory())p=path.join(p,'index.html');res.writeHead(200,{'content-type':types[path.extname(p)]||'application/octet-stream'});res.end(fs.readFileSync(p));}catch{res.writeHead(404);res.end('not found');}});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 const browser=await webkit.launch(process.env.WEBKIT_EXECUTABLE?{executablePath:process.env.WEBKIT_EXECUTABLE}:{});
 const report={browser:browser.version(),checks:[],devices:[]};
 try{
 for(const [name,config] of [['iphone13',devices['iPhone 13']],['iphoneSE',devices['iPhone SE']],['desktop',{viewport:{width:1440,height:900}}]]){
  const context=await browser.newContext(config),page=await context.newPage(),requests=[],errors=[];
  page.on('request',r=>requests.push(r.url()));page.on('pageerror',e=>errors.push(e.message));
  const start=Date.now();assert.equal((await page.goto(origin+'/analysis/')).status(),200);
  await page.waitForFunction(()=>document.querySelector('#history-status').textContent.includes('Rヒット'));
  const ready=Date.now()-start;
  assert.ok(!requests.some(u=>u.includes('/players/')), 'player histories must be lazy');
  assert.ok(!requests.some(u=>u.includes('/public/players.json')), 'player DB must be lazy');
  assert.ok(!requests.some(u=>u.includes('/indices/')), 'AI indices must be lazy');
  const initial=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,resources:performance.getEntriesByType('resource').map(r=>({url:new URL(r.name).pathname,bytes:r.transferSize}))}));
  assert.ok(initial.scroll<=initial.width,'no horizontal page overflow');
  assert.ok(initial.resources.filter(r=>/history\/\d/.test(r.url)).length<=2);
  await page.screenshot({path:path.join(output,name+'-results.png'),fullPage:false});
  await page.locator('#h-from').fill('2025-10-18');await page.locator('#history-form button').click();
  await page.waitForFunction(n=>document.querySelector('#history-status').textContent.startsWith(n+'R'),manifest.counts.indexed);
  await page.locator('#h-venue').selectOption('03');await page.locator('#h-wind-max').fill('0');await page.locator('#history-form button').click();
  await page.waitForFunction(()=>document.querySelector('#history-status').textContent.includes('Rヒット'));
  assert.ok((await page.locator('#history-rows tr').count())>0);
  await page.locator('#h-from').fill('2026-10-24');await page.locator('#h-to').fill('2025-10-18');await page.locator('#history-form button').click();
  await page.waitForFunction(()=>document.querySelector('#history-status').textContent.includes('エラー'));
  assert.equal(await page.locator('#history-metrics .metric').count(),0);
  await page.locator('#tab-players').click();await page.waitForFunction(()=>document.querySelector('#player-status').textContent.includes('名が条件'));
  await page.locator('#p-query').fill('4238');await page.locator('#player-form button').click();await page.locator('#player-rows button').first().click();
  await page.waitForFunction(()=>document.querySelector('#player-detail').textContent.includes('条件内の直近10走'));
  await page.locator('#p-venue').selectOption('06');await page.locator('#p-window').selectOption('90');
  await page.waitForFunction(()=>document.querySelector('#player-detail').textContent.includes('条件内の直近10走'));
  await page.locator('#player-detail').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,name+'-player.png')});
  await page.locator('#sim-order').fill('123564');await page.locator('#sim-form button').click();
  await page.waitForFunction(()=>document.querySelectorAll('#sim-results tbody tr').length===6);
  assert.match(await page.locator('#sim-results tbody tr').nth(3).innerText(),/5 \/ 4444/);
  await page.locator('#sim-order').fill('112345');await page.locator('#sim-form button').click();
  await page.waitForFunction(()=>document.querySelector('#sim-status').textContent.includes('1回ずつ'));
  assert.equal(await page.locator('#sim-results tbody tr').count(),0);
  await page.locator('#index-load').click();await page.waitForFunction(()=>document.querySelectorAll('#index-results tbody tr').length===120);
  assert.match(await page.locator('#index-status').innerText(),/事後研究/);
  await page.locator('#index-file').selectOption('5');await page.waitForFunction(()=>document.querySelector('#index-status').textContent.includes('新ゆうき'));
  assert.equal(await page.locator('#index-results tbody tr').count(),120);
  assert.deepEqual(errors,[]);assert.ok(requests.every(u=>u.startsWith(origin)), 'no external/live calls');
  report.devices.push({name,ready_ms_local:ready,initial_transfer_bytes:initial.resources.reduce((s,r)=>s+r.bytes,0),initial_history_chunks:initial.resources.filter(r=>/history\/\d/.test(r.url)).length,width:initial.width,scroll:initial.scroll,errors});
  report.checks.push(name+': search, date validation, environment, lazy loads, player detail, simulation, AI 120, no external traffic');await context.close();
 }
 const context=await browser.newContext(devices['iPhone 13']),page=await context.newPage();
 let fail=true;await page.route('**/data/history/'+manifest.shards.at(-1)+'.json',route=>fail?route.fulfill({status:503,body:'temporary failure'}):route.continue());
 await page.goto(origin+'/analysis/');await page.waitForFunction(()=>document.querySelector('#history-meta').textContent.includes('部分欠測'));
 assert.match(await page.locator('#history-status').innerText(),/一部の期間/);fail=false;
 await page.locator('#history-form button').click();await page.waitForFunction(()=>!document.querySelector('#history-meta').textContent.includes('部分欠測')&&document.querySelector('#history-status').textContent.includes('Rヒット'));
 report.checks.push('partial 503 explicitly labelled; retry restores missing chunk');await context.close();
 const bad=await browser.newContext();const bp=await bad.newPage();await bp.route('**/data/history/manifest.json',route=>route.fulfill({status:503,body:'down'}));
 await bp.goto(origin+'/analysis/');await bp.waitForFunction(()=>document.querySelector('#history-status').textContent.includes('エラー'));
 assert.equal(await bp.locator('#history-metrics .metric').count(),0);report.checks.push('manifest 503: no stale fallback, no fabricated ratios');await bad.close();
 fs.writeFileSync(path.join(output,'browser-report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
 }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
