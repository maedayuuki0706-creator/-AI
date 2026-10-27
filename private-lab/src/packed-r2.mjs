// Private Cloudflare R2 compressed-pack reader. No authentication is performed
// here: the caller MUST verify Cloudflare Access JWT before calling this module.
// The packed release is immutable and maps are served only through a private R2 binding.
const maps = new Map();

async function packMap(env, id) {
  const prefix = env.DATA_PREFIX || 'query';
  const path = `${prefix}/packs/maps/${id}.json`;
  if (maps.has(path)) return maps.get(path);
  const obj = await env.ARCHIVE.get(path);
  if (!obj) throw new Error('Missing private R2 lookup map');
  const mapping = await obj.json();
  maps.set(path, mapping);
  return mapping;
}

export async function readPacked(env, key) {
  if (!env.ARCHIVE) return null;
  const prefix = env.DATA_PREFIX || 'query';
  let pack = null;
  if (key === 'races/index.json' || key === 'players/index.json') {
    pack = 'packs/meta.json';
  } else if (/^days\/\d{4}-\d{2}-\d{2}\.json$/.test(key)) {
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
  const obj = await env.ARCHIVE.get(`${prefix}/${pack}`);
  if (!obj) throw new Error('Missing private R2 compressed pack');
  const entries = await obj.json();
  const encoded = entries[key];
  if (typeof encoded !== 'string') return null;
  const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
  const uncompressed = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return JSON.parse(await new Response(uncompressed).text());
}
