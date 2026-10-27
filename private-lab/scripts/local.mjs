// Local-only harness. No bypass is present in the production Worker.
import http from 'node:http';
import {DatabaseSync} from 'node:sqlite';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import worker,{api} from '../src/worker.mjs';
export function database(file){const db=new DatabaseSync(file,{readOnly:true});return {prepare(sql){let args=[];return {bind(...a){args=a;return this;},async all(){return {results:db.prepare(sql).all(...args)};},async first(){return db.prepare(sql).get(...args)||null;}};},close(){db.close();}};}
const root=fileURLToPath(new URL('../public/',import.meta.url));
export async function assets(request){const pathname=new URL(request.url).pathname;const names={'/':'index.html','/index.html':'index.html','/style.css':'style.css','/app.js':'app.js'};if(!names[pathname])return new Response('Not found',{status:404});return new Response(await readFile(path.join(root,names[pathname])),{headers:{'Content-Type':pathname.endsWith('.css')?'text/css':pathname.endsWith('.js')?'text/javascript':'text/html'}});}
if(process.argv[1]===fileURLToPath(import.meta.url)){
 if(!process.env.LAB_DB)throw Error('LAB_DB required');const env={DATA_BACKEND:process.env.DATA_BACKEND||'d1',DB:database(process.env.LAB_DB),ASSETS:{fetch:assets},ARCHIVE:{async get(key){if(!process.env.LAB_ARCHIVE)return null;try{return {body:await readFile(path.join(process.env.LAB_ARCHIVE,key))};}catch{return null;}}}};
 const preview=process.argv.includes('--preview');const server=http.createServer(async(req,res)=>{try{
  // Prevent DNS rebinding; never listen on a public interface.
  if(!['127.0.0.1:8787','localhost:8787'].includes(req.headers.host)){res.writeHead(403);res.end();return;}
  const request=new Request('http://'+req.headers.host+req.url,{method:req.method,headers:req.headers});
  const response=preview?(req.url.startsWith('/api/')?await api(request,env):await assets(request)):await worker.fetch(request,env);
  res.writeHead(response.status,Object.fromEntries(response.headers));res.end(Buffer.from(await response.arrayBuffer()));
 }catch{res.writeHead(500);res.end('local harness error');}});
 server.listen(8787,'127.0.0.1',()=>console.log(preview?'LOCAL UI PREVIEW — synthetic local authorization; not production authentication':'LOCAL FAIL-CLOSED WORKER'));
}
