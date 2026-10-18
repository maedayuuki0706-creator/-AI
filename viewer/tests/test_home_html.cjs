'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=process.argv[2]?path.resolve(process.argv[2]):path.join(__dirname,'..'),titles=new Set();
const routes=['','races','race','predictions','motors','racers','lab','sources','privacy','lab/six-boat','lab/manshu','lab/method'];
for(const route of routes){
 const html=fs.readFileSync(path.join(root,route,'index.html'),'utf8');
 const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
 assert.equal(ids.length,new Set(ids).size,'duplicate IDs: '+route);
 assert.equal([...html.matchAll(/<h1[\s>]/g)].length,1,'one h1: '+route);
 const title=/<title>([^<]+)<\/title>/.exec(html)?.[1];
 assert.ok(title&&!titles.has(title),'unique title: '+route);titles.add(title);
 for(const url of ['/','/races/','/predictions/','/motors/','/racers/','/lab/'])assert.ok(html.includes('href="'+url+'"'),'nav '+url);
 for(const text of ['aria-label="メインメニュー"','rel="canonical"','name="description"','property="og:image"','name="twitter:card"','type="application/ld+json"','src="/assets/app.mjs?v=20261019"'])assert.ok(html.includes(text),route+': '+text);
 assert.ok(!html.includes('src="app.js"'),'legacy app not loaded');
 assert.ok(!html.includes('docs.google.com/spreadsheets/'),'no sheet IDs');
 for(const m of html.matchAll(/(?:href|src)="(\/[^"?#]*)(?:[?#][^"]*)?"/g)){
  if(m[1].startsWith('//'))continue;
  assert.ok(fs.existsSync(path.join(root,m[1].endsWith('/')?m[1]+'index.html':m[1])),route+' broken local URL '+m[1]);
 }
}
assert.ok(fs.readFileSync(path.join(root,'assets/site-config.js'),'utf8').includes('"enabled": false'));
const gate=fs.readFileSync(path.join(root,'predictions/index.html'),'utf8');
assert.ok(gate.includes('id="prediction-open" disabled'));
assert.ok(!/\b[1-6]-[1-6]-[1-6]\b/.test(gate),'no initial picks');
const css=fs.readFileSync(path.join(root,'assets/site.css'),'utf8');
for(const text of ['@media(max-width:680px)','@media(max-width:360px)','font-size:16px','prefers-reduced-motion','overflow-x:auto','min-height:46px'])assert.ok(css.includes(text),'mobile contract: '+text);
console.log('PASS 12 routes: unique SEO/headings/IDs, links/assets, common navigation, mobile CSS contracts, dormant GA4');
