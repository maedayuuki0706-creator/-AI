// Remote unauthenticated smoke test. No credentials or authenticated cookies allowed.
// --require-access-gateway additionally demands a real Cloudflare Access login redirect,
// instead of accepting only the Worker's fail-closed 403 response.
const supplied=process.argv[2], requireAccess=process.argv.includes('--require-access-gateway');
if(!supplied)throw Error('HTTPS origin required');
const origin=new URL(supplied);
if(origin.protocol!=='https:'||origin.username||origin.password||origin.pathname!=='/'||origin.search||origin.hash)
 throw Error('Expected HTTPS origin without path, credentials or query');
const paths=['/','/index.html','/app.js','/style.css','/api/status','/api/races',
 '/api/players','/api/archive?id=202610011401','/data/search.sqlite','/not-a-real-route'];
let accessCount=0;
for(const path of paths){
 let response;
 try{
  response=await fetch(new URL(path,origin),{
   redirect:'manual',
   headers:{'Cf-Access-Authenticated-User-Email':'forged@example.test'},
   signal:AbortSignal.timeout(15000)
  });
 }catch(err){
  console.error(path,'NETWORK_OR_TLS_ERROR',err?.message||String(err));process.exitCode=1;continue;
 }
 const location=response.headers.get('location');
 let redirect=false;
 if(location&&[301,302,303,307,308].includes(response.status)){
  const u=new URL(location,origin);
  redirect=u.protocol==='https:'&&/^[a-z0-9-]+\.cloudflareaccess\.com$/i.test(u.hostname);
 }
 if(redirect)accessCount++;
 // A missing page (404), a site at a different host, or an upstream 5xx is NOT proof of privacy.
 const denied=redirect||(!requireAccess&&[401,403].includes(response.status));
 console.log(path,response.status,redirect?'ACCESS_LOGIN':denied?'DENIED':'FAIL');
 if(!denied)process.exitCode=1;
}
if(requireAccess&&accessCount!==paths.length){
 console.error('MISSING_WORKER_ACCESS: Cloudflare Access not confirmed for ALL surfaces');
 process.exitCode=1;
}
if(process.exitCode)console.error('Do NOT upload private research data.');
else console.log('Anonymous access blocked. Verify alternate user, authentic owner, R2 public URL and all Worker preview endpoints.');
