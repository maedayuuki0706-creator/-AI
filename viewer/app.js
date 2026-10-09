'use strict';
const VENUES=[['01','桐生'],['02','戸田'],['03','江戸川'],['04','平和島'],['05','多摩川'],['06','浜名湖'],['07','蒲郡'],['08','常滑'],['09','津'],['10','三国'],['11','びわこ'],['12','住之江'],['13','尼崎'],['14','鳴門'],['15','丸亀'],['16','児島'],['17','宮島'],['18','徳山'],['19','下関'],['20','若松'],['21','芦屋'],['22','福岡'],['23','唐津'],['24','大村']];
const API='https://boat-sheet-feed.onrender.com';
const RAW='https://raw.githubusercontent.com/maedayuuki0706-creator/-AI/main/data/prototype12_delivery/predictions/';
const DATA_RAW='https://raw.githubusercontent.com/maedayuuki0706-creator/-AI/main/data/';
const PACKS=new Map();
const playerState={players:[],selected:'',snapshotAt:'',loadPromise:null,livePromise:null,lastChecked:0,status:'',composing:false};
const $=id=>document.getElementById(id);
const state={day:'',venue:'20',race:8,tab:'pt2',token:0,prediction:null,raceRows:[],rosterRows:[],active:null,
  pt2Status:'予想を読み込んでいます…',raceStatus:'出走情報はタブを開いたときに読み込みます。',
  raceLoadingKey:'',raceLoadedKey:'',userSelectedVenue:false,venueToken:0};
const CACHE_PREFIX='boat-race-view-v4:';
function cacheRead(name,ttl) {
  try{
    const obj=JSON.parse(localStorage.getItem(CACHE_PREFIX+name)||'null');
    if(obj&&Number.isFinite(obj.storedAt)&&Date.now()-obj.storedAt>=0&&Date.now()-obj.storedAt<ttl)return obj;
  }catch(e){}
  return null;
}
function cacheWrite(name,value) {
  try{
    localStorage.setItem(CACHE_PREFIX+name,JSON.stringify({storedAt:Date.now(),value}));
    const keys=Object.keys(localStorage).filter(k=>k.startsWith(CACHE_PREFIX+'pt2:')||k.startsWith(CACHE_PREFIX+'race:')||k.startsWith(CACHE_PREFIX+'roster:')||k.startsWith(CACHE_PREFIX+'card:'));
    if(keys.length>75){keys.sort((a,b)=>JSON.parse(localStorage.getItem(a)).storedAt-JSON.parse(localStorage.getItem(b)).storedAt);keys.slice(0,keys.length-75).forEach(k=>localStorage.removeItem(k));}
  }catch(e){}
}
function lightPrediction(j) {
  if(!j||!j.models||!j.models.prototype2)return null;
  const p=j.models.prototype2;
  const cards={};
  for(const [key,c] of Object.entries(p.strategy_cards?.cards||{})){
    if(['balanced','probability','value','longshot'].includes(key))cards[key]={main_picks:c.main_picks,cover_picks:c.cover_picks,point_count:c.point_count,selection_policy:c.selection_policy};
  }
  return {day:j.day,jcd:j.jcd,rno:j.rno,venue:j.venue,deadline:j.deadline,created_at:j.created_at,digest:j.digest,
    models:{prototype2:{grade:p.grade,heads:p.heads,strategy_cards:{cards}}}};
}
function currentKey(){return yyyymmdd()+'_'+state.venue+'_'+String(state.race).padStart(2,'0');}
function refreshStatus(){$('status').textContent=state.tab==='player'?(playerState.status||'選手名・登録番号で検索できます。'):state.tab==='pt2'?state.pt2Status:state.raceStatus;}
function jstClock(){return new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit'}).format(new Date());}
const safe=x=>String(x==null?'':x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const jstToday=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const yyyymmdd=()=>state.day.replace(/-/g,'');
const number=(v,d=1)=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v))?Number(v).toFixed(d):'—';
function csv(text) {
 const rows=[];let row=[],part='',quoted=false;
 text=String(text||'').replace(/^\uFEFF/,'');
 for(let i=0;i<text.length;i++){
  const c=text[i];
  if(quoted){if(c==='"'&&text[i+1]==='"'){part+='"';i++;}else if(c==='"'){quoted=false;}else{part+=c;}}
  else if(c==='"'){quoted=true;}
  else if(c===','){row.push(part);part='';}
  else if(c==='\n'){row.push(part.replace(/\r$/,''));if(row.some(x=>x!==''))rows.push(row);row=[];part='';}
  else{part+=c;}
 }
 if(row.length||part){row.push(part.replace(/\r$/,''));if(row.some(x=>x!==''))rows.push(row);}
 return rows;
}
async function getText(url,timeout=18000,force=false) {
 const c=new AbortController();const timer=setTimeout(()=>c.abort(),timeout);
 try{const r=await fetch(url,{signal:c.signal,cache:force?'reload':'default'});
 if(!r.ok){const e=new Error('HTTP '+r.status);e.status=r.status;throw e;}
 return await r.text();}finally{clearTimeout(timer);}
}
async function getJson(url,timeout=18000,force=false){return JSON.parse(await getText(url,timeout,force));}
function getPack(key){
 if(!PACKS.has(key))PACKS.set(key,getJson('data/races/'+key+'.json',5000).catch(()=>null));
 return PACKS.get(key);
}
function setStatus(x){$('status').textContent=x;}
function updateAddress() {
 const params=new URLSearchParams();params.set('date',state.day);params.set('venue',state.venue);params.set('race',String(state.race));
 try{history.replaceState({},'',location.pathname+'?'+params.toString());}catch(e){}
 $('official').href='https://www.boatrace.jp/owpc/pc/race/racelist?hd='+yyyymmdd()+'&jcd='+state.venue+'&rno='+state.race;
}
function venueOptions(){
 $('venue').innerHTML=VENUES.map(v=>'<option value="'+v[0]+'">'+safe(v[1])+(Array.isArray(state.active)&&!state.active.includes(v[0])?'（開催未確認）':'')+'</option>').join('');
 $('venue').value=state.venue;
}
function raceOptions(){$('race').innerHTML=Array.from({length:12},(_,i)=>'<option value="'+(i+1)+'">'+(i+1)+'R</option>').join('');$('race').value=String(state.race);}
function setTab(tab){
 state.tab=tab;
 for(const name of ['pt2','race','player']){$('tab-'+name).setAttribute('aria-selected',String(tab===name));$('view-'+name).classList.toggle('hidden',tab!==name);}
 if(tab==='race')loadRaceData();
 if(tab==='player')loadPlayers();
 refreshStatus();
}
function inside(section){return '<section class="panel">'+section+'</section>';}
function predictionHtml(j){
 if(!j||!j.models||!j.models.prototype2)return inside('<div class="empty">このレースのPT2予想は保存されていません。</div>');
 if(j.day!==yyyymmdd()||String(j.jcd)!==state.venue||Number(j.rno)!==state.race)return inside('<div class="error">別レースの予想が返されたため表示を止めました。</div>');
 const p=j.models.prototype2,cards=p.strategy_cards&&p.strategy_cards.cards||{},time=j.created_at||'—';
 const labels=[['balanced','総合型'],['probability','本命型'],['value','妙味型'],['longshot','高配当型']];
 let h='<div class="panel"><div class="section-head"><div><h2>'+safe(j.venue)+' '+safe(j.rno)+'R ／ PT2</h2><p>締切 '+safe(j.deadline||'—')+'・生成 '+safe(time.replace('T',' ').slice(0,19))+'（JST）</p></div><span class="pill">'+safe(p.grade||'PT2')+' 評価</span></div>';
 h+='<div class="notice">予想はGitHubへ保存された時点のスナップショットです。オッズや出走情報は生成後に変わる場合があります。PT2予想シートの全表示項目と完全同一ではありません。</div>';
 h+='<p class="subhead">1着推定確率（モデル値）</p><div class="lanes">';
 for(let n=1;n<=6;n++){const value=(p.heads||{})[String(n)];h+='<div class="lane lane-'+n+'"><b>'+n+'号艇</b><strong>'+(value===null||value===undefined?'—':number(value*100,1)+'%')+'</strong></div>';}
 h+='</div></div><div class="grid">';
 let count=0;
 for(const entry of labels){const c=cards[entry[0]];if(!c)continue;count++;
 const main=(c.main_picks||[]),cover=(c.cover_picks||[]);
 h+='<article class="card"><h3>'+safe(entry[1])+'</h3><div class="kv"><span>'+safe(c.point_count||main.length+cover.length)+'点</span><span>'+safe(c.selection_policy||'')+'</span></div>';
 h+='<div class="subhead">本線 '+main.length+'点</div><div class="picks">'+main.map(k=>'<span class="pick">'+safe(k)+'</span>').join('')+'</div>';
 if(cover.length)h+='<div class="subhead">抑え '+cover.length+'点</div><div class="picks">'+cover.map(k=>'<span class="pick">'+safe(k)+'</span>').join('')+'</div>';
 h+='</article>';
 }
 h+='</div>';
 if(!count)h+=inside('<div class="empty">予想候補を確認できませんでした。</div>');
 h+=inside('<p>「激絞り」など元のスプレッドシート側で別計算される項目は、同一データが公開保存されていない場合は表示しません。全点数を機械的に増やしたり、別モデルと混同したりしないための措置です。</p>');
 return h;
}
function tableData(rows){
 if(rows.length<2)return [];
 const head=rows[0];return rows.slice(1).map(r=>Object.fromEntries(head.map((k,i)=>[k,(r[i]||'')]))).filter(obj=>Object.values(obj).some(Boolean));
}
function raceHtml(){
 const roster=state.rosterRows,data=state.raceRows;
 if(!roster.length&&!data.length)return inside('<h2>出走表</h2><div class="empty">このレースの出走データを確認できませんでした。非開催・取得遅延の可能性があります。</div>');
 const title=VENUES.find(v=>v[0]===state.venue)?.[1]||'場';
 const byRacer=new Map(roster.map((r,i)=>[String(r['登録番号']||''),r]));
 const rows=data.length?data:roster.map((r,i)=>({...r,'枠':String(i+1)}));
 let h='<section class="panel"><div class="section-head"><div><h2>'+safe(title)+' '+state.race+'R ／ 出走表</h2><p>'+(state.raceSnapshotAt?'保存時点の出走表 ／ '+safe(displayTime(state.raceSnapshotAt)):'公式出走フィード')+'</p></div></div><div class="notice">選手名を押すと、コース別1着率などのデータベース情報を確認できます。保存済みの出走表は取得時点の情報です。最新情報は「情報を更新」で確認してください。</div><div class="table-wrap"><table><thead><tr><th>艇</th><th>選手</th><th>級別</th><th>全国勝率</th><th>平均ST</th><th>モーター</th><th>2連率</th><th>展開材料</th></tr></thead><tbody>';
 rows.forEach((r,i)=>{
 const lane=Number(r['枠']||i+1);if(lane<1||lane>6)return;
 const reg=String(r['登録番号']||'');const d=byRacer.get(reg)||roster[lane-1]||{};
 const id=reg||d['登録番号']||'';
 h+='<tr><td><span class="boat boat-'+lane+'">'+lane+'</span></td><td><button type="button" class="player-link" data-player-id="'+safe(id)+'">'+safe(d['選手名']||'未取得')+'</button><div class="small">'+safe(id)+'</div></td><td>'+safe(r['級別']||d['級別']||'—')+'</td><td class="num">'+safe(r['全国勝率']||'—')+'</td><td class="num">'+safe(r['平均ST']||'—')+'</td><td>'+safe(d['モーターNo.']||'—')+'</td><td>'+safe(d['モーター2連率']||'—')+'</td><td>'+safe(r['展開材料']||'—')+'</td></tr>';
 });
 h+='</tbody></table></div></section>';
 const deadline=rows[0]?.['締切']||'';
 h+=inside('<p>締切情報：'+safe(deadline||'確認中')+' ／ データ取得日は '+safe(state.day)+'。出走表はフィード取得時点の情報であり、欠場や進入変更は公式で最終確認してください。</p><div class="ext"><a target="_blank" rel="noopener noreferrer" href="'+safe($('official').href)+'">公式出走表を開く ↗</a></div>');
 return h;
}
function errorsInPart(name,e) {
 return e&&e.status===404 ? name+'がまだ公開されていません。':name+'の取得に失敗しました（'+safe(e.message||'通信エラー')+'）。';
}

function cardMatches(card){
 return card&&card.day===yyyymmdd()&&String(card.jcd)===state.venue&&Number(card.rno)===state.race&&Array.isArray(card.boats)&&card.boats.length===6;
}
function applyCard(card){
 if(!cardMatches(card))return false;
 const val=v=>v===null||v===undefined?'':String(v);
 state.raceRows=card.boats.map(b=>({'枠':val(b.lane),'登録番号':val(b.racer_id),'級別':val(b.current_class),'全国勝率':val(b.win_rate),'平均ST':val(b.avg_st),'締切':val(card.deadline),'展開材料':b.flying?'F持ち':b.local_win_rate!==null&&b.local_win_rate!==undefined?'当地勝率'+number(b.local_win_rate,2):''}));
 state.rosterRows=card.boats.map(b=>({'登録番号':val(b.racer_id),'選手名':val(b.name),'級別':val(b.current_class),'モーターNo.':val(b.motor_number),'モーター2連率':val(b.motor_top2_rate)}));
 state.raceSnapshotAt=card.captured_at||'';
 cacheWrite('card:'+currentKey(),card);
 $('view-race').innerHTML=raceHtml();
 state.raceStatus='保存済み出走表を表示中（'+displayTime(card.captured_at)+'）';
 refreshStatus();
 return true;
}
async function loadRaceData(force=false){
 const key=currentKey(),token=state.token;
 if(!force&&(state.raceLoadingKey===key||state.raceLoadedKey===key))return;
 state.raceLoadingKey=key;
 const saved=cacheRead('card:'+key,7*86400000);
 if(saved)applyCard(saved.value);
 else{
  state.raceRows=cacheRead('race:'+key,7*86400000)?.value||[];
  state.rosterRows=cacheRead('roster:'+key,7*86400000)?.value||[];
  state.raceSnapshotAt='';
  $('view-race').innerHTML=(state.raceRows.length||state.rosterRows.length)?raceHtml():inside('<div class="empty">出走表を読み込んでいます…</div>');
 }
 if(!force){
  const pack=await getPack(key);
  if(token!==state.token)return;
  if(pack?.race&&applyCard(pack.race)){
   state.raceLoadingKey='';state.raceLoadedKey=key;return;
  }
  try{
   const request=await getJson(DATA_RAW+'hiyori/requests/'+key+'.json',10000);
   if(token!==state.token)return;
   const boats=request.official?.inputs;
   const fields=['lane','racer_id','name','current_class','win_rate','avg_st','motor_number','motor_top2_rate','local_win_rate','flying'];
   const card={day:request.day,jcd:request.jcd,rno:request.rno,deadline:request.deadline,captured_at:request.captured_at,boats:Array.isArray(boats)?boats.map(b=>Object.fromEntries(fields.map(k=>[k,b[k]]))):[]};
   if(applyCard(card)){state.raceLoadingKey='';state.raceLoadedKey=key;return;}
  }catch(e){}
 }
 if(token!==state.token)return;
 state.raceStatus=(state.raceRows.length||state.rosterRows.length)?'保存済み出走表を表示中・公式フィードを確認しています…':'出走情報を取得しています…';refreshStatus();
 const args='date='+yyyymmdd()+'&jcd='+state.venue+'&rno='+state.race;
 const results=await Promise.allSettled([
  getText(API+'/race.csv?'+args,42000,force).then(t=>tableData(csv(t))),
  getText(API+'/race_roster.csv?'+args,42000,force).then(t=>tableData(csv(t)))
 ]);
 if(token!==state.token)return;
 let updated=false;
 if(results[0].status==='fulfilled'&&results[0].value.length){state.raceRows=results[0].value;cacheWrite('race:'+key,state.raceRows);updated=true;}
 if(results[1].status==='fulfilled'&&results[1].value.length){state.rosterRows=results[1].value;cacheWrite('roster:'+key,state.rosterRows);updated=true;}
 state.raceLoadingKey='';state.raceLoadedKey=key;
 if(state.raceRows.length||state.rosterRows.length){
  if(updated)state.raceSnapshotAt='';
  $('view-race').innerHTML=raceHtml();
  state.raceStatus=updated?'出走情報を更新しました（'+jstClock()+' JST確認）':'保存済み出走表を表示中・最新フィードは取得できませんでした。';
 }else{
  $('view-race').innerHTML=inside('<h2>出走表</h2><div class="empty">出走情報を取得できませんでした。公式サイトを確認するか、情報を更新してください。</div>');
  state.raceStatus='出走情報を取得できませんでした。更新で再試行できます。';
 }
 refreshStatus();
}
async function loadRace(force=false){
 const token=++state.token,key=currentKey();
 updateAddress();
 state.raceLoadingKey='';state.raceLoadedKey='';state.raceSnapshotAt='';
 state.raceRows=[];state.rosterRows=[];
 $('view-race').innerHTML=inside('<div class="empty">出走表タブを開くと詳細を取得します。</div>');
 state.raceStatus='出走情報はタブを開いたときに読み込みます。';
 const cached=cacheRead('pt2:'+key,7*86400000);
 state.prediction=cached?.value||null;
 if(state.prediction){$('view-pt2').innerHTML=predictionHtml(state.prediction);state.pt2Status='保存済みのPT2予想を表示中';}
 else{$('view-pt2').innerHTML=inside('<div class="empty">PT2予想を読み込んでいます…</div>');state.pt2Status='PT2予想を読み込んでいます…';}
 refreshStatus();
 if(state.tab==='race')loadRaceData(force);
 const apply=data=>{
  if(token!==state.token)return;
  const light=lightPrediction(data);
  if(!light||light.day!==yyyymmdd()||String(light.jcd)!==state.venue||Number(light.rno)!==state.race)throw new Error('予想データが選択レースと一致しません');
  state.prediction=light;cacheWrite('pt2:'+key,light);
  $('view-pt2').innerHTML=predictionHtml(light);state.pt2Status='PT2予想を表示中（生成 '+displayTime(light.created_at)+'）';refreshStatus();
 };
 // A fresh persisted result is already usable; keystrokes and tab switches do
 // not re-download prediction models or wake the free feed service.
 if(!force&&cached&&Date.now()-cached.storedAt<240000)return;
 const pack=force?null:await getPack(key);
 if(token!==state.token)return;
 if(pack?.prediction)apply(pack.prediction);
 if(!force&&pack?.prediction&&state.day!==jstToday())return;
 if(!force&&state.prediction?.digest){
  try{
   const receipt=await getJson(DATA_RAW+'prototype12_delivery/deliveries/prototype2/'+key+'.json',8000);
   if(token!==state.token)return;
   if(receipt.key===key&&receipt.prediction_digest===state.prediction.digest)return;
  }catch(e){}
 }
 try{apply(await getJson(RAW+key+'.json',18000,force));}
 catch(e){
  if(token!==state.token)return;
  if(state.prediction)state.pt2Status='保存済みのPT2予想を表示中・最新データは取得できませんでした。';
  else{
   $('view-pt2').innerHTML=inside('<h2>PT2予想</h2><div class="error">'+errorsInPart('PT2保存済み予想',e)+'</div><p>保存済みの予想が公開され次第、閲覧できます。</p>');
   state.pt2Status='PT2予想を取得できませんでした。日時・開催場を確認してください。';
  }
  refreshStatus();
 }
}
async function loadVenues(keepSelection) {
 const requestDay=yyyymmdd(), requestToken=++state.venueToken;
 const cached=cacheRead('venues:'+requestDay,600000);
 function applyVenues(venueCodes) {
   if(requestToken!==state.venueToken||requestDay!==yyyymmdd())return;
   state.active=venueCodes.length?venueCodes:null;
   if(!keepSelection&&!state.userSelectedVenue&&state.active&&!state.active.includes(state.venue)){
     // 手動で選択した競艇場は書き換えない。
     state.venue=state.active[0];
     venueOptions();
     loadRace();
   }else venueOptions();
 }
 if(cached)applyVenues(cached.value);
 try{
   let rows;
   try{
     const card=await getJson(DATA_RAW+'race_cards/'+requestDay+'.json',8000);
     if(card.day!==requestDay||!card.complete)throw new Error('開催情報未確定');
     rows=[...new Set(Object.values(card.races||{}).map(r=>r.jcd))].map(code=>[code]);
   }catch(e){rows=csv(await getText(API+'/venues.csv?date='+requestDay,42000)).slice(1);}
   if(requestDay!==yyyymmdd()||requestToken!==state.venueToken)return;
   const active=rows.map(r=>String(r[0]).padStart(2,'0')).filter(code=>VENUES.some(v=>v[0]===code));
   if(active.length)cacheWrite('venues:'+requestDay,active);
   applyVenues(active);
 }catch(e){
   if(requestDay!==yyyymmdd()||requestToken!==state.venueToken)return;
   if(!cached)state.active=null;
   venueOptions();
 }
}
function selectRace(){
 state.userSelectedVenue=true;
 state.venue=$('venue').value;
 state.race=Number($('race').value);
 loadRace();
}
const PLAYER_FIELDS=[['登録番号','id'],['選手名','name'],['級別','class'],['支部','branch'],['勝率','win'],['平均ST','avg_st'],['逃げ率','escape'],['差し率','sashi'],['まくり率','makuri'],['まくり差し率','makurisashi'],['元A級','former_a'],['得意決まり手','best_method'],['総合評価','overall_grade'],['モーター整備力','maintenance_grade'],['ペラ調整力','propeller_grade'],['弱機立て直し力','weak_motor_recovery'],['弱機立て直しサンプル数','weak_motor_samples'],['整備改善値','maintenance_improvement'],['ペラ改善値','propeller_improvement'],['整備サンプル数','maintenance_samples'],['ペラサンプル数','propeller_samples'],['最新調整コメント','latest_adjustment_comment'],['メモ','memo']];
const normalizeQuery=v=>String(v||'').normalize('NFKC').replace(/[\s\u3000]+/g,'').toLowerCase();
function displayTime(value){
 const date=new Date(value);
 return !value||!Number.isFinite(date.getTime())?'日時未取得':new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}).format(date)+' JST';
}
function numericValue(value){
 if(value===null||value===undefined||String(value).trim()==='')return null;
 const n=Number(String(value).replace(/%/g,''));return Number.isFinite(n)?n:null;
}
function percentage(value){const n=numericValue(value);return n===null?'—':n.toFixed(1)+'%';}
function playerValue(value,decimals){
 if(value===null||value===undefined||String(value).trim()==='')return '—';
 const n=numericValue(value);return decimals!==undefined&&n!==null?n.toFixed(decimals):String(value);
}
function parsePlayers(payload){
 let players=[];
 if(Array.isArray(payload.rows)&&Array.isArray(payload.fields)){
  const indices=new Map(payload.fields.map((v,i)=>[v,i]));
  players=payload.rows.map(row=>{
   const p=Object.fromEntries(PLAYER_FIELDS.map(([label,key])=>[key,row[indices.get(label)]??null]));
   p.course_win=Array.from({length:6},(_,i)=>row[indices.get((i+1)+'コース1着率')]??null);return p;
  });
 }else if(payload&&typeof payload==='object'){
  players=Object.entries(payload).map(([id,p])=>({...p,id}));
 }
 const seen=new Set();
 return players.filter(p=>/^\d{4}$/.test(String(p.id))&&p.name&&!seen.has(String(p.id))&&seen.add(String(p.id))).map(p=>({...p,id:String(p.id),search:normalizeQuery(p.name)+' '+String(p.id)}));
}
function playerDetailHtml(p){
 const metrics=[['登録番号',p.id],['級別',p.class],['勝率',playerValue(p.win,2)],['平均ST',playerValue(p.avg_st,2)]];
 let h='<article class="panel player-detail"><div class="section-head"><div><div class="kicker">RACER / '+safe(p.id)+'</div><h2>'+safe(p.name)+'</h2><p>'+safe(playerValue(p.branch))+'支部</p></div><span class="pill">'+safe(playerValue(p.class))+'</span></div><div class="player-metrics">';
 h+=metrics.map(([label,value])=>'<div class="player-metric"><span>'+safe(label)+'</span><strong>'+safe(playerValue(value))+'</strong></div>').join('')+'</div><h3>コース別1着率</h3><div class="course-bars">';
 for(let i=0;i<6;i++){
  const value=p.course_win?.[i],n=numericValue(value),width=n===null?0:Math.max(0,Math.min(100,n));
  h+='<div class="course-row" aria-label="'+(i+1)+'コース 1着率 '+safe(percentage(value))+'"><span class="boat boat-'+(i+1)+'">'+(i+1)+'</span><div class="course-track" aria-hidden="true"><div class="course-fill" style="width:'+width+'%"></div></div><span class="course-value">'+safe(percentage(value))+'</span></div>';
 }
 h+='</div><h3>決まり手の割合</h3><div class="method-grid">';
 h+=[['逃げ',p.escape],['差し',p.sashi],['まくり',p.makuri],['まくり差し',p.makurisashi]].map(([label,value])=>'<div class="method-cell"><span>'+label+'</span><strong>'+safe(percentage(value))+'</strong></div>').join('')+'</div><h3>評価・調整データ</h3><dl class="rating-list">';
 const ratings=[['得意決まり手',p.best_method],['総合評価',p.overall_grade],['モーター整備力',p.maintenance_grade],['ペラ調整力',p.propeller_grade],['弱機立て直し力',p.weak_motor_recovery],['元A級',p.former_a],['整備改善値',p.maintenance_improvement],['ペラ改善値',p.propeller_improvement],['整備サンプル数',p.maintenance_samples],['ペラサンプル数',p.propeller_samples],['弱機サンプル数',p.weak_motor_samples]];
 h+=ratings.map(([label,value])=>'<div><dt>'+label+'</dt><dd>'+safe(playerValue(value))+'</dd></div>').join('')+'</dl>';
 if(p.latest_adjustment_comment)h+='<h3>最新調整コメント</h3><p class="player-comment">'+safe(p.latest_adjustment_comment)+'</p>';
 if(p.memo)h+='<h3>メモ</h3><p class="player-comment">'+safe(p.memo)+'</p>';
 h+='<div class="player-meta"><p>出典：競艇AI データベース／選手データ<br>データ取得：'+safe(displayTime(playerState.snapshotAt))+'<br>— は未登録。割合・評価はシート記載値です。</p><button type="button" class="player-refresh" data-player-refresh>選手情報を更新</button></div></article>';
 return h;
}
function renderPlayers(){
 if(state.tab!=='player')return;
 const query=normalizeQuery($('player-query').value);
 if(!playerState.players.length){$('view-player').innerHTML=inside('<div class="empty player-empty">'+safe(playerState.status||'選手データを読み込んでいます…')+'</div>');return;}
 if(!query){$('view-player').innerHTML=inside('<h2>選手データを検索</h2><p>名前の一部、フルネーム、登録番号で検索できます。</p><div class="notice">登録 '+playerState.players.length+'名 ／ データ取得 '+safe(displayTime(playerState.snapshotAt))+'</div><div class="empty">上の検索欄に選手名を入力してください。<br>例：毒島、峰、4238</div>');return;}
 const matches=playerState.players.filter(p=>p.search.includes(query)).sort((a,b)=>{
  const rank=p=>p.id===query||normalizeQuery(p.name)===query?0:normalizeQuery(p.name).startsWith(query)?1:2;
  return rank(a)-rank(b)||a.name.localeCompare(b.name,'ja');
 });
 if(!matches.length){$('view-player').innerHTML=inside('<h2>検索結果</h2><div class="empty player-empty">「'+safe($('player-query').value)+'」に一致する選手はいません。<br>名前の一部や登録番号を試してください。</div>');return;}
 const visible=matches.slice(0,30);
 let selected=visible.find(p=>p.id===playerState.selected)||visible[0];playerState.selected=selected.id;
 const list='<aside class="panel player-results" id="player-results" aria-label="選手検索結果"><div class="result-summary">'+matches.length+'名が一致'+(matches.length>30?' ／ 先頭30名を表示':'')+'<br>選手を選んで成績を確認</div>'+visible.map(p=>'<button type="button" class="player-result" data-player-id="'+safe(p.id)+'" aria-pressed="'+(selected.id===p.id)+'"><strong>'+safe(p.name)+'</strong><span>'+safe(p.id)+' ／ '+safe(playerValue(p.class))+' ／ '+safe(playerValue(p.branch))+'</span></button>').join('')+'</aside>';
 $('view-player').innerHTML='<div class="player-layout">'+list+playerDetailHtml(selected)+'</div>';
}
function setPlayerData(payload,snapshotAt){
 const players=parsePlayers(payload);if(!players.length)throw new Error('有効な選手データがありません');
 playerState.players=players;playerState.snapshotAt=snapshotAt||payload.snapshot_at||'';
 playerState.status=players.length+'名の選手データ ／ 取得 '+displayTime(playerState.snapshotAt);
 cacheWrite('players',{players:players.map(({search,...p})=>p),snapshotAt:playerState.snapshotAt});renderPlayers();refreshStatus();
}
async function refreshLivePlayers(force=false){
 if(playerState.livePromise)return playerState.livePromise;
 if(!force&&Date.now()-playerState.lastChecked<300000)return;
 playerState.lastChecked=Date.now();
 playerState.livePromise=(async()=>{
  try{
   const meta=await getJson(DATA_RAW+'sheet_db/meta.json',12000,force);
   if(meta.source!=='Google Sheets 競艇AI データベース'||!Number.isFinite(new Date(meta.snapshot_at).getTime()))throw new Error('取得元を確認できません');
   if(new Date(meta.snapshot_at)>new Date(playerState.snapshotAt)||!playerState.players.length){
    const players=await getJson(DATA_RAW+'sheet_db/players.json',18000,force);
    setPlayerData(players,meta.snapshot_at);
   }else{
    playerState.status=playerState.players.length+'名の選手データ ／ 取得 '+displayTime(playerState.snapshotAt)+'（更新確認済み）';refreshStatus();
   }
  }catch(e){
   playerState.status=playerState.players.length?'保存済み選手情報を表示中・最新データの確認に失敗しました。':'選手情報を取得できませんでした。更新で再試行できます。';refreshStatus();
  }finally{playerState.livePromise=null;}
 })();
 return playerState.livePromise;
}
async function loadPlayers(force=false){
 if(!playerState.players.length&&!playerState.loadPromise){
  const cached=cacheRead('players',7*86400000);
  if(cached?.value?.players?.length){
   playerState.players=cached.value.players.map(p=>({...p,search:normalizeQuery(p.name)+' '+p.id}));playerState.snapshotAt=cached.value.snapshotAt;
   playerState.status=playerState.players.length+'名の選手データ ／ 取得 '+displayTime(playerState.snapshotAt);renderPlayers();
  }else{
   playerState.status='選手データを読み込んでいます…';renderPlayers();refreshStatus();
   playerState.loadPromise=(async()=>{
    try{const bundle=await getJson('data/players.json',10000);setPlayerData(bundle,bundle.snapshot_at);}
    catch(e){playerState.status='選手データの読み込みに失敗しました。更新で再試行できます。';renderPlayers();}
    finally{playerState.loadPromise=null;}
   })();
  }
 }
 if(playerState.loadPromise)await playerState.loadPromise;
 renderPlayers();refreshStatus();
 refreshLivePlayers(force);
}
async function openPlayer(id){
 $('player-query').value=id;playerState.selected=id;setTab('player');await loadPlayers();renderPlayers();
}
function setupPlayerSearch(){
 $('player-search-form').addEventListener('submit',e=>{e.preventDefault();playerState.selected='';setTab('player');renderPlayers();$('view-player').scrollIntoView({block:'start',behavior:'smooth'});});
 $('player-query').addEventListener('compositionstart',()=>{playerState.composing=true;});
 const changed=()=>{if(playerState.composing)return;playerState.selected='';if($('player-query').value.trim()){setTab('player');renderPlayers();}else if(state.tab==='player')renderPlayers();};
 $('player-query').addEventListener('compositionend',()=>{playerState.composing=false;changed();});
 $('player-query').addEventListener('input',changed);
 $('view-player').addEventListener('click',e=>{
  const button=e.target.closest('button[data-player-id]');
  if(button){playerState.selected=button.dataset.playerId;renderPlayers();}
  if(e.target.closest('[data-player-refresh]'))loadPlayers(true);
 });
 $('view-race').addEventListener('click',e=>{const button=e.target.closest('button[data-player-id]');if(button?.dataset.playerId)openPlayer(button.dataset.playerId);});
}
function boot(){
 const params=new URLSearchParams(location.search);
 const day=params.get('date')||jstToday();state.day=/^20\d{2}-\d\d-\d\d$/.test(day)?day:jstToday();
 const venue=params.get('venue');state.venue=VENUES.some(x=>x[0]===venue)?venue:'20';
 const race=Number(params.get('race'));state.race=Number.isInteger(race)&&race>=1&&race<=12?race:8;
 $('day').value=state.day;venueOptions();raceOptions();
 $('tab-pt2').addEventListener('click',()=>setTab('pt2'));
 $('tab-race').addEventListener('click',()=>setTab('race'));
 $('tab-player').addEventListener('click',()=>{setTab('player');$('player-query').focus();});
 setupPlayerSearch();
 $('day').addEventListener('change',()=>{if(!$('day').value)return;state.day=$('day').value;state.active=null;loadRace();loadVenues(Boolean(venue));});
 $('venue').addEventListener('change',selectRace);
 $('race').addEventListener('change',selectRace);
 $('refresh').addEventListener('click',()=>{if(state.tab==='player')loadPlayers(true);else loadRace(true);});
 // 予想は即時読み込み。休止中の出走情報フィードを待たない。
 loadRace();
 loadVenues(Boolean(venue));
 getJson('data/manifest.json',5000).then(m=>{
   if(!Array.isArray(state.active)&&m.days?.[yyyymmdd()]){state.active=m.days[yyyymmdd()];venueOptions();}
 }).catch(()=>{});
}



boot();
