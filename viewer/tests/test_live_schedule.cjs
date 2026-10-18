'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const els=new Map();
const element=id=>{
 if(!els.has(id))els.set(id,{innerHTML:'',textContent:'',hidden:false,scrollTop:0,addEventListener(){}});
 return els.get(id);
};
const root={};
const context={
 window:root,
 document:{getElementById:element,addEventListener(){},visibilityState:'hidden'},
 fetch:async()=>{throw new Error('offline test')},
 AbortController,Intl,Date,Map,Number,String,JSON,Array,Math,RegExp,Error,
 setInterval(){},setTimeout(){return 1;},clearTimeout(){}
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'..','live_schedule.js'),'utf8'),context);
const api=root.RaceSchedule;
assert.ok(api);
api.start({
 venues:[['01','桐生'],['20','若松']],
 getDay:()=> '2026-10-19',
 autoDate:()=>false,
 isAutoFollowing:()=>false,
 onPick(){throw new Error('should not navigate in this test');},
 onFollow(){},
 onNewDay(){}
});
assert.equal(api.epoch('20261019','08:30'),Date.parse('2026-10-19T08:30:00+09:00'));
assert.ok(Number.isNaN(api.epoch('20261019','99:99')));
assert.ok(Number.isNaN(api.epoch('20261019','8:30')));
const card={day:'20261019',complete:true,checked_at:'2026-10-18T11:00:00+09:00',races:{
 '20:8':{jcd:'20',rno:8,deadline:'18:41'},
 '01:1':{jcd:'01',rno:1,deadline:'15:26'},
 'dup':{jcd:'01',rno:1,deadline:'15:26'},
 'unknown':{jcd:'99',rno:2,deadline:'16:00'},
 'badtime':{jcd:'01',rno:2,deadline:'wrong'}
}};
const items=api.fromCard('20261019',card).items;
assert.equal(items.length,2);
assert.equal(items[0].key,'20261019_01_01');
assert.equal(items[1].key,'20261019_20_08');
assert.equal(api.upcoming(items,items[0].at).length,1,'deadline is closed exactly at cutoff');
assert.throws(()=>api.fromCard('20261020',card),/未確定/);
assert.throws(()=>api.fromCard('20261019',{...card,complete:false}),/未確定/);
const feed=api.fromFeed('20261019',{day:'20261019',races:[{jcd:'20',rno:12,deadline:'20:50'}],partial:true});
assert.equal(feed.items.length,1);
assert.equal(feed.partial,true);
assert.equal(element('deadline-items').innerHTML.includes('若松'),false,'offline load must never invent races');
console.log('PASS: JST cutoff, deduplication, sorted deadlines, missing data, partial feed');
