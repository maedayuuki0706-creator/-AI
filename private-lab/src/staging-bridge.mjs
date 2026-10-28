// Staging bridge deployed to the existing boat-private-lab Worker on 2026-10-27.
// This file is not the final R2-backed Worker. It proxies ONLY publicly committed
// static UI assets; no private research data is embedded. Cloudflare Access and
// a verified owner Access JWT are required before serving any route.
// Runtime bindings ACCESS_TEAM, ACCESS_AUD, ALLOWED_EMAILS must be provisioned
// privately through Cloudflare. Do not put their values into this public repo.

const JWKS = new Map();
const HEADERS={"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer","X-Frame-Options":"DENY","Content-Security-Policy":"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'","Strict-Transport-Security":"max-age=31536000","X-Robots-Tag":"noindex,nofollow"};
const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{...HEADERS,"Content-Type":"application/json; charset=utf-8"}});
function b64(s){return Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')),v=>v.charCodeAt(0));}
async function permitted(req,env){
 const jwt=req.headers.get("Cf-Access-Jwt-Assertion");if(!jwt||jwt.length>12000)return false;
 try{
  const parts=jwt.split(".");if(parts.length!==3)return false;
  const h=JSON.parse(new TextDecoder().decode(b64(parts[0])));
  const p=JSON.parse(new TextDecoder().decode(b64(parts[1])));
  const issuer="https://"+env.ACCESS_TEAM+".cloudflareaccess.com", now=Date.now()/1000;
  if(h.alg!=="RS256"||!h.kid||p.iss!==issuer||!Array.isArray(p.aud)||!p.aud.includes(env.ACCESS_AUD)||p.exp<=now||!Number.isFinite(p.exp)||!p.sub||typeof p.email!=="string"||!env.ALLOWED_EMAILS.split(",").map(s=>s.trim().toLowerCase()).includes(p.email.toLowerCase()))return false;
  let cert=JWKS.get(issuer);
  if(!cert||cert.time<Date.now()){const r=await fetch(issuer+"/cdn-cgi/access/certs");if(!r.ok)return false;const j=await r.json();if(!Array.isArray(j.keys))return false;cert={keys:j.keys,time:Date.now()+300000};JWKS.set(issuer,cert);}
  const key=cert.keys.find(k=>k.kid===h.kid&&k.kty==="RSA");if(!key)return false;
  const cryptoKey=await crypto.subtle.importKey("jwk",key,{name:"RSASSA-PKCS1-v1_5",hash:"SHA-256"},false,["verify"]);
  return await crypto.subtle.verify("RSASSA-PKCS1-v1_5",cryptoKey,b64(parts[2]),new TextEncoder().encode(parts[0]+"."+parts[1]));
 }catch{return false;}
}
const ORIGIN="https://raw.githubusercontent.com/maedayuuki0706-creator/-AI/94819d00d01dcb24ce30fec0776df353052ddfda/private-lab/public/";
const types={"/":"text/html; charset=utf-8","/index.html":"text/html; charset=utf-8","/style.css":"text/css; charset=utf-8","/app.js":"text/javascript; charset=utf-8"};
const note="Cloudflare R2は未有効化のため研究データを接続していません。データ接続まで数値は未取得として表示します。";
export default {async fetch(req,env){
 if(!await permitted(req,env))return json({error:"本人認証が必要です"},403);
 if(req.method!=="GET"&&req.method!=="HEAD")return json({error:"Method not allowed"},405);
 const url=new URL(req.url),p=url.pathname;
 if(p.startsWith("/api/")){
  if(p==="/api/status")return json({from:"未接続",to:"未接続",races:null,entries:null,players:null,preview_rows:null,source:"非公開R2未接続",excluded:null,motor_rows:null,built_at:"未接続",missing:[note,"AIの的中率・回収率は未算出。公式結果は未接続。"],source_sha256:"未接続"});
  if(p==="/api/ai")return json({rows:[],note});
  if(["/api/race","/api/player","/api/archive"].includes(p))return json({error:note},404);
  return json({rows:[],next:null,note,phase:"未取得",tide:null});
 }
 const kind=types[p];if(!kind)return new Response("Not found",{status:404,headers:HEADERS});
 const file=p==="/"? "index.html":p.slice(1);
 try{const r=await fetch(ORIGIN+file,{headers:{"User-Agent":"BoatPrivateLab-ReadOnly-Staging"}});
 if(!r.ok)return json({error:"静的画面の取得に失敗しました"},503);
 return new Response(req.method==="HEAD"?null:r.body,{status:200,headers:{...HEADERS,"Content-Type":kind}});
 }catch{return json({error:"静的画面の取得に失敗しました"},503);}
}};
