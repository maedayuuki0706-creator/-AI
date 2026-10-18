'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

const elements=new Map();
function getEl(id){
  if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:''});
  return elements.get(id);
}
const meta={
 source:'Google Sheets 競艇AI データベース',snapshot_at:'2026-10-18T22:12:03+09:00',motor_count:3
};
const motors={
 '01:11':{venue:'桐生',motor:11,start:'2025/12/27',as_of:'2026/10/17',grade:'B',stretch:'B',launch:'A',turn:'S',run:'C',top2:31.7},
 '01:12':{venue:'桐生',motor:12,start:'2025/12/27',as_of:'2026/10/18',grade:'S',stretch:'S',launch:'A',turn:'B',run:'S',top2:50},
 '02:12':{venue:'戸田',motor:12,start:'2025/12/27',as_of:'2026/10/18',grade:'D',stretch:'D',launch:'D',turn:'D',run:'D',top2:22}
};
const calls=[];
const sandbox={
 window:{},
 document:{getElementById:getEl},
 fetch:async url=>{
   calls.push(url);
   return {ok:true,json:async()=>url.includes('meta.json')?meta:motors};
 },
 AbortController:class{signal={};abort(){}},
 setTimeout(){return 1;},clearTimeout(){},
 Intl,Date
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'..','motor_panel.js'),'utf8'),sandbox);
const model=sandbox.window.MotorPanel;
assert.equal(model.gradeMark('S').mark,'◎');
assert.equal(model.gradeMark('A').mark,'○');
assert.equal(model.gradeMark('B').mark,'△');
assert.equal(model.gradeMark('C').mark,'注意');
assert.equal(model.gradeMark('D').mark,'低');
assert.equal(model.gradeMark('other').mark,'—');
assert.equal(model.motorKey('01','012'),'01:12');
assert.equal(model.pick(motors,'01',12).grade,'S');
assert.equal(model.pick(motors,'02',12).grade,'D');
assert.equal(model.pick(motors,'03',12),null);
const race={
 day:'20261017',venue:'01',venueName:'桐生',race:1,
 rows:[{'枠':'1','登録番号':'4238'},{'枠':'2','登録番号':'4320'}],
 roster:[{'登録番号':'4238','選手名':'確認用A','モーターNo.':'11'},
         {'登録番号':'4320','選手名':'確認用B','モーターNo.':'12'}]
};
model.start({race:()=>race,roster:async()=>{}});
(async()=>{
 await model.show();
 let html=getEl('view-motor').innerHTML;
 assert.ok(html.includes('伸び')&&html.includes('出足')&&html.includes('回り足')&&html.includes('行き足'));
 assert.ok(html.includes('確認用A')&&html.includes('No.12'));
 assert.ok(html.includes('motor-mark--best'));
 assert.ok(html.includes('選択レースの日付より後に更新された評価'));
 assert.ok(html.includes('未評価')||html.includes('未取得'));
 assert.equal(getEl('home-motor-count').textContent,'3機');
 assert.equal(calls.length,2,'meta and motors fetched only on demand');
 race.day='20261019';model.render();
 html=getEl('view-motor').innerHTML;
 assert.ok(!html.includes('選択レースの日付より後に更新された評価'));
 race.day='20251201';model.render();
 assert.ok(getEl('view-motor').innerHTML.includes('モーター交換日が対象レースより後'));
 console.log('PASS motor grades, venue pairing, missing values, historical warning, race change, lazy fetch');
})().catch(e=>{console.error(e);process.exitCode=1;});
