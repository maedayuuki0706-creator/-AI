import {filterEnvironment,summarizePlayer,entrySimulation,VENUES,NAMES,mergeHistory,filterHistory,summarizeHistory,rankPlayers,dayLabel,yen,rate,finite} from './analysis-core.mjs';
const $=id=>document.getElementById(id);
const e=(tag,cls='',text='')=>{const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=String(text);return node;};
const text=(id,value)=>{$(id).textContent=value;};
const asDate=key=>key ? key.slice(0,4)+'-'+key.slice(4,6)+'-'+key.slice(6,8) : '';
const safePct=value=>finite(value)===null?'—':rate(finite(value));
async function json(path) {
 const ctrl=new AbortController();const timer=setTimeout(()=>ctrl.abort(),18000);
 try {const res=await fetch(path,{signal:ctrl.signal,cache:'no-cache',credentials:'same-origin'});
 if(!res.ok)throw new Error('HTTP '+res.status);return await res.json();}
 finally {clearTimeout(timer);}
}
for(const [code,name] of VENUES){const option=e('option','',name);option.value=code;$('h-venue').append(option);}
let manifestPromise, researchPromise, detailToken=0, selectedPlayer=null;
const historyCache=new Map(), playerCache=new Map();
const state={history:null,filtered:[],hLimit:100,playerPayload:null,players:[],pLimit:50,historyError:'',playerError:''};
function stat(label,value,sub=''){
 const div=e('div','metric'),b=e('b','',value);div.append(e('span','',label),b,e('small','',sub));return div;
}
function cell(tr,value,cls=''){const td=e('td',cls,value);tr.append(td);return td;}
function showHistory(){
 if(!state.history)return;
 const from=$('h-from').value,to=$('h-to').value;if(from&&to&&from>to){text('history-status','開始日が終了日より後です。期間を修正してください。');return;}
 const options={from,to,venue:$('h-venue').value,first:$('h-first').value,minPayout:$('h-min').value,manshu:$('h-manshu').checked};
 state.filtered=filterEnvironment(filterHistory(state.history.rows,options),{windMin:$('h-wind-min').value,windMax:$('h-wind-max').value,direction:$('h-direction').value,entry:$('h-entry').value});state.hLimit=100;
 const stats=summarizeHistory(state.filtered);
 $('history-metrics').replaceChildren(
  stat('該当結果',stats.count.toLocaleString('ja-JP')+'R','保存済み確定結果'),
  stat('万舟',stats.manshu.toLocaleString('ja-JP')+'R','3連単10,000円以上'),
  stat('万舟率',rate(stats.rate),'検索条件内での割合'),
  stat('最高払戻',stats.highest?yen(stats.highest[4]):'—','100円あたり'));
 const chart=$('history-chart');chart.replaceChildren();
 for(let i=0;i<6;i++){
  const n=stats.heads[i],share=stats.count?n/stats.count*100:0,bar=e('div','bar-track'),fill=e('span','bar-fill');
  fill.style.width=Math.min(100,Math.max(0,share))+'%';bar.append(fill);
  const row=e('div','bar-row');row.append(e('span','lane lane-'+(i+1),String(i+1)),bar,e('span','bar-number',n+'件 / '+rate(stats.count?share:null)));chart.append(row);
 }
 text('history-status',stats.count+'Rヒット。'+(state.historyError?'一部の期間は取得できていません。':'収録済みの公式結果から検索しています。'));
 drawHistoryRows();
}
function drawHistoryRows(){
 const tbody=$('history-rows');tbody.replaceChildren();
 for(const row of state.filtered.slice(0,state.hLimit)){
  const tr=e('tr');cell(tr,dayLabel(row[0]));cell(tr,(NAMES.get(row[1])||row[1])+' '+row[2]+'R');
  const td=cell(tr,'','combination');for(const lane of row[3].split('-'))td.append(e('span','lane lane-'+lane,lane));
  cell(tr,yen(row[4]),row[4]>=10000?'high-prize':'');
  const link=e('a','','公式結果');link.href='https://www.boatrace.jp/owpc/pc/race/raceresult?hd='+row[0]+'&jcd='+row[1]+'&rno='+row[2];link.target='_blank';link.rel='noopener noreferrer';
  cell(tr,'').append(link);tbody.append(tr);
 }
 if(!state.filtered.length) {const tr=e('tr');const td=e('td','empty','この条件に該当する保存済みレースはありません。');td.colSpan=5;tr.append(td);tbody.append(tr);}
 const more=$('history-more');more.hidden=state.hLimit>=state.filtered.length;
 text('history-page-label',Math.min(state.hLimit,state.filtered.length)+' / '+state.filtered.length+'件を表示');
}
function historyManifest(){
 if(!manifestPromise)manifestPromise=json('/data/history/manifest.json').then(m=>{
  if(!Array.isArray(m.shards)||!m.shards.length||m.shards.length>1000||!m.shards.every(s=>/^[0-9a-z-]{7,40}$/.test(s)))throw new Error('履歴目録の形式不正');
  return m;
 }).catch(error=>{manifestPromise=null;throw error;});return manifestPromise;
}
function daysBefore(day,n){const d=new Date(asDate(day)+'T00:00:00Z');d.setUTCDate(d.getUTCDate()-n+1);return d.toISOString().slice(0,10).replaceAll('-','');}
let historyRequest=0;
async function loadHistory(initial=false){
 const request=++historyRequest;
 text('history-status','公式結果を読み込み中…');
 try{
  const manifest=await historyManifest();
  if(request!==historyRequest)return;
  if(initial){$('h-from').value=asDate(daysBefore(manifest.to,30));$('h-to').value=asDate(manifest.to);}
  const from=$('h-from').value.replaceAll('-',''),to=$('h-to').value.replaceAll('-','');
  if(from&&to&&from>to)throw new Error('開始日が終了日より後です。');
  const lo=finite($('h-wind-min').value),hi=finite($('h-wind-max').value);
  if(lo!==null&&hi!==null&&lo>hi)throw new Error('風速下限が上限より大きいです。');
  const names=manifest.shard_info?manifest.shard_info.filter(s=>(!from||s.to>=from)&&(!to||s.from<=to)).map(s=>s.name):manifest.shards;
  // At most four concurrent reads, and only the requested calendar chunks.
  const ok=[],failures=[];let cursor=0;
  await Promise.all(Array.from({length:Math.min(4,names.length)},async()=>{
   while(cursor<names.length){const name=names[cursor++];try{
    let part=historyCache.get(name);if(!part){part=await json('/data/history/'+name+'.json');mergeHistory([part]);historyCache.set(name,part);}ok.push(part);
   }catch{failures.push(name);}}
  }));
  if(request!==historyRequest)return;
  if(names.length&&!ok.length)throw new Error('対象期間の結果を取得できませんでした。再検索で再試行できます。');
  state.history=mergeHistory(ok);state.historyError=failures.join(',');
  const h=state.history;
  const missing=h.rows.filter(r=>r[5]?.wind==null).length;
  text('history-meta',`収録期間 ${dayLabel(manifest.from)}〜${dayLabel(manifest.to)} ／ 全収録 ${manifest.counts.indexed.toLocaleString('ja-JP')}R。今回読込 ${h.rows.length}R、風速欠測 ${missing}R。元記録の除外 ${manifest.counts.skip}件、重複統合 ${manifest.counts.duplicates??0}件。全開催の網羅ではありません。${failures.length?' 部分欠測 '+failures.length+'ファイル。再検索で再試行できます。':''}`);
  showHistory();
 }catch(err){if(request!==historyRequest)return;state.history=null;state.filtered=[];
  $('history-metrics').replaceChildren();$('history-chart').replaceChildren();drawHistoryRows();
  text('history-status','取得・検索エラー：'+err.message);text('history-meta','表示条件を確認できないため集計を表示しません。再検索で再試行できます。');
 }
}
function researchManifest(){
 if(!researchPromise)researchPromise=json('/data/research/manifest.json').catch(e=>{researchPromise=null;throw e;});
 return researchPromise;
}
async function playerHistory(id){
 const manifest=await researchManifest(),name=manifest.players?.[id.slice(0,2)];
 if(!name)return [];
 if(!/^[0-9]{2}-[0-9a-f]{12}\.json$/.test(name))throw new Error('選手履歴の形式不正');
 if(!playerCache.has(name))playerCache.set(name,json('/data/research/players/'+name).catch(e=>{playerCache.delete(name);throw e;}));
 const payload=await playerCache.get(name);return payload.data?.[id]??[];
}
function showPlayers(){
 if(!state.playerPayload)return;
 const opts={query:$('p-query').value,course:+$('p-course').value,level:$('p-class').value,branch:$('p-branch').value,sort:$('p-sort').value,minimum:$('p-min').value};
 try{state.players=rankPlayers(state.playerPayload,opts);state.pLimit=50;drawPlayerRows();
 text('player-status',state.players.length+'名が条件に一致。集計母数未提供のため順位は参考です。');
 }catch(err){text('player-status','検索できませんでした：'+err.message);}
}
function drawPlayerRows(){
 const tbody=$('player-rows');tbody.replaceChildren();
 for(const p of state.players.slice(0,state.pLimit)){
  const tr=e('tr');const racer=cell(tr,'');racer.append(e('b','',p.name),e('small','',p.id+' / '+(p.branch||'—')));
  cell(tr,p.class||'—');cell(tr,finite(p.win)===null?'—':Number(p.win).toFixed(2));
  cell(tr,safePct(p.courseValue),'course-value');cell(tr,finite(p.avg_st)===null?'—':Number(p.avg_st).toFixed(2));
  const btn=e('button','detail-button','詳細');btn.type='button';btn.addEventListener('click',()=>showDetail(p));cell(tr,'').append(btn);tbody.append(tr);
 }
 if(!state.players.length){const tr=e('tr');const td=e('td','empty','該当する選手がいません。');td.colSpan=6;tr.append(td);tbody.append(tr);}
 $('player-more').hidden=state.pLimit>=state.players.length;
}
async function showDetail(p){
 const token=++detailToken;selectedPlayer=p;
 const box=$('player-detail');box.replaceChildren();
 box.append(e('p','eyebrow','RACER PROFILE'),e('h3','',p.name+'（'+p.id+'）'),
  e('p','profile-meta',(p.class||'級別未取得')+' / '+(p.branch||'支部未取得')+' / 全国勝率 '+(finite(p.win)===null?'—':Number(p.win).toFixed(2))+' / 平均ST '+(finite(p.avg_st)===null?'—':Number(p.avg_st).toFixed(2))));
 box.append(e('h4','','コース別1着率'));
 const grid=e('div','profile-grid');
 for(let i=0;i<6;i++){const v=Array.isArray(p.course_win)?p.course_win[i]:null;grid.append(stat((i+1)+'コース',safePct(v)));}box.append(grid);
 box.append(e('h4','','決まり手率（収録DBの参考値）'));
 const grid2=e('div','profile-grid');
 for(const [key,label] of [['escape','逃げ'],['sashi','差し'],['makuri','まくり'],['makurisashi','まくり差し']])grid2.append(stat(label,safePct(p[key])));
 box.append(grid2,e('p','note','上記は保存済み選手DBの参考値。以下の母数付き履歴とは集計対象が異なります。'));
 const extra=e('div','','母数付き履歴を読み込み中…');box.append(extra);
 box.hidden=false;box.focus({preventScroll:true});box.scrollIntoView({behavior:'smooth',block:'nearest'});
 try{
  const [manifest,records]=await Promise.all([researchManifest(),playerHistory(p.id)]);if(token!==detailToken)return;
  const venue=$('p-venue').value,window=$('p-window').value,from=window==='all'?'':daysBefore(manifest.to,+window);
  const opts={venue,from,to:manifest.to},sum=summarizePlayer(records,opts);
  extra.replaceChildren(e('h4','','収録履歴から集計（事後研究）'),e('p','note',`${dayLabel(from||manifest.from)}〜${dayLabel(manifest.to)} / ${NAMES.get(venue)||'全場（収録分）'}。最新開催の現在値ではありません。`));
  const metrics=e('div','profile-grid');metrics.append(stat('収録出走数',sum.n+'走'),stat('1着率',rate(sum.firstRate)),stat('2連対率',rate(sum.top2Rate)),stat('3連対率',rate(sum.top3Rate)),stat('実ST平均',sum.st===null?'—':sum.st.toFixed(2),sum.stN+'走'),stat('着順数値なし',sum.unclassified+'走'));
  extra.append(metrics,e('p','note','1〜3着率の分母には着順数値なしの収録出走も含みます。実STの欠測はST平均からのみ除外。当地の公式勝率とは別の集計です。'));
  if(sum.local&&venue)extra.append(e('p','note',`保存番組表の当地勝率 ${sum.local[7].toFixed(2)}（${dayLabel(sum.local[0])} ${NAMES.get(sum.local[1])} ${sum.local[2]}R時点／公式の集計期間・母数は未収録）`));
  else extra.append(e('p','note',venue?'保存番組表の当地勝率：未取得':'当地勝率は場を指定すると表示します。'));
  const courses=e('div','profile-grid');for(let i=1;i<=6;i++){const a=summarizePlayer(records,{...opts,course:i});courses.append(stat(i+'コース',rate(a.firstRate),a.n+'走 / 1着 '+a.first+'回'));}extra.append(courses);
  const recent=records.filter(r=>(!venue||r[1]===venue)&&(!from||r[0]>=from)).slice(0,10);
  const list=e('ul');for(const r of recent)list.append(e('li','note',`${dayLabel(r[0])} ${NAMES.get(r[1])} ${r[2]}R / ${r[3]??'—'}コース / ${r[4]??'数値なし'}着 / ST ${r[5]??'—'} / 展示 ${r[8]??'—'}`));extra.append(e('h4','','条件内の直近10走'),list);
 }catch{if(token===detailToken)extra.textContent='履歴を取得できませんでした。詳細ボタンで再試行できます。';}

}
async function loadPlayers(){
 text('player-status','選手データを読み込み中…');
 try{const payload=await json('/data/public/players.json');
 if(!payload?.data)throw new Error('選手データの形式が不正');
 state.playerPayload=payload;
 const branches=[...new Set(Object.values(payload.data).map(p=>p?.branch).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'ja'));
 for(const name of branches){const option=e('option','',name);option.value=name;$('p-branch').append(option);}
 text('player-meta','収録時刻：'+(payload.snapshot_at||'未収録')+'。コース別1着率と決まり手は保存スナップショット由来。上記DBの対象期間・分母は未収録。詳細の下部に、別途収録した母数付き履歴・保存番組表の当地勝率を表示します。今節STは未接続。');
 showPlayers();
 }catch(err){text('player-status','選手データを読み込めませんでした。通信を確認して再読み込みしてください。');}
}
function selectTab(which){
 const history=which==='history';
 $('tab-history').setAttribute('aria-selected',String(history));
 $('tab-players').setAttribute('aria-selected',String(!history));
 $('history-section').hidden=!history;$('players-section').hidden=history;
 if(!history&&!state.playerPayload)loadPlayers();
}
$('tab-history').addEventListener('click',()=>selectTab('history'));
$('tab-players').addEventListener('click',()=>selectTab('players'));
$('history-form').addEventListener('submit',event=>{event.preventDefault();loadHistory();});
$('history-more').addEventListener('click',()=>{state.hLimit+=100;drawHistoryRows();});
$('player-form').addEventListener('submit',event=>{event.preventDefault();if(state.playerPayload)showPlayers();else loadPlayers();});
$('player-more').addEventListener('click',()=>{state.pLimit+=50;drawPlayerRows();});
for(const id of ['p-venue','sim-venue'])for(const [value,name] of VENUES){const option=e('option','',name);option.value=value;$(id).append(option);}
for(const id of ['p-venue','p-window'])$(id).addEventListener('change',()=>{if(selectedPlayer)showDetail(selectedPlayer);});
let simulationRequest=0;
$('sim-form').addEventListener('submit',async event=>{
 event.preventDefault();const token=++simulationRequest;$('sim-results').replaceChildren();text('sim-status','履歴を比較中…');
 try{
  const ids=$('sim-ids').value.normalize('NFKC').split(',').map(s=>s.trim()),order=$('sim-order').value.normalize('NFKC'),venue=$('sim-venue').value;
  entrySimulation(ids,order,{}); // validate before reads
  const records=await Promise.all(ids.map(playerHistory));if(token!==simulationRequest)return;
  const manifest=await researchManifest();if(token!==simulationRequest)return;
  const rows=entrySimulation(ids,order,Object.fromEntries(ids.map((id,i)=>[id,records[i]])),{venue});
  const table=e('table'),head=e('thead'),hr=e('tr');for(const title of ['仮定コース','号艇 / 選手','収録出走','1着率','参考指数'])hr.append(e('th','',title));head.append(hr);table.append(head);
  const body=e('tbody');for(const r of rows){const tr=e('tr');for(const v of [r.course,r.lane+' / '+r.id,r.n+'走',rate(r.firstRate),r.index??'母数不足'])cell(tr,v);body.append(tr);}table.append(body);$('sim-results').append(table);
  text('sim-status',`${dayLabel(manifest.from)}〜${dayLabel(manifest.to)}のコース実績比較。仮定の進入であり、AI確率・推奨買い目ではありません。`);
 }catch(error){if(token===simulationRequest)text('sim-status',error.message);}
});
loadHistory(true);

let indexManifest=null,indexPayload=null,indexRequest=0;
function drawIndex(){
 $('index-results').replaceChildren();const race=indexPayload?.races?.[Number($('index-race').value)];if(!race)return;
 const table=e('table'),head=e('thead'),hr=e('tr');for(const title of ['同点順位帯','出目','相対指数','展開候補'])hr.append(e('th','',title));head.append(hr);table.append(head);
 const body=e('tbody');for(const r of race.ranks){const tr=e('tr');for(const value of [r[6]+'〜'+(r[6]+r[7]-1),r[1],Number(r[2]).toFixed(2),r[5]>0?'候補 '+r[5]+'仮説':'展開根拠なし'])cell(tr,value);body.append(tr);}table.append(body);$('index-results').append(table);
 text('index-status',`${race.model} / ${race.race_id} / 120通り。元予想生成 ${race.source_generated_at??'未記録'} ／ 元予想締切 ${race.source_deadline_at??'未記録'}。指数の作成は事後研究。`);
}
async function loadIndexFile(){
 const token=++indexRequest;indexPayload=null;$('index-results').replaceChildren();$('index-race').replaceChildren();
 text('index-status','研究原本を読み込み中…');
 try{
  const file=indexManifest.files[Number($('index-file').value)]?.file;
  if(!file||!/^[0-9]{8}-(?:venue|yuuki_partial)_[0-9]{2}\.json$/.test(file))throw new Error('研究原本の形式不正');
  const payload=await json('/data/research/indices/'+file);if(token!==indexRequest)return;
  if(payload.calibrated!==false||payload.prospective_index_verified!==false)throw new Error('研究注記の確認が必要です');
  for(const r of payload.races){if(r.ranks?.length!==120||new Set(r.ranks.map(x=>x[1])).size!==120)throw new Error('120通りの原本に欠測があります');}
  indexPayload=payload;payload.races.forEach((r,i)=>{const option=e('option','',r.race_id);option.value=String(i);$('index-race').append(option);});drawIndex();
 }catch(error){if(token===indexRequest)text('index-status','読込エラー：'+error.message);}
}
$('index-load').addEventListener('click',async()=>{
 try{indexManifest=await json('/data/research/indices/manifest.json');$('index-file').replaceChildren();
  indexManifest.files.forEach((f,i)=>{const option=e('option','',f.date+' / '+f.model);option.value=String(i);$('index-file').append(option);});$('index-controls').hidden=false;await loadIndexFile();
 }catch{ text('index-status','研究一覧を取得できませんでした。再度ボタンを押してください。');}
});
$('index-file').addEventListener('change',loadIndexFile);$('index-race').addEventListener('change',drawIndex);
