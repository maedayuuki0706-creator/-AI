import {createRequire} from 'node:module';
const {chromium}=createRequire(import.meta.url)('playwright');
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const page=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('https://lab.test/**',async r=>{const p=new URL(r.request().url()).pathname;if(p.startsWith('/api/'))return r.fulfill({status:404,contentType:'application/json',body:JSON.stringify({error:'QA：R2本人セッションは未接続'})});try{const f=path.resolve('private-lab/public',p==='/'?'index.html':p.slice(1));const body=await readFile(f);return r.fulfill({body,contentType:p.endsWith('.js')?'text/javascript':p.endsWith('.css')?'text/css':p.endsWith('.json')?'application/json':'text/html'});}catch{return r.fulfill({status:404,body:'not found'});}});
await page.goto('https://lab.test');await page.locator('.top3-card').last().waitFor();assert.equal(await page.locator('.top3-card').count(),6);assert.deepEqual(await page.locator('.lane-badge').allTextContents(),['1','2','3','4','5','6']);
await page.getByRole('button',{name:'最新の保存レースを見る'}).click();await page.getByText(/出典：/).waitFor();
await page.getByRole('button',{name:'児島の展開研究を見る'}).click();await page.getByText('展開研究：勝ち筋・負け筋').first().waitFor();assert.equal(await page.locator('.top3-main strong').first().textContent(),'未算出');
await page.locator('details summary').first().click();await page.getByText('QA：R2本人セッションは未接続').waitFor();
for(const width of [375,390,430,1280]){await page.setViewportSize({width,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`overflow ${width}`);}
await page.setViewportSize({width:390,height:844});await page.screenshot({path:'/workspace/scratch/3dc1688599fa/boat-lab-top3-mobile.png',fullPage:true});assert.deepEqual(errors,[]);console.log('PASS: six lanes, missing today, archive selection, scenario, detail error, 375/390/430/1280px, JS errors=0');await browser.close();
