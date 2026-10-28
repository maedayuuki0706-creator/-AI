import {test} from 'node:test';
import assert from 'node:assert/strict';
import {gzipSync} from 'node:zlib';
import {readPacked} from '../src/packed-r2.mjs';
const base = 'releases/official-2022-2025-v1/query';
const gzip64 = o => gzipSync(JSON.stringify(o)).toString('base64');
const objects = new Map();
const put = (path,data) => objects.set(`${base}/${path}`,data);
const realValues = {
 'summaries/manifest.json': {races:205269,entries:1231614},
 'races/index.json': [{day:'2025-12-31',venues:['03']}],
 'races/2025-12-31.json': [{id:'202512310301',day:'2025-12-31'}],
 'days/2025-12-31.json': {'202512310301':{race:{id:'202512310301'},entries:[]}},
 'players/index.json': [{id:'4238',name:'毒島誠'}],
 'players/4238.json': {player:{id:'4238',name:'毒島誠'},entries:[]},
 'summaries/water-03.json': [{venue:'03',wind:2}],
 'motors/03.json': [],
 'previews/03.json': []
};
function pack(path,keys){put(path,Object.fromEntries(keys.map(k=>[k,gzip64(realValues[k])])));}
pack('packs/meta.json',['races/index.json','players/index.json']);
pack('packs/days/2025-12-4.json',['days/2025-12-31.json']);
pack('packs/players/197.json',['players/4238.json']);
pack('packs/races/2025-12.json',['races/2025-12-31.json']);
pack('packs/summaries.json',['summaries/manifest.json','summaries/water-03.json']);
pack('packs/motors.json',['motors/03.json']);
pack('packs/previews.json',['previews/03.json']);
put('packs/maps/days-2025.json',{'days/2025-12-31.json':'packs/days/2025-12-4.json'});
put('packs/maps/players.json',{'players/4238.json':'packs/players/197.json'});
const env={DATA_PREFIX:base,ARCHIVE:{async get(key){return objects.has(key)?{json:async()=>objects.get(key)}:null}}};
for(const [key,expected] of Object.entries(realValues)){
 test(`pack round trip ${key}`,async()=>assert.deepEqual(await readPacked(env,key),expected));
}
test('does not serve unknown file',async()=>assert.equal(await readPacked(env,'private/secret.json'),null));
test('does not serve missing item',async()=>assert.equal(await readPacked(env,'players/0000.json'),null));
test('one request reads each pack once and a new request cannot reuse another bucket',async()=>{
 let reads=0;const fresh={DATA_PREFIX:base,ARCHIVE:{async get(key){reads++;return {json:async()=>objects.get(key)};}}};
 await readPacked(fresh,'races/index.json');await readPacked(fresh,'players/index.json');assert.equal(reads,1);
 const other={DATA_PREFIX:base,ARCHIVE:{async get(){return {json:async()=>({'races/index.json':gzip64([])})};}}};
 assert.deepEqual(await readPacked(other,'races/index.json'),[]);
});
