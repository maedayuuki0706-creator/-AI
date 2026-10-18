'use strict';
/** Read-only opt-in prediction gate regression test. Run: node viewer/tests/test_prediction_opt_in.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const js=fs.readFileSync(path.join(__dirname,'..','app.js'),'utf8');
const elems = new Map(), network=[], analytics=[], nav=[], storage=new Map();
const elem=id=>{
  if(!elems.has(id)){
    const css=new Set(['race-center','view-pt2','view-race','view-player','view-motor'].includes(id)?['hidden']:[]);
    const listeners={};
    elems.set(id,{
      classList:{contains:c=>css.has(c),add:c=>css.add(c),remove:c=>css.delete(c),toggle:(c,on)=>on?css.add(c):css.delete(c)},
      handlers:listeners,
      value:'',textContent:'',innerHTML:'',href:'',
      setAttribute(key,value){this[key]=value},
      addEventListener(name,cb){listeners[name]=cb},
      scrollIntoView(){},focus(){}
    });
  }
  return elems.get(id);
};
for(const tab of ['pt2','race','motor','player']){
  let cb;
  nav.push({
    getAttribute:name=>name==='data-open-tab'?tab:null,
    addEventListener:(type,f)=>{if(type==='click')cb=f;},
    click:()=>cb()
  });
}
const day=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()).replace(/-/g,'');
const official={day,complete:true,races:{'03:5':{jcd:'03',rno:5,deadline:'15:30'}}};
const forecast=rno=>({
  day,jcd:'03',rno,venue:'江戸川',deadline:'15:30',
  created_at:new Date().toISOString(),digest:'test',
  models:{prototype2:{grade:'B',heads:{'1':.55},strategy_cards:{cards:{balanced:{main_picks:['1-2-3'],cover_picks:[],point_count:1}}}}}
});
const fetcher=async url=>{
  network.push(url);
  let payload=null;
  if(url.includes('/race_cards/'))payload=official;
  else if(url.includes('data/manifest.json'))payload={days:{}};
  else if(url.includes('/prototype12_delivery/predictions/')){
    const match=/_03_(\d\d)\.json/.exec(url);
    payload=forecast(Number(match?.[1]||5));
  }
  if(!payload)return{ok:false,status:404,text:async()=>''};
  return{ok:true,status:200,text:async()=>JSON.stringify(payload)};
};
let schedule;
const window={
  MotorPanel:{start(){},readMeta(){},show(){},render(){},load(){}},
  RaceSchedule:{start:options=>schedule=options,load(){}},
  gtag:(...args)=>analytics.push(args)
};
const localStorage={
  getItem:key=>storage.get(key)||null,
  setItem:(key,value)=>storage.set(key,value),
  removeItem:key=>storage.delete(key),
  key:i=>[...storage.keys()][i],
  get length(){return storage.size;}
};
const context={
  window,document:{getElementById:elem,querySelectorAll:key=>key==='[data-open-tab]'?nav:[]},
  location:{search:'',pathname:'/'},history:{replaceState(){}},
  localStorage,fetch:fetcher,AbortController:class{signal={};abort(){}},
  setTimeout:()=>1,clearTimeout(){},URLSearchParams,Intl,Date,Map,Number,String,JSON,Array,
  console
};
const predictionFetches=()=>network.filter(x=>x.includes('/prototype12_delivery/predictions/')||/data\/races\/.+\.json/.test(x));
const settle=async()=>{for(let i=0;i<70;i++)await Promise.resolve();};
vm.runInNewContext(js,context,{filename:'viewer/app.js'});

(async()=>{
 await settle();
 assert.ok(schedule,'deadline schedule wired');
 assert.equal(elem('race-center').classList.contains('hidden'),true,'details initially hidden');
 assert.equal(predictionFetches().length,0,'no forecast prefetch on home');

 schedule.onPick('03',5,true);
 await settle();
 assert.equal(predictionFetches().length,0,'no forecast prefetch on auto-selection');
 assert.equal(elem('view-pt2').classList.contains('hidden'),true);

 nav[0].click();
 await settle();
 assert.ok(predictionFetches().length>0,'forecast loaded after explicit user gesture');
 assert.equal(elem('view-pt2').classList.contains('hidden'),false);
 assert.ok(elem('view-pt2').innerHTML.includes('1-2-3'));
 assert.equal(analytics.length,1);
 assert.equal(analytics[0][1],'prediction_open');
 assert.equal(analytics[0][2].venue_code,'03');

 const count=predictionFetches().length;
 schedule.onPick('03',6,false);
 await settle();
 assert.equal(predictionFetches().length,count,'changing race does not read forecast data');
 assert.equal(elem('view-pt2').classList.contains('hidden'),true);
 assert.equal(elem('view-race').classList.contains('hidden'),false);

 console.log('PASS: home hidden, race navigation does not prefetch picks, explicit user click opens picks, analytics opt-in event, changing race hides picks');
})().catch(e=>{console.error(e);process.exitCode=1;});
