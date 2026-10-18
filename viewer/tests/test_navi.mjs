import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {fileURLToPath} from 'node:url';
import * as D from '../assets/data.mjs';
import {predictionHtml,racerHtml,motorHtml,scoreMetrics,statsHtml,DISPLAY_AI_TYPES,boot} from '../assets/app.mjs';
import {configured,safeLocation,fromX} from '../assets/analytics.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
const fixture=name=>JSON.parse(fs.readFileSync(root+'data/public/'+name+'.json','utf8'));
const race=D.raceSelection('?date=2026-10-18&venue=19&race=12');
const forecast={day:race.day,jcd:race.jcd,rno:race.rno,created_at:'2026-10-18T20:30:00+09:00',deadline:'20:40',models:{prototype2:{heads:{1:.4,2:.2,3:.1,4:.1,5:.1,6:.1},strategy_cards:{cards:{balanced:{main_picks:['1-2-3','1-2-3','1-1-3','7-2-3'],cover_picks:['1-3-2']}}},database:{lane_factors:{1:{signals:['course=80.0/50.0','motor_grade=0.8']}}}}}};

test('JST dates, exact cutoff, duplicates, cancellation, partial and midnight',()=>{
 assert.equal(D.validDay('2026-02-30'),false);assert.equal(D.validDay('2024-02-29'),true);
 assert.equal(D.raceSelection('?date=2026-02-30&venue=19&race=1'),null);
 assert.equal(D.raceSelection('?date=2026-10-18&venue=25&race=1'),null);
 const p={day:'20261018',complete:true,races:[{jcd:'19',rno:2,deadline:'20:00'},{jcd:'1',rno:1,deadline:'10:00'},{jcd:'19',rno:2,deadline:'20:00'},{jcd:'19',rno:13,deadline:'21:00'},{jcd:'25',rno:1,deadline:'12:00'},{jcd:'04',rno:3,deadline:'25:00'},{jcd:'04',rno:1,deadline:'11:00',cancelled:true}]};
 const s=D.scheduleRows('20261018',p,'saved');
 assert.deepEqual(s.races.map(r=>r.jcd),['01','19']);
 assert.equal(D.upcoming(s.races,D.deadlineEpoch('20261018','10:00')).length,1);
 assert.equal(D.upcoming(s.races,Date.parse('2026-10-19T00:00:00+09:00')).length,0);
 assert.throws(()=>D.scheduleRows('20261019',p,'saved'),/一致/);
 assert.throws(()=>D.scheduleRows('20261018',{...p,complete:false},'saved'),/未確定/);
 assert.equal(D.scheduleRows('20261018',{...p,partial:true},'feed').partial,true);
});
test('CSV: BOM, quotes, CRLF',()=>{
 assert.deepEqual(D.csv('\uFEFF枠,選手名\r\n1,"氏名,テスト"\r\n2,"改""名"\r\n'),[{'枠':'1','選手名':'氏名,テスト'},{'枠':'2','選手名':'改"名'}]);
});
test('card identity and unique lanes',()=>{
 const c={...race,boats:Array.from({length:6},(_,i)=>({lane:i+1,racer_id:String(4200+i),name:'選手'+i}))};
 assert.ok(D.compactCard(c,race));assert.equal(D.compactCard({...c,jcd:'18'},race),null);
 assert.equal(D.compactCard({...c,boats:c.boats.map(b=>({...b,lane:1}))},race),null);
 assert.equal(D.compactCard({...c,boats:c.boats.slice(1)},race),null);
});
test('forecast identity, valid picks, post-close, zero vs missing and escaping',()=>{
 const p=D.compactPrediction(forecast,race);
 assert.deepEqual(p.cards.balanced.main,['1-2-3']);
 assert.throws(()=>D.compactPrediction({...forecast,jcd:'01'},race),/一致/);
 assert.equal(D.compactPrediction({...forecast,created_at:'2026-10-18T20:40:00+09:00'},race).afterClose,true);
 assert.equal(D.pct(0),'0.0%');assert.equal(D.pct(null),'—');
 assert.ok(predictionHtml({...p,source:'原本'}).includes('コース1着率 80.0%'));
 assert.ok(predictionHtml({...p,analysis:'<script>alert(1)</script>'}).includes('&lt;script&gt;'));
});
test('real 1,505 motors: venue pairing, grade mapping, replacement and missing',()=>{
 const {data:motors,snapshot_at}=fixture('motors');
 assert.equal(Object.keys(motors).length,1505);
 for(const [key,entry] of Object.entries(motors)){const [jcd,no]=key.split(':');assert.equal(D.motorEntry(motors,jcd,no),entry);}
 assert.equal(D.motorEntry({'01:12':{motor:12,venue:'戸田'}},'01',12),null);
 assert.equal(D.motorEntry({'01:12':{motor:12,start:'2026/10/19'}},'01',12,'20261018'),null);
 assert.equal(D.motorEntry(motors,'01',999),null);
 assert.deepEqual(['S','A','B','C','D','?'].map(g=>D.grade(g).mark),['◎','○','△','注意','低','—']);
 assert.ok(motorHtml(motors[Object.keys(motors)[0]],'01',{snapshot_at}).includes('記録と、評価の根拠'));
});
test('real 1,660 racers: Japanese and full-width ID search, missing period',()=>{
 const pack=fixture('players'),list=D.playersList(pack.data);
 assert.equal(list.length,1660);
 assert.equal(D.playerMatches(list,'４２３８')[0]?.id,'4238');
 assert.equal(D.playerMatches(list,'毒島　誠')[0]?.id,'4238');
 assert.equal(D.playerMatches(list,'存在しない選手名').length,0);
 const html=racerHtml({...pack.data['4238'],id:'4238'},{snapshot_at:pack.snapshot_at});
 for(const text of ['母数','対象期間','未収録'])assert.ok(html.includes(text));
 assert.ok(racerHtml({name:'<img src=x onerror=1>',id:'0000'},{}).includes('&lt;img'));
});
test('real 8-AI stats: exact ROI, missing is not zero, public allowlist',()=>{
 const stats=D.publicStats(fixture('stats'));assert.equal(Object.keys(stats.streams).length,8);
 for(const row of Object.values(stats.streams)){
  const m=scoreMetrics(row);
  if(m.roi!==null)assert.ok(Math.abs(m.roi-row.roi)<0.001);
  if(m.hitRate!==null)assert.ok(Math.abs(m.hitRate-row.hit_rate)<0.001);
 }
 const empty=scoreMetrics({judged:0,hits:0,stake_yen:0,return_yen:0});assert.equal(empty.hitRate,null);assert.equal(empty.roi,null);
 assert.throws(()=>D.publicStats({...stats,unit_yen:1000}),/集計条件/);
 assert.ok(statsHtml(stats).includes('未確定は除外'));
 assert.ok(statsHtml(stats,'未登録場').includes('公開集計はありません'));
 assert.ok(!statsHtml(stats).includes('hit_races'));
 const raw={day:'20261018',unit_yen:100,streams:{test:{label:'test',judged:1,hits:1,stake_yen:100,return_yen:200,internal_secret:'NO_OUTPUT'}},venues:{}};
 assert.ok(!JSON.stringify(D.publicStats(raw)).includes('NO_OUTPUT'));
});
test('all eight public AI names are fixed TYPE A-H aliases (not ROI ranking)',()=>{
 const expected={
  hiyori:'TYPE A',prototype3:'TYPE B',main:'TYPE C',prototype2:'TYPE D',
  mid_odds:'TYPE E',prototype1:'TYPE F',selected:'TYPE G',longshot:'TYPE H'
 };
 assert.deepEqual(DISPLAY_AI_TYPES,expected);
 const stats=D.publicStats(fixture('stats'));
 const national=statsHtml(stats);
 const venue=statsHtml(stats,'児島');
 for(const [id,alias] of Object.entries(expected)){
   assert.ok(national.includes('<td>'+alias),'missing national alias for '+id);
   assert.ok(national.includes('<h3>'+alias+'</h3>')||Object.keys(expected).length>4,
     'missing card alias for '+id);
   assert.ok(venue.includes('<td>'+alias),'missing venue alias for '+id);
 }
 for(const old of ['日和','PT3 / ゆうき','メインくん','PT2','中穴くん','PT1','厳選くん','穴くん']){
   assert.ok(!national.includes(old),'old national display name leaked: '+old);
   assert.ok(!venue.includes(old),'old venue display name leaked: '+old);
 }
 assert.ok(national.includes('成績順位や強さの格付けではありません'));
 // Changing results must NOT relabel a stream merely because its ranking changed.
 const swapped=D.publicStats({day:'20261018',unit_yen:100,
  streams:{
   hiyori:{judged:111,hits:22,stake_yen:10000,return_yen:4000},
   main:{judged:222,hits:133,stake_yen:10000,return_yen:19000}
  },venues:{}});
 const html=statsHtml(swapped);
 assert.ok(html.indexOf('TYPE C')<html.indexOf('TYPE A'),
   'row ordering is ROI, but TYPE aliases must stay attached to stable IDs');
 assert.ok(html.includes('<td>TYPE A</td><td class="number">111</td>'));
 assert.ok(html.includes('<td>TYPE C</td><td class="number">222</td>'));
 const preview=D.compactPrediction(forecast,race);
 assert.ok(predictionHtml({...preview,source:'原本'}).includes('TYPE D'));
 assert.ok(!predictionHtml({...preview,source:'原本'}).includes('PT2'));
});

test('GA4 config, sanitized page URL, X acquisition',()=>{
 assert.equal(configured({preview:false,analytics:{enabled:false,measurementId:'G-123456'}}),false);
 assert.equal(configured({preview:true,analytics:{enabled:true,measurementId:'G-123456'}}),false);
 assert.equal(configured({preview:false,analytics:{enabled:true,measurementId:'G-123456'}}),true);
 const url=new URL('https://example.com/racers/?q=private-name&utm_source=x&utm_medium=social&utm_campaign=free_prediction&secret=abc');
 const clean=safeLocation(url);assert.ok(!clean.includes('private-name'));assert.ok(!clean.includes('secret'));assert.ok(clean.includes('utm_source=x'));
 assert.equal(fromX(url,''),true);assert.equal(fromX(new URL('https://example.com/'),'https://t.co/abc'),true);assert.equal(fromX(new URL('https://example.com/'),'https://not-x.com/'),false);
});

// Runs shipped event handlers, without a rendering browser or layout claims.
class Element{
 constructor(id=''){Object.assign(this,{id,value:'',disabled:false,hidden:false,dataset:{},listeners:{},textContent:'',_html:'',options:[]});}
 set innerHTML(v){this._html=v;this.options=[...String(v).matchAll(/<option[^>]*>([^<]*)<\/option>/g)].map(m=>({textContent:m[1]}));}
 get innerHTML(){return this._html;}
 addEventListener(k,fn){(this.listeners[k]||=[]).push(fn);}
 async emit(k,props={}){for(const fn of [...(this.listeners[k]||[])])await fn({preventDefault(){},target:this,...props});}
 querySelectorAll(){return [];}setAttribute(k,v){this[k]=v;}getAttribute(k){return this[k]??null;}contains(){return false;}focus(){}
}
function environment(page,search=''){
 const old=new Map(['document','window','location','history','NAVI_CONFIG','NAVI_TEST_MODE','fetch','setInterval','clearInterval','localStorage'].map(k=>[k,globalThis[k]]));
 const elements=new Map(),calls=[],scripts=[],store=new Map();
 const get=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);};
 const location={origin:'https://example.com',pathname:page==='home'?'/':'/'+page+'/',search,hostname:'example.com',reload(){},replace(){}};
 Object.defineProperty(location,'href',{get(){return this.origin+this.pathname+this.search;}});
 const doc={body:{dataset:{page}},title:'競艇AIナビ',referrer:'',cookie:'',visibilityState:'visible',getElementById:get,querySelectorAll:()=>[],addEventListener(){},createElement:()=>new Element(),head:{appendChild(el){scripts.push(el);}}};
 Object.assign(globalThis,{document:doc,window:{location,addEventListener(){}},location,history:{replaceState(a,b,path){location.search=path.includes('?')?'?'+path.split('?')[1]:'';}},NAVI_CONFIG:{preview:true,analytics:{enabled:false,measurementId:''}},NAVI_TEST_MODE:true,setInterval:()=>1,clearInterval(){},localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)}});
 const reply=(body,status=200)=>({ok:status===200,status,json:async()=>body,text:async()=>typeof body==='string'?body:JSON.stringify(body)});
 globalThis.fetch=async url=>{
  calls.push(String(url));
  if(String(url).includes('/predictions/'))return reply(forecast);
  if(String(url).includes('/data/races/'))return reply({prediction:forecast});
  if(String(url).includes('meta.json'))return reply(fixture('meta'));
  if(String(url).includes('/race_cards/'))return reply({day:D.dayKey(D.jstDate()),complete:true,races:[]});
  if(String(url).includes('/live_status/')||String(url).includes('/public/stats.json'))return reply(fixture('stats'));
  return reply({},404);
 };
 return{get,calls,scripts,store,doc,reply,restore(){for(const [k,v]of old)if(v===undefined)delete globalThis[k];else globalThis[k]=v;}};
}
test('shipped UI: no prediction fetch on any page; explicit click only; change erases picks',async()=>{
 for(const page of ['home','races','motors','racers','lab','predictions']){
  const env=environment(page,page==='predictions'?'?date=2026-10-18&venue=19&race=12':'');
  try{
   boot();await new Promise(r=>setTimeout(r,25));
   assert.ok(!env.calls.some(u=>/\/(?:predictions|races)\/.*\.json/.test(u)),'no forecast prefetch on '+page);
   if(page==='predictions'){
    assert.equal(env.get('prediction-open').disabled,false);assert.equal(env.get('prediction-content').innerHTML,'');
    await env.get('prediction-open').emit('click');
    assert.equal(env.calls.filter(u=>u.includes('/predictions/')).length,1);
    assert.ok(env.get('prediction-content').innerHTML.includes('1-2-3'));
    env.get('race-number').value='11';await env.get('race-form').emit('change');
    assert.equal(env.get('prediction-content').innerHTML,'');assert.equal(env.get('prediction-open').disabled,true);
    await env.get('prediction-open').emit('click');assert.equal(env.calls.filter(u=>u.includes('/predictions/')).length,1);
   }
   assert.equal(env.scripts.length,0);
  }finally{env.restore();}
 }
});
test('shipped UI: wrong race is rejected; 404 and network error stay distinct',async()=>{
 for(const mode of ['wrong','404','network']){
  const env=environment('predictions','?date=2026-10-18&venue=19&race=12');
  try{
   globalThis.fetch=async url=>{env.calls.push(String(url));if(mode==='wrong')return env.reply({...forecast,jcd:'18'});if(mode==='404')return env.reply({},404);throw new TypeError('fetch failed');};
   boot();await env.get('prediction-open').emit('click');
   const html=env.get('prediction-content').innerHTML;
   assert.ok(!html.includes('1-2-3'));assert.ok(mode==='404'?html.includes('未公開'):html.includes('確認できませんでした'));
  }finally{env.restore();}
 }
});
test('shipped UI: slower old response cannot overwrite a changed race',async()=>{
 const env=environment('predictions','?date=2026-10-18&venue=19&race=12');let resolve;
 try{
  globalThis.fetch=()=>new Promise(done=>{resolve=()=>done(env.reply(forecast));});
  boot();const pending=env.get('prediction-open').emit('click');
  env.get('race-number').value='11';await env.get('race-form').emit('change');resolve();await pending;
  assert.equal(env.get('prediction-content').innerHTML,'');assert.equal(env.get('prediction-open').disabled,true);
 }finally{env.restore();}
});
test('basic consent: no tag before consent, one page_view after consent, no raw queries',async()=>{
 const env=environment('privacy');
 try{
  globalThis.NAVI_CONFIG={preview:false,analytics:{enabled:true,measurementId:'G-TEST1234'}};
  const A=await import('../assets/analytics.mjs?consent-test=1');A.initAnalytics();
  assert.equal(env.scripts.length,0);assert.equal(A.track('prediction_open',{query:'SECRET'}),false);
  await env.get('consent-accept').emit('click');assert.equal(env.scripts.length,1);
  const events=window.dataLayer.map(args=>[...args]);
  assert.equal(events.filter(e=>e[0]==='event'&&e[1]==='page_view').length,1);
  assert.equal(events.find(e=>e[0]==='consent'&&e[1]==='update')[2].ad_storage,'denied');
  A.track('racer_search',{query:'SECRET',query_length:4,result_count:1});assert.ok(!JSON.stringify(window.dataLayer).includes('SECRET'));
 }finally{env.restore();}
});

const cardFixture=(selected,name)=>({...selected,captured_at:'2026-10-18T10:00:00+09:00',deadline:'15:00',boats:Array.from({length:6},(_,i)=>({lane:i+1,racer_id:String(4200+i),name:name+(i+1),current_class:'A1',win_rate:6,avg_st:.15,motor_number:11+i,motor_top2_rate:30}))});
const liveCsv=name=>({
 race:'枠,登録番号,級別,全国勝率,平均ST,締切\n'+Array.from({length:6},(_,i)=>[i+1,4200+i,'A1',6,.15,'15:00'].join(',')).join('\n'),
 roster:'登録番号,選手名,級別,モーターNo.,モーター2連率\n'+Array.from({length:6},(_,i)=>[4200+i,name+(i+1),'A1',51+i,45].join(',')).join('\n')
});
const settled=()=>new Promise(resolve=>setTimeout(resolve,15));
test('shipped UI: refresh replaces a cached card and later reads keep the new data',async()=>{
 const env=environment('race','?date=2026-10-17&venue=01&race=1'),selected=D.raceSelection(location.search),live=liveCsv('更新後');
 try{
  globalThis.fetch=async url=>{
   env.calls.push(String(url));
   if(String(url).includes('/data/cards/'))return env.reply(cardFixture(selected,'更新前'));
   if(String(url).includes('/race_roster.csv'))return env.reply(live.roster);
   if(String(url).includes('/race.csv'))return env.reply(live.race);
   return env.reply({},404);
  };
  boot();await settled();assert.ok(env.get('race-content').innerHTML.includes('更新前1'));
  await env.get('race-refresh').emit('click');await settled();
  assert.ok(env.get('race-content').innerHTML.includes('更新後1'),'refresh must show new feed, not old cache');
  assert.ok(!env.get('race-content').innerHTML.includes('更新前1'));
  const later=await D.loadCard(selected);
  assert.equal(later.boats[0].name,'更新後1','subsequent reads must keep the updated card');
 }finally{env.restore();}
});
test('shipped UI: old race refresh completing late cannot reopen the old race',async()=>{
 const env=environment('race','?date=2026-10-17&venue=02&race=1'),first=D.raceSelection(location.search),next={...first,rno:2,key:'20261017_02_02'},live=liveCsv('旧レース更新'),complete=[];
 try{
  globalThis.fetch=async url=>{
   if(String(url).includes('/data/cards/'+first.key))return env.reply(cardFixture(first,'旧レース'));
   if(String(url).includes('/data/cards/'+next.key))return env.reply(cardFixture(next,'選択中レース'));
   if(String(url).includes('/race_roster.csv'))return new Promise(resolve=>complete.push(()=>resolve(env.reply(live.roster))));
   if(String(url).includes('/race.csv'))return new Promise(resolve=>complete.push(()=>resolve(env.reply(live.race))));
   return env.reply({},404);
  };
  boot();await settled();
  const refreshing=env.get('race-refresh').emit('click');await settled();
  assert.equal(complete.length,2);
  env.get('race-number').value='2';await env.get('race-form').emit('change');await env.get('race-form').emit('submit');await settled();
  assert.ok(env.get('race-content').innerHTML.includes('選択中レース1'));
  complete.forEach(done=>done());await refreshing;await settled();
  assert.ok(env.get('race-content').innerHTML.includes('選択中レース1'),'late refresh must preserve current race');
  assert.ok(!env.get('race-content').innerHTML.includes('旧レース'));
  assert.equal(new URLSearchParams(location.search).get('race'),'2');
 }finally{env.restore();}
});
test('shipped UI: unconfirmed selector changes remove the old race from the shared URL',async()=>{
 const env=environment('predictions','?date=2026-10-18&venue=19&race=12&utm_source=x');
 try{
  boot();env.get('race-number').value='11';await env.get('race-form').emit('change');
  assert.equal(D.raceSelection(location.search),null,'URL must not retain the previous race');
  assert.equal(new URLSearchParams(location.search).get('utm_source'),'x','preserve unrelated acquisition tags');
  assert.equal(env.get('prediction-open').disabled,true);
 }finally{env.restore();}
});
test('private preview can read its protected JSON while external sources remain cross-origin',async()=>{
 const env=environment('home');
 try{
  globalThis.fetch=async(url,options)=>{
   const local=new URL(url,location.origin).origin===location.origin;
   if(local&&options.credentials!=='same-origin')return env.reply({},401);
   return env.reply({ok:true});
  };
  assert.deepEqual(await D.request('/data/public/meta.json'),{ok:true},'same-site JSON must keep the signed-in session');
  assert.deepEqual(await D.request(D.DATA_ROOT+'sheet_db/meta.json'),{ok:true});
 }finally{env.restore();}
});
