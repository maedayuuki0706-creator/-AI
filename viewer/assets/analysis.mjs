import {VENUES,NAMES,SHARDS,mergeHistory,filterHistory,summarizeHistory,rankPlayers,dayLabel,yen,rate,finite} from './analysis-core.mjs';
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
const state={history:null,filtered:[],hLimit:100,playerPayload:null,players:[],pLimit:50,historyError:'',playerError:''};
function stat(label,value,sub=''){
 const div=e('div','metric'),b=e('b','',value);div.append(e('span','',label),b,e('small','',sub));return div;
}
function cell(tr,value,cls=''){const td=e('td',cls,value);tr.append(td);return td;}
function showHistory(){
 if(!state.history)return;
 const from=$('h-from').value,to=$('h-to').value;if(from&&to&&from>to){text('history-status','開始日が終了日より後です。期間を修正してください。');return;}
 const options={from,to,venue:$('h-venue').value,first:$('h-first').value,minPayout:$('h-min').value,manshu:$('h-manshu').checked};
 state.filtered=filterHistory(state.history.rows,options);state.hLimit=100;
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
  const row=e('div','bar-row');row.append(e('span','lane lane-'+(i+1),String(i+1)),bar,e('span','bar-number',n+'件 / '+rate(share)));chart.append(row);
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
async function loadHistory(){
 text('history-status','公式結果を読み込み中…');
 const results=await Promise.allSettled(SHARDS.map(s=>json('/data/history/'+s+'.json')));
 const ok=results.filter(r=>r.status==='fulfilled').map(r=>r.value);
 const failed=results.filter(r=>r.status==='rejected').length;
 if(!ok.length){text('history-status','結果データを取得できませんでした。通信を確認して再読み込みしてください。');text('history-meta','データが取得できなかったため、割合は算出しません。');return;}
 try{state.history=mergeHistory(ok);state.historyError=failed?String(failed)+'分割ファイル欠測':'';
 const h=state.history;
 text('history-meta',`公式結果の保存済み ${dayLabel(h.from)}〜${dayLabel(h.to)} ／ 検索対象 ${h.rows.length.toLocaleString('ja-JP')}R。元記録 ${h.source}件、除外 ${h.skipped}件、重複・不正 ${h.rejected}件。全開催・全結果の網羅ではありません。${failed?' 一部ファイルが読み込めないため部分集計です。':''}`);
 $('h-from').min=asDate(h.from);$('h-from').max=asDate(h.to);
 $('h-to').min=asDate(h.from);$('h-to').max=asDate(h.to);
 $('h-from').value=asDate(h.from);$('h-to').value=asDate(h.to);
 showHistory();
 }catch(err){text('history-status','履歴の形式を確認できませんでした：'+err.message);}
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
function showDetail(p){
 const box=$('player-detail');box.replaceChildren();
 box.append(e('p','eyebrow','RACER PROFILE'),e('h3','',p.name+'（'+p.id+'）'),
  e('p','profile-meta',(p.class||'級別未取得')+' / '+(p.branch||'支部未取得')+' / 全国勝率 '+(finite(p.win)===null?'—':Number(p.win).toFixed(2))+' / 平均ST '+(finite(p.avg_st)===null?'—':Number(p.avg_st).toFixed(2))));
 box.append(e('h4','','コース別1着率'));
 const grid=e('div','profile-grid');
 for(let i=0;i<6;i++){const v=Array.isArray(p.course_win)?p.course_win[i]:null;grid.append(stat((i+1)+'コース',safePct(v)));}box.append(grid);
 box.append(e('h4','','決まり手率（収録DBの参考値）'));
 const grid2=e('div','profile-grid');
 for(const [key,label] of [['escape','逃げ'],['sashi','差し'],['makuri','まくり'],['makurisashi','まくり差し']])grid2.append(stat(label,safePct(p[key])));
 box.append(grid2,e('p','note','数値は保存済み選手DBの値です。当地勝率・今節ST・コース別出走数・決まり手別の対象期間は収録されていません。'));
 box.hidden=false;box.focus({preventScroll:true});box.scrollIntoView({behavior:'smooth',block:'nearest'});
}
async function loadPlayers(){
 text('player-status','選手データを読み込み中…');
 try{const payload=await json('/data/public/players.json');
 if(!payload?.data)throw new Error('選手データの形式が不正');
 state.playerPayload=payload;
 const branches=[...new Set(Object.values(payload.data).map(p=>p?.branch).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'ja'));
 for(const name of branches){const option=e('option','',name);option.value=name;$('p-branch').append(option);}
 text('player-meta','収録時刻：'+(payload.snapshot_at||'未収録')+'。コース別1着率と決まり手は保存スナップショット由来。対象期間・分母は未収録、当地勝率・今節STも未収録のため推測表示なし。');
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
$('history-form').addEventListener('submit',event=>{event.preventDefault();if(state.history)showHistory();else loadHistory();});
$('history-more').addEventListener('click',()=>{state.hLimit+=100;drawHistoryRows();});
$('player-form').addEventListener('submit',event=>{event.preventDefault();if(state.playerPayload)showPlayers();else loadPlayers();});
$('player-more').addEventListener('click',()=>{state.pLimit+=50;drawPlayerRows();});
loadHistory();
