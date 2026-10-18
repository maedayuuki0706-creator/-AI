// GA4 is off until a site owner supplies an ID AND enables it at build time.
// Basic consent: no Google script, pings or queued pre-consent interactions.
const CONSENT_KEY = 'boat-ai-navi:analytics-consent:v1';
const MAX_AGE = 180 * 86400000;
let config = null, consent = 'unset', started = false, initialized = false;
const $ = id => document.getElementById(id);
export function configured(value = globalThis.NAVI_CONFIG) {
  return Boolean(value && value.preview !== true && value.analytics?.enabled === true && /^G-[A-Z0-9]+$/.test(value.analytics.measurementId || ''));
}
export function safeLocation(location) {
  const p = new URLSearchParams(location.search), out = new URL(location.pathname,location.origin);
  for (const key of ['date','venue','race']) {
    const v = p.get(key);
    if (v && (key === 'date' ? /^20\d{2}-\d{2}-\d{2}$/.test(v) : /^\d{1,2}$/.test(v))) out.searchParams.set(key,v);
  }
  // Restrict acquisition tags; never forward arbitrary query strings or names.
  const allowed = {utm_source:['x','twitter'],utm_medium:['social','organic_social'],utm_campaign:['free_prediction','profile','race','motor','research']};
  for (const [key,values] of Object.entries(allowed)) if (values.includes(p.get(key))) out.searchParams.set(key,p.get(key));
  return out.href;
}
export function fromX(location, referrer) {
  const p = new URLSearchParams(location.search);
  if (['x','twitter'].includes(p.get('utm_source'))) return true;
  try { return ['x.com','www.x.com','twitter.com','www.twitter.com','t.co'].includes(new URL(referrer).hostname); }
  catch (_) { return false; }
}
function readConsent() {
  try {
    const saved = JSON.parse(localStorage.getItem(CONSENT_KEY) || 'null');
    if (saved && ['granted','denied'].includes(saved.value) && Date.now()-saved.at >= 0 && Date.now()-saved.at < MAX_AGE) return saved.value;
  } catch (_) {}
  return 'unset';
}
function saveConsent(value) {
  consent = value;
  try { localStorage.setItem(CONSENT_KEY,JSON.stringify({value,at:Date.now()})); } catch (_) {}
}
const denied = {analytics_storage:'denied',ad_storage:'denied',ad_user_data:'denied',ad_personalization:'denied'};
function start() {
  if (!configured(config) || consent !== 'granted' || started) return;
  started = true;
  const id = config.analytics.measurementId;
  window['ga-disable-'+id] = false;
  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { window.dataLayer.push(arguments); };
  window.gtag('consent','default',denied);
  window.gtag('consent','update',{...denied,analytics_storage:'granted'});
  window.gtag('js',new Date());
  window.gtag('config',id,{send_page_view:false,allow_google_signals:false,allow_ad_personalization_signals:false,page_location:safeLocation(window.location),page_referrer:safeReferrer(document.referrer)});
  const script = document.createElement('script');
  script.async = true;
  script.src = 'https://www.googletagmanager.com/gtag/js?id='+encodeURIComponent(id);
  document.head.appendChild(script);
  track('page_view',{page_location:safeLocation(window.location),page_title:document.title,page_referrer:safeReferrer(document.referrer)});
  if (fromX(window.location,document.referrer)) track('x_referral',{source:'x'});
}
function safeReferrer(referrer) {
  try { const url = new URL(referrer); return url.origin+'/'; } catch (_) { return ''; }
}
const EVENTS = new Set(['page_view','race_detail_view','prediction_open','motor_search','racer_search','x_referral']);
const PARAMS = new Set(['page_location','page_title','page_referrer','date','venue_code','race_number','result_count','query_length','source','entry_point']);
export function track(event, parameters = {}) {
  if (!configured(config) || consent !== 'granted' || !started || !EVENTS.has(event)) return false;
  const safe = {};
  for (const [key,value] of Object.entries(parameters)) if (PARAMS.has(key) && ['string','number'].includes(typeof value)) safe[key] = typeof value === 'string' ? value.slice(0,180) : value;
  window.gtag('event',event,safe);
  return true;
}
function deleteAnalyticsCookies() {
  for (const cookie of document.cookie.split(';')) {
    const name = cookie.trim().split('=')[0];
    if (!/^_ga(?:_|$)/.test(name)) continue;
    const base = name+'=; Max-Age=0; Path=/; SameSite=Lax';
    document.cookie = base;
    const host = location.hostname.split('.');
    while (host.length > 1) { document.cookie = base+'; Domain=.'+host.join('.'); host.shift(); }
  }
}
function choose(value) {
  saveConsent(value);
  if ($('consent-panel')) $('consent-panel').hidden = true;
  if (value === 'granted') start();
  else if (started) {
    window['ga-disable-'+config.analytics.measurementId] = true;
    window.gtag('consent','update',denied);
    deleteAnalyticsCookies();
    // A reload removes the loaded Google library after consent is withdrawn.
    window.location.reload();
  }
}
export function initAnalytics(toast = () => {}) {
  if (initialized) return; initialized = true; config = globalThis.NAVI_CONFIG || {};
  document.querySelectorAll('[data-consent-settings]').forEach(button => button.addEventListener('click',() => {
    if (configured(config)) { $('consent-panel').hidden = false; $('consent-accept')?.focus(); }
    else toast(config.preview ? 'プレビューではアクセス解析を停止しています。' : 'アクセス解析は現在無効です。');
  }));
  if (!configured(config)) return;
  const label = $('analytics-state');
  if (label) label.textContent = 'アクセス解析の準備が有効です。閲覧者が許可した場合だけGoogle Analyticsを読み込みます。';
  consent = readConsent();
  $('consent-accept')?.addEventListener('click',() => choose('granted'));
  $('consent-decline')?.addEventListener('click',() => choose('denied'));
  if (consent === 'granted') start();
  else if (consent === 'unset' && $('consent-panel')) $('consent-panel').hidden = false;
}
