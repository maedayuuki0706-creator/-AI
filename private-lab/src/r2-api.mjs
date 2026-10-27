// Equivalent read-only API over offline indexes. No D1 bootstrap quota required.
// All callers must pass through the Worker authorization gate.
async function read(env,key){const r=await env.ARCHIVE.get((env.DATA_PREFIX||'query')+'/'+key);if(!r)return null;return r.json?await r.json():JSON.parse(await new Response(r.body).text());}
function param(p,key,re){const v=p.get(key)||'';if(v&&!re.test(v))throw Error('invalid '+key);return v;}
function stats(entries,key){const m=new Map();for(const e of entries){if(!m.has(e[key]))m.set(e[key],{lane:e[key],starts:0,first:0,top2:0,top3:0,st_sum:0,st_n:0});const r=m.get(e[key]);r.starts++;r.first+=e.rank===1?1:0;r.top2+=e.rank<=2?1:0;r.top3+=e.rank<=3?1:0;if(e.st!==null){r.st_sum+=e.st;r.st_n++;}}return [...m.values()].sort((a,b)=>a.lane-b.lane).map(({st_sum,st_n,...r})=>({...r,avg_st:st_n?st_sum/st_n:null}));}
export async function r2Query(request,env){const u=new URL(request.url),p=u.searchParams,path=u.pathname;const venue=param(p,'venue',/^(0[1-9]|1[0-9]|2[0-4])$/);
 if(path==='/api/status'){const m=await read(env,'summaries/manifest.json');if(!m)throw Error('missing manifest');return m;}
 if(path==='/api/races'){
  const from=param(p,'from',/^\d{4}-\d{2}-\d{2}$/),to=param(p,'to',/^\d{4}-\d{2}-\d{2}$/),cursor=param(p,'after',/^\d{4}-\d{2}-\d{2}:\d{12}$/);const high=p.get('high')==='1';const [afterDay,afterId]=(cursor||':').split(':');let rows=[];
  const index=await read(env,'races/index.json');if(!index)throw Error('missing index');
  // At most 8 daily objects per request, returning a continuation even for sparse matches.
  let scanned=0,continuation=null;
  const selected=index.filter(x=>(!from||x.day>=from)&&(!to||x.day<=to)&&(!afterDay||x.day<=afterDay)&&(!venue||x.venues.includes(venue)));
  for(let i=0;i<selected.length;i++){
   const chunk=await read(env,'races/'+selected[i].day+'.json');if(!chunk)throw Error('missing shard');scanned++;
   rows.push(...chunk.filter(r=>(!venue||r.venue===venue)&&(!from||r.day>=from)&&(!to||r.day<=to)&&(!high||r.payout>=10000)&&(!afterDay||r.day<afterDay||r.day===afterDay&&r.id<afterId)));
   if(rows.length>30)break;
   if(scanned===8&&i<selected.length-1){continuation=selected[i].day+':'+selected[i].day.replaceAll('-','')+'0000';break;}
  }
  return {rows:rows.slice(0,30),next:rows.length>30?rows[29].day+':'+rows[29].id:continuation};
 }
 if(path==='/api/race'){const id=param(p,'id',/^\d{12}$/);if(!id)throw Error('id required');const day=id.slice(0,4)+'-'+id.slice(4,6)+'-'+id.slice(6,8);return (await read(env,'days/'+day+'.json'))?.[id]||{error:'未取得'};}
 if(path==='/api/players'){const q=(p.get('q')||'').replace(/[ 　]/g,'').slice(0,40),after=param(p,'after',/^\d{4}$/);const list=await read(env,'players/index.json');if(!list)throw Error('missing index');const rows=list.filter(r=>r.id>after&&(r.id===q||r.name_key.includes(q))).slice(0,31);return {rows:rows.slice(0,30),next:rows.length>30?rows[29].id:null};}
 if(path==='/api/player'){
  const id=param(p,'id',/^\d{4}$/);if(!id)throw Error('id required');const from=param(p,'from',/^\d{4}-\d{2}-\d{2}$/),to=param(p,'to',/^\d{4}-\d{2}-\d{2}$/);const data=await read(env,'players/'+id+'.json');if(!data)return {error:'未取得'};
  const entries=data.entries.filter(r=>(!venue||r.venue===venue)&&(!from||r.day>=from)&&(!to||r.day<=to));return {player:data.player,stats:{boat:stats(entries,'boat'),course:stats(entries,'course')},scope:{venue:venue||'全国',from,to},note:'公式結果の収録範囲内の1着率・連対率。公式得点率の「勝率」ではありません。'};
 }
 if(path==='/api/water'||path==='/api/manshu'){
  const kind=path.endsWith('water')?'water':'manshu';let rows=await read(env,'summaries/'+kind+(venue?'-'+venue:'')+'.json');if(!rows)throw Error('missing summary');const wind=param(p,'wind',/^\d{1,2}$/);if(kind==='water'&&wind)rows=rows.filter(r=>r.wind===Number(wind));return {rows,phase:'post',tide:null};
 }
 if(path==='/api/previews'){const rows=await read(env,'previews/'+(venue||'all')+'.json');if(!rows)throw Error('missing preview');return {rows:rows.slice(0,30),phase:'pre'};}
 if(path==='/api/motors'){const motor=param(p,'motor',/^\d{1,3}$/);if(!venue)return {rows:[],note:'場を指定してください。モーター番号は場・交換期で区別します。'};const rows=await read(env,'motors/'+venue+'.json');if(!rows)throw Error('missing motors');return {rows:rows.filter(r=>!motor||r.motor===motor).slice(0,60),note:'第三者の期別累計スナップショット。時点保証なし。日別値は合算しません。'};}
 return undefined;
}
