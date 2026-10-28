// Private Cloudflare R2 compressed-pack reader. No authentication is performed
// here: the caller MUST verify Cloudflare Access JWT before calling this module.
// The packed release is immutable and maps are served only through a private R2 binding.
// r2Query creates a fresh env per request. Reuse a pack within that request,
// without retaining research data across users/releases or unbounded global caches.
const requests = new WeakMap();
async function objectJSON(env,path) {
  let cache=requests.get(env);
  if(!cache){cache=new Map();requests.set(env,cache);}
  if(!cache.has(path))cache.set(path,(async()=>{
    const obj=await env.ARCHIVE.get(path);
    if(!obj)throw new Error('Missing private R2 object');
    return obj.json();
  })());
  return cache.get(path);
}

async function packMap(env, id) {
  const prefix = env.DATA_PREFIX || 'query';
  const path = `${prefix}/packs/maps/${id}.json`;
  return objectJSON(env,path);
}

export async function readPacked(env, key) {
  if (!env.ARCHIVE) return null;
  const prefix = env.DATA_PREFIX || 'query';
  let pack = null;
  if (key === 'races/index.json' || key === 'players/index.json') {
    pack = 'packs/meta.json';
  } else if (/^days\/\d{4}-\d{2}-\d{2}\.json$/.test(key)) {
    const index = await readPacked(env,'races/index.json');
    if(!Array.isArray(index))throw new Error('Missing private race index');
    if(!index.some(row=>row.day===key.slice(5,15)))return null;
    const lookup = await packMap(env, `days-${key.slice(5, 9)}`);
    pack = lookup[key];
  } else if (/^players\/\d{4}\.json$/.test(key)) {
    const lookup = await packMap(env, 'players');
    pack = lookup[key];
  } else if (/^races\/\d{4}-\d{2}-\d{2}\.json$/.test(key)) {
    pack = `packs/races/${key.slice(6, 13)}.json`;
  } else if (key.startsWith('summaries/')) {
    pack = 'packs/summaries.json';
  } else if (key.startsWith('motors/')) {
    pack = 'packs/motors.json';
  } else if (key.startsWith('previews/')) {
    pack = 'packs/previews.json';
  }
  if (!pack) return null;
  const entries = await objectJSON(env,`${prefix}/${pack}`);
  const encoded = entries[key];
  if (typeof encoded !== 'string') return null;
  const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
  const uncompressed = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return JSON.parse(await new Response(uncompressed).text());
}
