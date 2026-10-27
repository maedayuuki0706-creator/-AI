// Deliberately requires a real authentication gate, not merely an undeployed 404.
// Use before uploading any private R2 research data and after routing changes.
// Credentials must NEVER be supplied to this script.
const raw = process.argv[2];
if (!raw) throw Error('HTTPS origin required');
const origin = new URL(raw);
if (origin.protocol !== 'https:' || origin.username || origin.password ||
    origin.pathname !== '/' || origin.search || origin.hash) {
  throw Error('Expected HTTPS origin without path, credentials, query or fragment');
}
const paths = [
  '/', '/index.html', '/app.js', '/style.css', '/api/status',
  '/api/races', '/api/players', '/api/archive?id=202610011401',
  '/data/search.sqlite', '/not-a-real-route'
];
for (const path of paths) {
  let response;
  try {
    response = await fetch(new URL(path, origin), {
      redirect: 'manual',
      headers: {'Cf-Access-Authenticated-User-Email':'forged@example.test'},
      signal: AbortSignal.timeout(15000)
    });
  } catch (err) {
    console.error(path, 'NETWORK_OR_TLS_ERROR', err?.message || String(err));
    process.exitCode = 1;
    continue;
  }
  const location = response.headers.get('location');
  let accessRedirect = false;
  if (location && [301,302,303,307,308].includes(response.status)) {
    const target = new URL(location, origin);
    accessRedirect = target.protocol === 'https:' &&
      /^[a-z0-9-]+\.cloudflareaccess\.com$/i.test(target.hostname);
  }
  // A 404 is NOT proof of authentication: it might mean the site is missing.
  const denied = response.status === 401 || response.status === 403 || accessRedirect;
  console.log(path, response.status, denied ? 'DENIED' : 'FAIL');
  if (!denied) process.exitCode = 1;
}
if (process.exitCode) {
  console.error('Security preflight failed: do not upload research data.');
} else {
  console.log('Unauthenticated routes denied. Still verify allowed/blocked accounts,');
  console.log('direct workers.dev and preview URLs, and private R2 bucket settings.');
}
