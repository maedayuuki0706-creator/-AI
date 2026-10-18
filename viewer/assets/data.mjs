// Read-only display adapters. This module never generates predictions or writes upstream.
export const VENUES = [['01','桐生'],['02','戸田'],['03','江戸川'],['04','平和島'],['05','多摩川'],['06','浜名湖'],['07','蒲郡'],['08','常滑'],['09','津'],['10','三国'],['11','びわこ'],['12','住之江'],['13','尼崎'],['14','鳴門'],['15','丸亀'],['16','児島'],['17','宮島'],['18','徳山'],['19','下関'],['20','若松'],['21','芦屋'],['22','福岡'],['23','唐津'],['24','大村']];
export const NAMES = new Map(VENUES);
export const DATA_ROOT = 'https://raw.githubusercontent.com/maedayuuki0706-creator/-AI/main/data/';
export const FEED = 'https://boat-sheet-feed.onrender.com';
export const SCHEDULE = 'https://boat-ai-navi-schedule.onrender.com/schedule.json';
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const normalize = value => String(value ?? '').normalize('NFKC').replace(/[\s\u3000]+/g,'').toLowerCase();
export const num = value => value == null || String(value).trim() === '' ? null : Number.isFinite(Number(String(value).replace(/%/g,''))) ? Number(String(value).replace(/%/g,'')) : null;
export const fixed = (value, digits = 1) => num(value) === null ? '—' : num(value).toFixed(digits);
export const pct = value => num(value) === null ? '—' : fixed(value) + '%';
export const jstDate = (value = new Date()) => new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(value);
export const dayKey = value => String(value ?? '').replace(/-/g,'');
export function validDay(value) {
  const s = dayKey(value);
  if (!/^20\d{6}$/.test(s)) return false;
  const d = new Date(s.slice(0,4)+'-'+s.slice(4,6)+'-'+s.slice(6,8)+'T00:00:00+09:00');
  return Number.isFinite(d.getTime()) && dayKey(jstDate(d)) === s;
}
export function isoDay(value) {
  const s = dayKey(value);
  return validDay(s) ? s.slice(0,4)+'-'+s.slice(4,6)+'-'+s.slice(6,8) : '';
}
export function stamp(value) {
  const date = new Date(value);
  return !value || !Number.isFinite(date.getTime()) ? '日時未取得' : new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',year:'numeric',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}).format(date)+' JST';
}
export function deadlineEpoch(day, time) {
  if (!validDay(day) || !/^([01]\d|2[0-3]):[0-5]\d$/.test(String(time))) return NaN;
  return Date.parse(isoDay(day)+'T'+time+':00+09:00');
}
export function raceSelection(search = '') {
  const p = new URLSearchParams(search), date = p.get('date') || jstDate();
  const venue = String(p.get('venue') || '').padStart(2,'0'), race = Number(p.get('race'));
  return validDay(date) && NAMES.has(venue) && Number.isInteger(race) && race >= 1 && race <= 12 ? {day:dayKey(date),jcd:venue,rno:race,key:dayKey(date)+'_'+venue+'_'+String(race).padStart(2,'0')} : null;
}
export function raceUrl(path, race) {
  return path+'?'+new URLSearchParams({date:isoDay(race.day),venue:race.jcd,race:String(race.rno)}).toString();
}
export function sameRace(value, race) {
  return Boolean(value && race && dayKey(value.day) === race.day && String(value.jcd).padStart(2,'0') === race.jcd && Number(value.rno) === race.rno);
}
export function scheduleRows(day, payload, source) {
  if (!validDay(day) || !payload || dayKey(payload.day) !== dayKey(day)) throw new Error('開催日が一致しません');
  if (source === 'saved' && payload.complete !== true) throw new Error('開催表が未確定です');
  const rows = Array.isArray(payload.races) ? payload.races : payload.races && typeof payload.races === 'object' ? Object.values(payload.races) : null;
  if (!rows) throw new Error('締切情報がありません');
  const seen = new Set(), races = [];
  for (const row of rows) {
    const jcd = String(row.jcd ?? '').padStart(2,'0'), rno = Number(row.rno), at = deadlineEpoch(day,row.deadline);
    if (!NAMES.has(jcd) || !Number.isInteger(rno) || rno < 1 || rno > 12 || !Number.isFinite(at)) continue;
    if (row.cancelled === true || row.canceled === true || ['cancelled','canceled','中止','不成立'].includes(row.status)) continue;
    const key = dayKey(day)+'_'+jcd+'_'+String(rno).padStart(2,'0');
    if (seen.has(key)) continue;
    seen.add(key);
    races.push({day:dayKey(day),jcd,rno,key,at,deadline:row.deadline});
  }
  races.sort((a,b) => a.at-b.at || a.jcd.localeCompare(b.jcd) || a.rno-b.rno);
  return {day:dayKey(day),races,partial:Boolean(payload.partial),capturedAt:payload.checked_at || payload.generated_at || '',source:source === 'saved' ? '保存済み公式締切表' : '公式情報の読取専用フィード',missing:payload.missing_venue_codes || []};
}
export const upcoming = (rows, now = Date.now()) => rows.filter(r => r.at > now);
export function remaining(at, now = Date.now()) {
  const min = Math.ceil((at-now)/60000);
  return min <= 0 ? '締切済み' : min <= 1 ? 'まもなく締切' : min < 60 ? 'あと'+min+'分' : 'あと'+Math.floor(min/60)+'時間'+(min%60 ? min%60+'分' : '');
}
export async function request(url, type = 'json', timeout = 14000) {
  const control = new AbortController(), timer = setTimeout(() => control.abort(), timeout);
  try {
    const response = await fetch(url,{signal:control.signal,cache:'no-cache',credentials:'omit',referrerPolicy:'no-referrer'});
    if (!response.ok) { const error = new Error('HTTP '+response.status); error.status = response.status; throw error; }
    return type === 'json' ? await response.json() : await response.text();
  } finally { clearTimeout(timer); }
}
const memory = new Map();
async function shared(key, fn, ttl = 300000) {
  const old = memory.get(key);
  if (old && Date.now()-old.at < ttl) return old.value;
  const value = Promise.resolve().then(fn);
  memory.set(key,{at:Date.now(),value});
  try { return await value; } catch (error) { memory.delete(key); throw error; }
}
export async function loadSchedule(day) {
  if (!validDay(day)) throw new Error('日付を確認してください');
  const key = dayKey(day);
  let result;
  try { result = scheduleRows(key,await request(DATA_ROOT+'race_cards/'+key+'.json'),'saved'); }
  catch (_) { result = scheduleRows(key,await request(SCHEDULE+'?date='+key,'json',45000),'feed'); }
  try { sessionStorage.setItem('boat-ai-navi:schedule',JSON.stringify({writtenAt:Date.now(),...result})); } catch (_) {}
  return result;
}
export async function loadScheduleSeed(day) {
  const key = dayKey(day);
  const read = (value, source) => {
    const result = scheduleRows(key,{day:value.day,races:value.races,partial:value.partial,generated_at:value.capturedAt || value.generated_at},'feed');
    const age = Date.now()-Date.parse(result.capturedAt);
    if (!Number.isFinite(age) || age < -300000 || age > 1800000) return null;
    return {...result,source};
  };
  try {
    const saved = JSON.parse(sessionStorage.getItem('boat-ai-navi:schedule') || 'null');
    if (saved && saved.day === key && Date.now()-saved.writtenAt >= 0 && Date.now()-saved.writtenAt < 300000) {
      const result = read(saved,'このタブで確認済みの公式締切');
      if (result) return result;
    }
  } catch (_) {}
  try { return read(await request('/data/public/schedule.json','json',4000),'保存済みの公式締切'); }
  catch (_) { return null; }
}
export function csv(text) {
  const records = []; let row = [], field = '', quoted = false;
  text = String(text).replace(/^\uFEFF/,'');
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) { if (c === '"' && text[i+1] === '"') { field += '"'; i++; } else if (c === '"') quoted = false; else field += c; }
    else if (c === '"') quoted = true;
    else if (c === ',') { row.push(field); field = ''; }
    else if (c === '\n') { row.push(field.replace(/\r$/,'')); if (row.some(Boolean)) records.push(row); row = []; field = ''; }
    else field += c;
  }
  if (row.length || field) { row.push(field.replace(/\r$/,'')); records.push(row); }
  const headers = records.shift() || [];
  return records.map(values => Object.fromEntries(headers.map((h,i) => [h,values[i] ?? ''])));
}
export function compactCard(record, race) {
  if (!sameRace(record,race)) return null;
  const boats = record.boats || record.official?.inputs;
  if (!Array.isArray(boats) || boats.length !== 6 || new Set(boats.map(b => Number(b.lane))).size !== 6 || boats.some(b => !Number.isInteger(Number(b.lane)) || Number(b.lane)<1 || Number(b.lane)>6)) return null;
  const fields = ['lane','racer_id','name','current_class','win_rate','avg_st','motor_number','motor_top2_rate','local_win_rate','flying'];
  return {...race,deadline:record.deadline || '',captured_at:record.captured_at || '',boats:boats.map(b => Object.fromEntries(fields.map(k => [k,b[k] ?? null]))).sort((a,b) => Number(a.lane)-Number(b.lane))};
}
export async function loadCard(race, force = false) {
  if (!race) throw new Error('レースを選択してください');
  const read = async () => {
    if (!force) {
      try {
        const card = compactCard(await request('/data/cards/'+race.key+'.json','json',3500),race);
        if (card) return {...card,source:'保存済み出走表'};
      } catch (_) {}
      try {
        const card = compactCard(await request(DATA_ROOT+'hiyori/requests/'+race.key+'.json','json',10000),race);
        if (card) return {...card,source:'保存済み公式入力'};
      } catch (_) {}
    }
    const query = new URLSearchParams({date:race.day,jcd:race.jcd,rno:String(race.rno)});
    const results = await Promise.allSettled([request(FEED+'/race.csv?'+query,'text',30000),request(FEED+'/race_roster.csv?'+query,'text',30000)]);
    const rows = results[0].status === 'fulfilled' ? csv(results[0].value) : [];
    const roster = results[1].status === 'fulfilled' ? csv(results[1].value) : [];
    // Never use row position as a substitute for an absent lane or racer identity.
    const rosterByID = new Map(roster.filter(r => /^\d{4}$/.test(r['登録番号'])).map(r => [r['登録番号'],r]));
    const boats = rows.filter(r => /^[1-6]$/.test(r['枠'])).map(r => {
      const extra = rosterByID.get(r['登録番号']) || {};
      return {lane:Number(r['枠']),racer_id:r['登録番号'] || null,name:extra['選手名'] || r['選手名'] || null,current_class:r['級別'] || extra['級別'] || null,win_rate:num(r['全国勝率']),avg_st:num(r['平均ST']),motor_number:num(extra['モーターNo.']),motor_top2_rate:num(extra['モーター2連率']),flying:null,local_win_rate:null};
    });
    if (boats.length !== 6 || new Set(boats.map(b => b.lane)).size !== 6) throw new Error('6艇の出走表を確認できませんでした');
    return {...race,boats:boats.sort((a,b) => a.lane-b.lane),deadline:rows[0]?.['締切'] || '',captured_at:new Date().toISOString(),source:'公式出走フィード'};
  };
  return force ? read() : shared('card:'+race.key,read,120000);
}
export function compactPrediction(record, race) {
  if (!sameRace(record,race)) throw new Error('選択レースと予想が一致しません');
  const p = record.models?.prototype2;
  if (!p) throw new Error('予想は未公開です');
  const cards = {};
  for (const key of ['balanced','probability','value','longshot']) {
    const c = p.strategy_cards?.cards?.[key];
    if (!c) continue;
    const picks = rows => Array.isArray(rows) ? [...new Set(rows.filter(x => /^[1-6]-[1-6]-[1-6]$/.test(x) && new Set(x.split('-')).size === 3))] : [];
    cards[key] = {main:picks(c.main_picks),cover:picks(c.cover_picks),notes:Array.isArray(c.notes) ? c.notes.filter(x => typeof x === 'string') : []};
  }
  if (!Object.values(cards).some(c => c.main.length+c.cover.length)) throw new Error('公開された買い目がありません');
  const created = record.created_at || '', deadline = deadlineEpoch(race.day,record.deadline);
  const createdMs = Date.parse(created);
  return {...race,created_at:created,deadline:record.deadline || '',cards,heads:p.heads || {},afterClose:Number.isFinite(createdMs) && Number.isFinite(deadline) && createdMs >= deadline,version:p.version_label || 'PT2',reasons:p.boat_reasons || {},analysis:typeof p.scenario_commentary === 'string' ? p.scenario_commentary : '',db:p.database?.lane_factors || {},playerMatches:num(p.db_player_matches),motorMatches:num(p.db_motor_matches)};
}
// Called only by the explicit forecast button handler. No other data loader calls it.
export async function loadPrediction(race) {
  try { return {...compactPrediction(await request(DATA_ROOT+'prototype12_delivery/predictions/'+race.key+'.json','json',18000),race),source:'公開予想原本'}; }
  catch (error) {
    // A mismatch must never be hidden by falling back to a different payload.
    if (error.status !== 404 && !error.status && error.name !== 'AbortError' && !/fetch|network/i.test(error.message)) throw error;
    try {
      const pack = await request('/data/races/'+race.key+'.json','json',4000);
      return {...compactPrediction(pack.prediction,race),source:'保存済み予想スナップショット'};
    } catch (_) {
      if (error.status === 404) { const e = new Error('このレースの予想は未公開です'); e.status = 404; throw e; }
      throw error;
    }
  }
}
export const GRADES = {S:['◎','最上位','best'],A:['○','高評価','good'],B:['△','標準','average'],C:['注意','低め','caution'],D:['低','低評価','low']};
export function grade(value) { const key = String(value || '').trim().toUpperCase(); return GRADES[key] ? {key,mark:GRADES[key][0],label:GRADES[key][1],css:GRADES[key][2]} : {key:'',mark:'—',label:'未評価',css:'missing'}; }
export function motorEntry(motors, jcd, no, raceDay = '') {
  const n = num(no), entry = motors?.[String(jcd).padStart(2,'0')+':'+n];
  if (!NAMES.has(String(jcd).padStart(2,'0')) || !Number.isInteger(n) || n < 1 || !entry || Number(entry.motor) !== n || (entry.venue && entry.venue !== NAMES.get(String(jcd).padStart(2,'0')))) return null;
  const start = dayKey(String(entry.start || '').replace(/\//g,'-'));
  if (raceDay && validDay(start) && start > dayKey(raceDay)) return null;
  return entry;
}
export async function loadMeta() {
  try {
    const meta = await request(DATA_ROOT+'sheet_db/meta.json','json',10000);
    if (meta.source !== 'Google Sheets 競艇AI データベース' || !Number.isFinite(Date.parse(meta.snapshot_at)) || !Number.isInteger(meta.motor_count) || !Number.isInteger(meta.player_count)) throw new Error('出典が不明です');
    return meta;
  } catch (_) { return request('/data/public/meta.json','json',4000); }
}
export async function loadDatabase(kind) {
  if (!['motors','players'].includes(kind)) throw new Error('未対応のデータです');
  return shared(kind,async () => {
    const meta = await loadMeta(); let data, saved = false;
    try { data = await request(DATA_ROOT+'sheet_db/'+kind+'.json','json',18000); }
    catch (_) {
      const pack = await request('/data/public/'+kind+'.json','json',5000);
      data = pack.data; Object.assign(meta,{snapshot_at:pack.snapshot_at}); saved = true;
    }
    const expected = kind === 'motors' ? meta.motor_count : meta.player_count;
    if (!data || typeof data !== 'object' || Array.isArray(data) || Object.keys(data).length !== expected) throw new Error('データ件数と更新情報が一致しません');
    return {data,meta,saved};
  });
}
export function playersList(data) {
  return Object.entries(data || {}).filter(([id,p]) => /^\d{4}$/.test(id) && typeof p.name === 'string').map(([id,p]) => ({...p,id,search:normalize(p.name)+' '+id}));
}
export function playerMatches(players, query) {
  const q = normalize(query);
  return !q ? [] : players.filter(p => p.search.includes(q)).sort((a,b) => Number(b.id === q || normalize(b.name) === q)-Number(a.id === q || normalize(a.name) === q) || a.name.localeCompare(b.name,'ja'));
}
const STAT_FIELDS = ['label','judged','hits','hit_rate','stake_yen','return_yen','roi','profit_yen','manshu','torigami','pending','resolved','delivered','avg_points'];
export function publicStats(payload) {
  if (!validDay(payload?.day) || !payload.streams || typeof payload.streams !== 'object' || num(payload.unit_yen) !== 100) throw new Error('集計条件を確認できません');
  const pick = m => Object.fromEntries(STAT_FIELDS.filter(k => m[k] != null).map(k => [k,m[k]]));
  return {day:dayKey(payload.day),generated_at:payload.generated_at || '',unit_yen:100,basis:'配信済み予想を1点100円で仮想購入。未確定は除外。',streams:Object.fromEntries(Object.entries(payload.streams).map(([k,v]) => [k,pick(v)])),venues:Object.fromEntries(Object.entries(payload.venues || {}).map(([k,v]) => [k,Object.fromEntries(Object.entries(v).map(([s,m]) => [s,pick(m)]))]))};
}
export async function loadStats(date = '') {
  try {
    const path = date ? dayKey(date) : 'latest';
    if (date && !validDay(date)) throw new Error('日付を確認してください');
    return {...publicStats(await request(DATA_ROOT+'live_status/'+path+'.json','json',18000)),saved:false};
  } catch (error) {
    const saved = await request('/data/public/stats.json','json',5000);
    if (date && dayKey(saved.day) !== dayKey(date)) throw error;
    return {...publicStats(saved),saved:true};
  }
}
