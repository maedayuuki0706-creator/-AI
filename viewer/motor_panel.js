/* Public motor evaluations from existing read-only sheet-db snapshots.
 * S/A/B/C/D are inherited grades, NOT freshly calculated live-race predictions.
 */
(function (root) {
 'use strict';
 const ROOT='https://raw.githubusercontent.com/maedayuuki0706-creator/-AI/main/data/sheet_db/';
 const MARKS={
   S:{mark:'◎',label:'最上位',css:'best'},A:{mark:'○',label:'高評価',css:'good'},
   B:{mark:'△',label:'標準',css:'average'},C:{mark:'注意',label:'低め',css:'caution'},
   D:{mark:'低',label:'低評価',css:'low'}
 };
 const FIELDS=[['伸び','stretch'],['出足','launch'],['回り足','turn'],['行き足','run']];
 const dateValue=v=>{
   const s=String(v||'').trim();
   const m=/^(20\d{2})[/-](\d{2})[/-](\d{2})$/.exec(s);
   if(!m)return '';
   return m[1]+m[2]+m[3];
 };
 const canonJcd=x=>String(x??'').padStart(2,'0');
 const stamp=v=>{
   const d=new Date(v);
   return !v||!Number.isFinite(d.getTime())?'不明':
      new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',year:'numeric',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}).format(d)+' JST';
 };
 function gradeMark(grade){
   const key=String(grade||'').trim().toUpperCase();
   return MARKS[key]?{...MARKS[key],source:key}:{mark:'—',label:'未評価',css:'missing',source:''};
 }
 function motorKey(venue,no){
   const number=Number(no);
   if(!/^\d{1,2}$/.test(String(venue))||!Number.isInteger(number)||number<1||number>999)return '';
   return canonJcd(venue)+':'+number;
 }
 function pick(motors,venue,no){
   if(!motors||typeof motors!=='object'||Array.isArray(motors))return null;
   const key=motorKey(venue,no);
   const entry=key?motors[key]:null;
   if(!entry||Number(entry.motor)!==Number(no))return null;
   return entry;
 }
 const status={meta:null,motors:null,loadedAt:0,promise:null,error:'',enabled:false};
 let getRace=()=>({}),requestRoster=()=>Promise.resolve();
 function toText(v){return String(v===undefined||v===null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
 function badge(value){
   const g=gradeMark(value);
   return '<span class="motor-mark motor-mark--'+g.css+'" title="'+toText(g.label+(g.source?'（'+g.source+'評価）':''))+'">'+toText(g.mark)+'</span>';
 }
 function validMeta(j){
   return j&&j.source==='Google Sheets 競艇AI データベース'&&
     Number.isFinite(Date.parse(j.snapshot_at))&&Number.isInteger(j.motor_count)&&j.motor_count>0;
 }
 async function getJson(url,timeout=12000){
   const c=new AbortController(),timer=setTimeout(()=>c.abort(),timeout);
   try{
     const r=await fetch(url,{signal:c.signal,cache:'no-store'});
     if(!r.ok)throw new Error('HTTP '+r.status);
     return await r.json();
   }finally{clearTimeout(timer);}
 }
 async function readMeta(force=false){
   try{
     if(status.meta&&!force&&Date.now()-status.loadedAt<300000)return status.meta;
     const j=await getJson(ROOT+'meta.json?at='+Math.floor(Date.now()/60000),12000);
     if(!validMeta(j))throw new Error('モーターデータの出典情報が一致しません');
     status.meta=j;
     const count=document.getElementById('home-motor-count');
     if(count)count.textContent=Number(j.motor_count).toLocaleString('ja-JP')+'機';
     const asOf=document.getElementById('home-motor-updated');
     if(asOf)asOf.textContent='DB更新 '+stamp(j.snapshot_at);
     return j;
   }catch(e){
     const node=document.getElementById('home-motor-updated');
     if(node)node.textContent='取得日時未確認';
     return null;
   }
 }
 function rosterData(race){
   const roster=Array.isArray(race.roster)?race.roster:[];
   const normalized=[];
   const laneMap=new Map(roster.map((r,i)=>[String(r['登録番号']||''),r]));
   // Fast saved cards are already ordered by lane. Live roster CSV may be matched by racer ID.
   for(let lane=1;lane<=6;lane++){
     const raw=Array.isArray(race.rows)?race.rows.find(x=>Number(x['枠'])===lane):null;
     const match=raw?laneMap.get(String(raw['登録番号']||'')):null;
     const fallback=roster[lane-1]||{};
     const row=match||fallback;
     const number=row['モーターNo.']??'';
     const registration=String(raw?.['登録番号']||row['登録番号']||'');
     normalized.push({lane,racer:row['選手名']||raw?.['選手名']||'未取得',registration,no:number,
       liveTop2:row['モーター2連率']??''});
   }
   return normalized;
 }
 function viewHtml(race){
   const day=String(race.day||'');
   const asOf=status.meta?.snapshot_at||'',snapshotDay=dateValue(asOf.slice(0,10));
   const older=Boolean(snapshotDay&&day&&snapshotDay>day);
   const roster=rosterData(race),available=roster.filter(x=>motorKey(race.venue,x.no)).length;
   let h='<div class="panel motor-panel"><div class="section-head"><div><h2>モーターAI評価 / 6艇比較</h2><p>'+toText((race.venueName||'')+' '+(race.race||'')+'R')+' ・データベース時点 '+toText(stamp(asOf))+'</p></div><span class="pill">参考評価</span></div>';
   h+='<div class="motor-intro"><strong>伸び・出足・回り足・行き足</strong><p>競艇AIデータベースで評価済みのS〜Dランクを、見やすい印に変換しています。レース直前の足色を保証するものではありません。</p></div>';
   if(older)h+='<p class="motor-warning">選択レースの日付より後に更新された評価です。過去レースの事前予想として使用できません。</p>';
   if(!available)h+='<p class="deadline-empty">このレースの6艇モーター番号を取得できていません。出走表の保存・配信を確認してください。</p>';
   else{
     h+='<div class="motor-scroll"><table class="motor-table"><thead><tr><th>艇</th><th>選手 / モーター</th><th>総合</th>'+FIELDS.map(f=>'<th>'+f[0]+'</th>').join('')+'<th>2連率</th></tr></thead><tbody>';
     for(const b of roster){
       const motor=pick(status.motors,race.venue,b.no);
       const motorFrom=dateValue(motor?.start),raceDay=String(day||'');
       const wrongCycle=Boolean(motorFrom&&raceDay&&motorFrom>raceDay);
       const valid=Boolean(motor&&!wrongCycle);
       const grade=v=>valid?badge(v):badge(null);
       h+='<tr><td><span class="boat boat-'+b.lane+'">'+b.lane+'</span></td><td><strong>'+toText(b.racer)+'</strong><small>No.'+toText(b.no||'—')+'</small></td>';
       h+='<td>'+grade(motor?.grade)+'</td>';
       h+=FIELDS.map(([_,field])=>'<td>'+grade(motor?.[field])+'</td>').join('');
       const top2=valid?motor?.top2:null;
       h+='<td class="motor-number">'+(Number.isFinite(Number(top2))&&top2!==''&&top2!=null?Number(top2).toFixed(1)+'%':'—')+'</td></tr>';
       if(wrongCycle)h+='<tr class="motor-note-row"><td colspan="8">モーター交換日が対象レースより後なので、この艇の評価は非表示</td></tr>';
     }
     h+='</tbody></table></div>';
   }
   const legend=Object.entries(MARKS).map(([k,v])=>'<span><b>'+toText(v.mark)+'</b> '+k+' ('+toText(v.label)+')</span>').join('');
   h+='<div class="motor-legend">'+legend+'<span><b>—</b> 未取得</span></div>';
   h+='<p class="motor-note">評価元：競艇AI データベース／モーターデータ。現在のスナップショットは事前固定原本ではありません。選手や整備によって状態が変わるため、展示と公式の直前情報を確認してください。</p></div>';
   return h;
 }
 function render(){
   if(!status.enabled)return;
   const target=document.getElementById('view-motor');
   if(!target)return;
   const race=getRace();
   if(!status.motors){
     target.innerHTML='<section class="panel"><h2>モーターAI評価</h2><p class="empty">'+toText(status.error||'モーターデータを読み込み中…')+'</p></section>';
     return;
   }
   target.innerHTML=viewHtml(race);
 }
 async function load(force=false){
   status.enabled=true;
   if(status.motors&&!force&&Date.now()-status.loadedAt<300000){render();return;}
   if(status.promise){await status.promise;render();return;}
   render();
   status.promise=(async()=>{
     try{
       const meta=await readMeta(true);
       if(!meta)throw new Error('評価元の更新情報が未取得です');
       const version=encodeURIComponent(meta.snapshot_at);
       const motors=await getJson(ROOT+'motors.json?version='+version,18000);
       if(!motors||typeof motors!=='object'||Array.isArray(motors)||Object.keys(motors).length!==meta.motor_count)
         throw new Error('評価データの件数が合いません');
       status.motors=motors;status.loadedAt=Date.now();status.error='';
     }catch(e){status.error='AIモーター評価を取得できませんでした。通信状況を確認して再度更新してください。';}
     finally{status.promise=null;}
   })();
   await status.promise;render();
 }
 function start({race,roster}){
   getRace=race;requestRoster=roster;
 }
 async function show(){
   status.enabled=true;
   render();
   await Promise.allSettled([load(),requestRoster()]);
   render();
 }
 root.MotorPanel={start,show,load,render,readMeta,gradeMark,pick,motorKey,rosterData};
})(window);
