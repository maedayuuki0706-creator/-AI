const cache=new Map();
const decode=s=>Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
export async function authorize(request,env,fetcher=fetch){
 if(!/^[a-z0-9-]+$/.test(env.ACCESS_TEAM||'')||!env.ACCESS_AUD||!env.ALLOWED_EMAILS)return false;
 const token=request.headers.get('Cf-Access-Jwt-Assertion');
 if(!token||token.length>16384)return false;
 try{
  const [h,p,s,...rest]=token.split('.');if(rest.length||!s)return false;
  const header=JSON.parse(new TextDecoder().decode(decode(h)));const claims=JSON.parse(new TextDecoder().decode(decode(p)));
  const issuer=`https://${env.ACCESS_TEAM}.cloudflareaccess.com`;const now=Date.now()/1000;
  if(header.alg!=='RS256'||!header.kid||claims.iss!==issuer||!Array.isArray(claims.aud)||!claims.aud.includes(env.ACCESS_AUD)||!Number.isFinite(claims.exp)||claims.exp<=now||!Number.isFinite(claims.iat)||claims.iat>now+30||(claims.nbf!==undefined&&(!Number.isFinite(claims.nbf)||claims.nbf>now))||!claims.sub||typeof claims.email!=='string')return false;
  if(!env.ALLOWED_EMAILS.split(',').map(x=>x.trim().toLowerCase()).filter(Boolean).includes(claims.email.toLowerCase()))return false;
  let keys=cache.get(issuer);
  if(!keys||keys.expires<Date.now()){
   const r=await fetcher(issuer+'/cdn-cgi/access/certs',{signal:AbortSignal.timeout(5000)});if(!r.ok)return false;
   const data=await r.json();if(!Array.isArray(data.keys))return false;
   keys={keys:data.keys,expires:Date.now()+300000};cache.set(issuer,keys);
  }
  const jwk=keys.keys.find(k=>k.kid===header.kid&&k.kty==='RSA');if(!jwk)return false;
  const key=await crypto.subtle.importKey('jwk',jwk,{name:'RSASSA-PKCS1-v1_5',hash:'SHA-256'},false,['verify']);
  return await crypto.subtle.verify('RSASSA-PKCS1-v1_5',key,decode(s),new TextEncoder().encode(h+'.'+p));
 }catch{return false;}
}
