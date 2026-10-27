// No credentials accepted. Run before private data upload and after every routing change.
const origin=process.argv[2];if(!origin||new URL(origin).protocol!=='https:')throw Error('HTTPS origin required');
for(const path of ['/','/index.html','/app.js','/style.css','/api/status','/api/races','/api/players','/api/archive?id=202610011401','/data/search.sqlite']){
 const r=await fetch(new URL(path,origin),{redirect:'manual',headers:{'Cf-Access-Authenticated-User-Email':'forged@example.test'}});
 const redirect=[302,303,307].includes(r.status)&&new URL(r.headers.get('location'),origin).hostname.endsWith('.cloudflareaccess.com');
 const denied=[401,403,404].includes(r.status)||redirect;
 console.log(path,r.status,denied?'DENIED':'FAIL');if(!denied)process.exitCode=1;
}
