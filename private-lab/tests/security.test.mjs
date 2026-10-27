import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/worker.mjs';
import {authorize} from '../src/auth.mjs';
const pair=await crypto.subtle.generateKey({name:'RSASSA-PKCS1-v1_5',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['sign','verify']);
const jwk=await crypto.subtle.exportKey('jwk',pair.publicKey);jwk.kid='test-key';
const env={ACCESS_TEAM:'isolated-unit-test',ACCESS_AUD:'private-aud',ALLOWED_EMAILS:'owner@example.test'};
const base={iss:'https://isolated-unit-test.cloudflareaccess.com',aud:['private-aud'],email:'owner@example.test',sub:'owner',iat:Math.floor(Date.now()/1000),exp:Math.floor(Date.now()/1000)+300};
const b64=x=>Buffer.from(JSON.stringify(x)).toString('base64url');
async function token(claims={},head={}){const s=b64({alg:'RS256',kid:'test-key',...head})+'.'+b64({...base,...claims});return s+'.'+Buffer.from(await crypto.subtle.sign('RSASSA-PKCS1-v1_5',pair.privateKey,Buffer.from(s))).toString('base64url');}
const certs=async()=>Response.json({keys:[jwk]});
function req(t,path='/'){return new Request('https://private.example.test'+path,{headers:t?{'Cf-Access-Jwt-Assertion':t}:{}});}
test('missing authentication denies every surface without touching data',async()=>{for(const path of ['/','/index.html','/app.js','/style.css','/api/status','/api/races','/api/archive?id=202201012402','/data/private.sqlite','/anything']){const r=await worker.fetch(req(null,path),{ASSETS:{fetch(){throw Error('must not run');}},DB:{}});assert.equal(r.status,403,path);assert.match(r.headers.get('cache-control'),/no-store/);}});
test('signed valid owner accepted; forged identity is not enough',async()=>{assert.equal(await authorize(req(await token()),env,certs),true);assert.equal(await authorize(new Request('https://x',{headers:{'Cf-Access-Authenticated-User-Email':base.email}}),env,certs),false);});
test('expired, wrong audience/issuer, unapproved account, future nbf/iat, missing sub and bad algorithm denied',async()=>{for(const c of [{exp:0},{aud:['public-aud']},{iss:'https://evil.test'},{email:'other@example.test'},{nbf:Date.now()/1000+300},{iat:Date.now()/1000+300},{sub:''},{aud:'private-aud'},{exp:'9999999999'}])assert.equal(await authorize(req(await token(c)),env,certs),false,JSON.stringify(c));assert.equal(await authorize(req(await token({},{alg:'none'})),env,certs),false);});
test('tampered signature, malformed JWT and absent config denied',async()=>{const t=await token();const parts=t.split('.');parts[2]='X'+parts[2].slice(1);assert.equal(await authorize(req(parts.join('.')),env,certs),false);assert.equal(await authorize(req('abc.def.ghi'),env,certs),false);assert.equal(await authorize(req(t),{},certs),false);});
test('Worker validates signature before serving assets/API; all methods protected',async()=>{const old=globalThis.fetch;globalThis.fetch=certs;try{const e={...env,ASSETS:{fetch:async()=>new Response('safe asset')}};const r=await worker.fetch(req(await token()),e);assert.equal(r.status,200);assert.match(r.headers.get('Content-Security-Policy'),/frame-ancestors 'none'/);const post=new Request('https://private.example.test/api/status',{method:'POST',headers:{'Cf-Access-Jwt-Assertion':await token()}});assert.equal((await worker.fetch(post,e)).status,405);}finally{globalThis.fetch=old;}});
