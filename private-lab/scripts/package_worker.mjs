// Build the connector upload from the canonical modules and three public assets.
// No database, credentials, remote GitHub fetch, or third-party build dependency.
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=fileURLToPath(new URL('../',import.meta.url));
export async function packageWorker(){
 const files=[];
 for(const name of ['worker','auth','r2-api','packed-r2'])files.push({name:`src/${name}.mjs`,content:await readFile(path.join(root,`src/${name}.mjs`),'utf8')});
 const assets={};
 for(const [name,type] of [['index.html','text/html'],['app.js','text/javascript'],['style.css','text/css']])assets['/'+name]={body:await readFile(path.join(root,'public',name),'utf8'),type:type+'; charset=utf-8'};
 files.push({name:'embedded-assets.mjs',content:`const files=${JSON.stringify(assets)};\nexport const assets={async fetch(request){const pathname=new URL(request.url).pathname;const file=files[pathname==='/'?'/index.html':pathname];if(!file)return new Response('Not found',{status:404});return new Response(request.method==='HEAD'?null:file.body,{headers:{'Content-Type':file.type}});}};\n`});
 files.push({name:'entry.mjs',content:"import worker from './src/worker.mjs';\nimport {assets} from './embedded-assets.mjs';\nexport default {fetch(request,env){return worker.fetch(request,{...env,ASSETS:assets});}};\n"});
 return {main_module:'entry.mjs',files};
}
if(process.argv[1]===fileURLToPath(import.meta.url)){
 const output=path.join(root,'.deploy');await mkdir(output,{recursive:true});
 await writeFile(path.join(output,'modules.json'),JSON.stringify(await packageWorker()));
 console.log('Packaged canonical Worker modules and three authenticated assets. DATA_READY must remain 0 until verification is complete.');
}
