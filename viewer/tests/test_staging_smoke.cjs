'use strict';
// Smoke-test the *independent* free schedule service and staging site.
// Never calls production prediction/Discord/X endpoints or modifies remote state.
const assert=require('node:assert/strict');
const API=process.env.SCHEDULE_URL||'https://boat-ai-navi-schedule.onrender.com';
const SITE=process.env.PREVIEW_URL||'https://boat-ai-navi-preview-20261019.onrender.com';
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function get(url,retries=8){
 let last;
 for(let i=0;i<retries;i++){
  try{
   const res=await fetch(url,{signal:AbortSignal.timeout(27000),cache:'no-store'});
   const body=await res.text();
   if(res.status===200||res.status===503)return {res,body};
   throw new Error('HTTP '+res.status+' '+body.slice(0,90));
  }catch(e){last=e;if(i<retries-1)await wait(4500);}
 }
 throw last;
}
async function main(){
 const [health,site]=await Promise.all([get(API+'/health'),get(SITE+'/')]);
 assert.equal(health.res.status,200,'independent schedule must be running');
 const hello=JSON.parse(health.body);
 assert.equal(hello.service,'boat-ai-navi-schedule');
 assert.equal(hello.mode,'readonly');
 assert.equal(health.res.headers.get('access-control-allow-origin'),'*');
 assert.equal(site.res.status,200);
 assert.ok(site.body.includes('class="home-landing"'),'homepage missing');
 assert.ok(site.body.includes('data-open-tab="pt2"'),'manual prediction button missing');
 assert.ok(site.body.includes('class="workspace hidden"'),'predictions must be initially hidden');
 assert.ok(site.body.includes('id="view-motor"'),'motor ratings panel missing');
 assert.ok(!site.body.includes('docs.google.com/spreadsheets/d/'),'private spreadsheet link leaked');
 const js=await get(SITE+'/live_schedule.js');
 assert.equal(js.res.status,200);
 assert.ok(js.body.includes('boat-ai-navi-schedule.onrender.com'),'schedule endpoint wiring');
 const day=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()).replace(/-/g,'');
 const schedule=await get(API+'/schedule.json?date='+day,3);
 if(schedule.res.status===503){
  console.warn('WARN: official schedule upstream temporarily unavailable; site must show missing-data message');
  console.log('PASS isolated API health, CORS, published homepage and opt-in behavior; official feed pending');
  return;
 }
 assert.equal(schedule.res.status,200);
 const data=JSON.parse(schedule.body);
 assert.equal(data.day,day);
 assert.ok(Array.isArray(data.races));
 let last='';
 for(const race of data.races){
  assert.match(race.deadline,/^([01]\d|2[0-3]):[0-5]\d$/);
  assert.match(race.jcd,/^\d\d$/);
  assert.ok(Number.isInteger(race.rno)&&race.rno>=1&&race.rno<=12);
  assert.ok(race.deadline>=last,'deadlines not sorted');
  last=race.deadline;
 }
 console.log('PASS live staging homepage, motor panel, manual predictions, no raw sheet link, independent schedule API');
 console.log('Official schedule: '+data.venues+' venues, '+data.races.length+' races, partial='+data.partial);
}
main().catch(e=>{console.error(e);process.exitCode=1;});
