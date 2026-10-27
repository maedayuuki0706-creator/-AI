import fs from 'node:fs';

import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);const {chromium:pw}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const browser=await pw.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE,args:['--no-sandbox','--disable-dev-shm-usage']}: {})});
const page=await browser.newPage({viewport:{width:390,height:844},deviceScaleFactor:1,isMobile:true,hasTouch:true});if(process.env.QA_FONT_CSS)await page.addInitScript(css=>document.addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');s.textContent=css;document.head.append(s);} ),fs.readFileSync(process.env.QA_FONT_CSS,'utf8'));let errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto('http://127.0.0.1:8787');await page.getByText('205,269',{exact:true}).waitFor();await page.evaluate(()=>document.fonts.ready);await page.screenshot({path:'/tmp/boat-lab-home-mobile.png',fullPage:true});
for(const route of ['races','players','motors','water','manshu','ai','data']){
 await page.goto('http://127.0.0.1:8787/#'+route);await page.waitForTimeout(400);
 if(route==='players'){await page.locator('input[name=q]').fill('毒島');await page.getByRole('button',{name:'検索する'}).click();await page.getByRole('button',{name:'成績を見る'}).first().click();await page.getByText('枠番別',{exact:true}).waitFor();await page.screenshot({path:'/tmp/boat-lab-player-mobile.png',fullPage:true});await page.getByRole('button',{name:'閉じる'}).click();}
 if(route==='races'){await page.getByRole('button',{name:'6艇・気象を見る'}).first().click();await page.locator('#detail table').waitFor();await page.getByRole('button',{name:'閉じる'}).click();await page.getByRole('button',{name:'次の30件'}).click();await page.waitForFunction(()=>document.querySelectorAll('.race').length===60);}
 const layout=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,cards:document.querySelectorAll('.race').length}));console.log(route,JSON.stringify(layout));if(layout.scroll>layout.width)throw Error('overflow '+route);
}
await page.setViewportSize({width:375,height:812});await page.goto('http://127.0.0.1:8787/#home');await page.waitForTimeout(300);console.log('375',await page.evaluate(()=>document.documentElement.scrollWidth));
await page.setViewportSize({width:1440,height:1000});await page.screenshot({path:'/tmp/boat-lab-home-desktop.png',fullPage:true});console.log('errors',errors);if(errors.length)throw Error(errors.join());await browser.close();
