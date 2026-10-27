import {authorize} from './auth.mjs';
import {r2Query} from './r2-api.mjs';
const headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",'Strict-Transport-Security':'max-age=31536000','X-Robots-Tag':'noindex, nofollow'};
const json=(x,status=200)=>new Response(JSON.stringify(x),{status,headers:{...headers,'Content-Type':'application/json; charset=utf-8'}});
function value(p,k,re){const v=p.get(k)||'';if(v&&!re.test(v))throw Error('invalid '+k);return v;}
async function all(db,sql,args=[]){return (await db.prepare(sql).bind(...args).all()).results;}
export async function api(request,env){
 if(env.DATA_BACKEND==='r2'){const result=await r2Query(request,env);if(result!==undefined)return json(result,result?.error?404:200);}
 const u=new URL(request.url),p=u.searchParams,path=u.pathname;
 const venue=value(p,'venue',/^(0[1-9]|1[0-9]|2[0-4])$/);
 const summary=async kind=>{const r=await env.DB.prepare('SELECT json FROM summaries WHERE kind=?').bind(kind).first();return r?JSON.parse(r.json):null;};
 if(path==='/api/status')return json(await summary('manifest'));
 if(path==='/api/races'){
  const from=value(p,'from',/^\d{4}-\d{2}-\d{2}$/),to=value(p,'to',/^\d{4}-\d{2}-\d{2}$/),after=value(p,'after',/^[\d:-]{1,40}$/);let w=['1=1'],a=[];
  for(const [col,v,op] of [['venue',venue,'='],['day',from,'>='],['day',to,'<=']])if(v){w.push(`${col}${op}?`);a.push(v);}
  if(p.get('high')==='1')w.push('payout>=10000');
  if(after){const [day,id]=after.split(':');if(!day||!id)throw Error('invalid cursor');w.push('(day,id)<(?,?)');a.push(day,id);}
  const rows=await all(env.DB,`SELECT id,day,venue,rno,result,payout,method,wind,wave,phase FROM races WHERE ${w.join(' AND ')} ORDER BY day DESC,id DESC LIMIT 31`,a);
  const more=rows.length>30;const data=rows.slice(0,30);return json({rows:data,next:more?data.at(-1).day+':'+data.at(-1).id:null});
 }
 if(path==='/api/race'){
  const id=value(p,'id',/^\d{12}$/);if(!id)throw Error('id required');
  const race=await env.DB.prepare('SELECT * FROM races WHERE id=?').bind(id).first();if(!race)return json({error:'未取得'},404);
  return json({race,entries:await all(env.DB,'SELECT * FROM entries WHERE race_id=? ORDER BY boat',[id])});
 }
 if(path==='/api/players'){
  const q=(p.get('q')||'').replace(/[ 　]/g,'').slice(0,40),after=value(p,'after',/^\d{4}$/);
  const rows=await all(env.DB,"SELECT * FROM players WHERE (id=? OR name_key LIKE ? ESCAPE '\\') AND id>? ORDER BY id LIMIT 31",[q,'%'+q.replace(/[\\%_]/g,'\\$&')+'%',after]);
  return json({rows:rows.slice(0,30),next:rows.length>30?rows[29].id:null});
 }
 if(path==='/api/player'){
  const id=value(p,'id',/^\d{4}$/);if(!id)throw Error('id required');const from=value(p,'from',/^\d{4}-\d{2}-\d{2}$/),to=value(p,'to',/^\d{4}-\d{2}-\d{2}$/);
  let w=['e.racer_id=?'],a=[id];for(const [col,v,op] of [['r.venue',venue,'='],['r.day',from,'>='],['r.day',to,'<=']])if(v){w.push(`${col}${op}?`);a.push(v);}
  const player=await env.DB.prepare('SELECT * FROM players WHERE id=?').bind(id).first();if(!player)return json({error:'未取得'},404);
  const stats={};for(const col of ['boat','course'])stats[col]=await all(env.DB,`SELECT e.${col} lane,count(*) starts,sum(rank=1) first,sum(rank<=2) top2,sum(rank<=3) top3,avg(st) avg_st FROM entries e JOIN races r ON r.id=e.race_id WHERE ${w.join(' AND ')} GROUP BY e.${col}`,a);
  return json({player,stats,scope:{venue:venue||'全国',from,to},note:'公式結果の収録範囲内の1着率・連対率。公式得点率の「勝率」ではありません。'});
 }
 if(path==='/api/water'||path==='/api/manshu'){
  const kind=path.endsWith('water')?'water':'manshu';let data=(await summary(kind))||[];if(venue)data=data.filter(x=>x.venue===venue);
  const wind=value(p,'wind',/^\d{1,2}$/);if(kind==='water'&&wind)data=data.filter(x=>x.wind===Number(wind));
  // Summaries are bounded; group water across direction/wave in the UI only after server filtering.
  return json({rows:data,phase:'post',tide:null});
 }
 if(path==='/api/previews')return json({rows:await all(env.DB,`SELECT * FROM previews ${venue?'WHERE venue=?':''} ORDER BY day DESC,id DESC LIMIT 30`,venue?[venue]:[]),phase:'pre'});
 if(path==='/api/motors'){
  const motor=value(p,'motor',/^\d{1,3}$/);let w=[],a=[];if(venue){w.push('venue=?');a.push(venue);}if(motor){w.push('motor=?');a.push(motor);}
  if(!venue)return json({rows:[],note:'場を指定してください。モーター番号は場・交換期で区別します。'});
  return json({rows:await all(env.DB,`SELECT * FROM motors WHERE ${w.join(' AND ')} ORDER BY day DESC,motor LIMIT 60`,a),note:'第三者の期別累計スナップショット。時点保証なし。日別値は合算しません。'});
 }
 if(path==='/api/ai')return json({rows:[],note:'未取得：締切前予想原本と購入点数・金額・確定払戻を照合してから成績を表示します。'});
 if(path==='/api/archive'){
  const id=value(p,'id',/^\d{12}$/);if(!id)throw Error('id required');
  if(!env.ARCHIVE)return json({error:'未取得'},404);
  const obj=await env.ARCHIVE.get(`${env.DETAIL_PREFIX||"details"}/${id}.json`);if(!obj)return json({error:'未取得'},404);
  return new Response(obj.body,{headers:{...headers,'Content-Type':'application/json; charset=utf-8'}});
 }
 return json({error:'Not found'},404);
}
export default {async fetch(request,env){
 try{
  if(!await authorize(request,env))return json({error:'認証が必要です。許可されたアカウントでログインしてください。'},403);
  if(!['GET','HEAD'].includes(request.method))return json({error:'Method not allowed'},405);
  if(new URL(request.url).pathname.startsWith('/api/'))return await api(request,env);
  const res=await env.ASSETS.fetch(request);const h=new Headers(res.headers);for(const [k,v] of Object.entries(headers))h.set(k,v);return new Response(res.body,{status:res.status,headers:h});
 }catch(e){return json({error:e.message?.startsWith('invalid')||e.message?.endsWith('required')?'検索条件が正しくありません':'データを取得できません。再試行してください。'},e.message?.startsWith('invalid')||e.message?.endsWith('required')?400:503);}
}};
