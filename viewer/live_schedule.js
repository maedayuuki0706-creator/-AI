/* Read-only deadline board. No predictions, Sheets writes, delivery or private credentials. */
(function (root) {
  'use strict';
  const RAW='https://raw.githubusercontent.com/maedayuuki0706-creator/-AI/main/data/race_cards/';
  const FEED='https://boat-sheet-feed.onrender.com/schedule.json';
  const fmt=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'});
  const clock=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'});
  const isDay=s=>/^20\d{6}$/.test(String(s||''));
  const dayKey=s=>String(s||'').replace(/-/g,'');
  const today=()=>fmt.format(new Date()).replace(/-/g,'');
  const NAME=new Map();
  let config=null, saved=[], activeDay='', source='', captured='', error='', partial=false, loading=false;
  let requested=0, lastChecked=0, lastAutoKey='', expanded=false, requestAbort=null;
  function epoch(day,hhmm) {
    if(!isDay(day)||!/^([01]\d|2[0-3]):[0-5]\d$/.test(String(hhmm||'')))return NaN;
    const s=day.slice(0,4)+'-'+day.slice(4,6)+'-'+day.slice(6,8)+'T'+hhmm+':00+09:00';
    const ms=Date.parse(s);
    return Number.isFinite(ms)?ms:NaN;
  }
  function validRows(day,rows) {
    if(!Array.isArray(rows))throw new Error('レース配列がありません');
    const seen=new Set(), output=[];
    for(const row of rows){
      const jcd=String(row.jcd||'').padStart(2,'0'), rno=Number(row.rno);
      const time=row.deadline;
      if(!NAME.has(jcd)||!Number.isInteger(rno)||rno<1||rno>12||!Number.isFinite(epoch(day,time)))continue;
      const key=day+'_'+jcd+'_'+String(rno).padStart(2,'0');
      if(seen.has(key))continue;
      seen.add(key);output.push({key,jcd,rno,deadline:time,at:epoch(day,time)});
    }
    return output.sort((a,b)=>a.at-b.at||a.jcd.localeCompare(b.jcd)||a.rno-b.rno);
  }
  function fromCard(day,payload) {
    if(!payload||dayKey(payload.day)!==day||payload.complete!==true||!payload.races)throw new Error('公式日程が未確定');
    return {items:validRows(day,Object.values(payload.races)),source:'GitHub公式締切表',captured:payload.checked_at||'',partial:false};
  }
  function fromFeed(day,payload) {
    if(!payload||dayKey(payload.day)!==day||!Array.isArray(payload.races))throw new Error('日程レスポンス不一致');
    return {items:validRows(day,payload.races),source:'公式フィード',captured:payload.generated_at||'',partial:Boolean(payload.partial)};
  }
  async function json(url,timeout=12000) {
    const controller=new AbortController();requestAbort=controller;
    const timer=setTimeout(()=>controller.abort(),timeout);
    try{
      const response=await fetch(url,{signal:controller.signal,cache:'no-store'});
      if(!response.ok)throw new Error('HTTP '+response.status);
      return await response.json();
    }finally{clearTimeout(timer);if(requestAbort===controller)requestAbort=null;}
  }
  function upcoming(rows,now=Date.now()) {return rows.filter(x=>x.at>now);}
  function left(ms) {
    const m=Math.ceil(ms/60000);
    return m<=1?'締切間近':m<60?'あと'+m+'分':'あと'+Math.floor(m/60)+'時間'+String(m%60).padStart(2,'0')+'分';
  }
  function currentDay(){return dayKey(config.getDay());}
  function statusText(msg) {
    const el=document.getElementById('deadline-status');
    if(el)el.textContent=msg;
  }
  function render(){
    if(!config)return;
    const day=currentDay(), el=document.getElementById('deadline-items'), headline=document.getElementById('deadline-summary');
    if(!el||!headline)return;
    const valid=day===activeDay, all=valid?upcoming(saved):[];
    const todayDay=today(), isPast=day<todayDay, isToday=day===todayDay;
    headline.textContent=valid?('締切前 '+all.length+'R / 取得 '+saved.length+'R'):'締切データ取得待ち';
    const display=all.length?all:[];
    const existingScroll=el.scrollTop;
    if(!valid){
      el.innerHTML='<p class="deadline-empty">'+(loading?'開催・締切データを確認中…':'締切情報を確認できません。公式サイトから開催日程をご確認ください。')+'</p>';
    }else if(!display.length){
      el.innerHTML='<p class="deadline-empty">'+(partial?'締切情報に欠測があります。未取得のレースは表示していません。':isPast?'選択日は終了しています。':isToday?'本日の締切前レースはありません。開催終了または非開催です。':'開催予定の締切レースが確認できません。')+'</p>';
    }else{
      el.innerHTML=display.map((race,i)=>'<button type="button" class="deadline-item'+(i===0?' next':'')+'" data-key="'+race.key+'" aria-label="'+NAME.get(race.jcd)+' '+race.rno+'レース 締切'+race.deadline+'"><span class="deadline-when">'+race.deadline+'</span><span class="deadline-venue">'+NAME.get(race.jcd)+' <b>'+race.rno+'R</b></span><span class="deadline-count">'+(isToday?left(race.at-Date.now()):'開催予定')+'</span></button>').join('');
    }
    el.scrollTop=existingScroll;
    const meta=document.getElementById('deadline-updated');
    if(meta)meta.textContent=valid?(source+' / '+(captured?clock.format(new Date(captured))+'更新':'日時未確認')+(partial?' / 一部取得不可':'') ):'公開情報を確認中';
    const follow=document.getElementById('deadline-follow');
    if(follow)follow.hidden=!valid||!all.length||config.isAutoFollowing();
    if(valid&&!error){
      statusText(all.length?'締切順に自動更新中（約2分間隔で日程再確認）':(partial?'一部締切情報が未取得です':'本日の締切前レースなし'));
    }else if(error){
      statusText('締切表を取得できませんでした。手動の場・R選択は使えます。');
    }
  }
  function autoPick(){
    if(!config||!config.isAutoFollowing()||activeDay!==currentDay())return;
    const first=upcoming(saved)[0];
    if(!first||lastAutoKey===first.key)return;
    lastAutoKey=first.key;config.onPick(first.jcd,first.rno,true);
  }
  async function load(day,force=false) {
    if(!config)return;
    const normalized=dayKey(day);
    if(!isDay(normalized))return;
    if(!force&&lastChecked&&activeDay===normalized&&Date.now()-lastChecked<120000)return;
    const id=++requested;
    if(requestAbort)requestAbort.abort();
    loading=true;error='';statusText('締切順のレースを取得中…');
    render();
    const tag='?v='+Math.floor(Date.now()/120000);
    let fetched=null, problems=[];
    try{fetched=fromCard(normalized,await json(RAW+normalized+'.json'+tag,9000));}
    catch(e){problems.push('保存済み日程: '+String(e.message||e));}
    if(!fetched){
      try{fetched=fromFeed(normalized,await json(FEED+'?date='+normalized,30000));}
      catch(e){problems.push('公式フィード: '+String(e.message||e));}
    }
    if(id!==requested||currentDay()!==normalized)return;
    loading=false;lastChecked=Date.now();
    if(fetched){
      saved=fetched.items;activeDay=normalized;source=fetched.source;captured=fetched.captured;partial=fetched.partial;error='';
      autoPick();
    }else{
      saved=[];activeDay='';source='';captured='';partial=false;error=problems.join(' / ');
    }
    render();
  }
  function tick(){
    if(!config)return;
    if(config.autoDate&&config.autoDate()&&currentDay()!==today()){
      config.onNewDay(today());lastAutoKey='';load(currentDay(),true);return;
    }
    autoPick();render();
    if(document.visibilityState!=='hidden'&&Date.now()-lastChecked>=120000&&!loading)load(currentDay(),true);
  }
  function start(options){
    if(config)return;
    config=options;
    for(const pair of options.venues)NAME.set(pair[0],pair[1]);
    const el=document.getElementById('deadline-items');
    if(el)el.addEventListener('click',event=>{
      const button=event.target.closest('button[data-key]');if(!button)return;
      const found=saved.find(r=>r.key===button.dataset.key);if(!found||found.at<=Date.now())return;
      options.onPick(found.jcd,found.rno,false);render();
    });
    const follow=document.getElementById('deadline-follow');
    if(follow)follow.addEventListener('click',()=>{options.onFollow();lastAutoKey='';autoPick();render();});
    document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')load(currentDay(),true);});
    setInterval(tick,20000);
    load(currentDay(),true);
  }
  root.RaceSchedule={start,load,tick,validRows,epoch,upcoming,fromCard,fromFeed};
})(window);
