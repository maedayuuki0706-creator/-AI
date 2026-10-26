// BOAT AI NAVI — read-only independent analysis primitives.
export const VENUES = Object.freeze([
  ['01','桐生'],['02','戸田'],['03','江戸川'],['04','平和島'],['05','多摩川'],['06','浜名湖'],
  ['07','蒲郡'],['08','常滑'],['09','津'],['10','三国'],['11','びわこ'],['12','住之江'],
  ['13','尼崎'],['14','鳴門'],['15','丸亀'],['16','児島'],['17','宮島'],['18','徳山'],
  ['19','下関'],['20','若松'],['21','芦屋'],['22','福岡'],['23','唐津'],['24','大村']
]);
export const NAMES = new Map(VENUES);
export const SHARDS = Object.freeze(['202609a','202609b','202609c','202610a']);
export const normalize = v => String(v ?? '').normalize('NFKC').replace(/[\s　]+/g,'').toLowerCase();
export const finite = v => v === '' || v == null ? null : (Number.isFinite(Number(v)) ? Number(v) : null);
export const yen = n => Number.isFinite(n) ? Math.round(n).toLocaleString('ja-JP')+'円' : '—';
export const rate = n => Number.isFinite(n) ? n.toFixed(1)+'%' : '—';
export const dayLabel = day => /^\d{8}$/.test(day) ? `${day.slice(0,4)}/${day.slice(4,6)}/${day.slice(6,8)}` : '—';
const VALID_TRIFECTA = /^[1-6]-[1-6]-[1-6]$/;
function validRecord(row) {
  return Array.isArray(row) && row.length >= 5 && /^20\d{6}$/.test(row[0]) &&
    NAMES.has(row[1]) && Number.isInteger(row[2]) && row[2]>=1 && row[2]<=12 &&
    VALID_TRIFECTA.test(row[3]) && new Set(row[3].split('-')).size===3 &&
    Number.isFinite(row[4]) && row[4] > 0;
}
export function mergeHistory(shards) {
  const dedup = new Map(); let rejected=0,source=0,skipped=0;
  for(const part of shards) {
    if(!part || !Array.isArray(part.rows)) throw new Error('履歴のデータ形式が不正です');
    source+=Number(part.counts?.source ?? part.rows.length);
    skipped+=Number(part.counts?.skip ?? 0);
    for(const row of part.rows) {
      if(!validRecord(row)) {rejected++;continue;}
      const key=row[0]+'|'+row[1]+'|'+row[2];
      if(dedup.has(key)) { rejected++; continue; }
      dedup.set(key,row);
    }
  }
  const rows=[...dedup.values()].sort((a,b)=>b[0].localeCompare(a[0]) || a[1].localeCompare(b[1]) || a[2]-b[2]);
  return {rows,source,skipped,rejected,from:rows.at(-1)?.[0] ?? '',to:rows[0]?.[0] ?? ''};
}
export function filterHistory(rows,{from='',to='',venue='',first='',minPayout=0,manshu=false}={}) {
  const floor=finite(minPayout) ?? 0;
  return rows.filter(r => (!from || r[0]>=from.replace(/-/g,'')) &&
   (!to || r[0]<=to.replace(/-/g,'')) && (!venue || r[1]===venue) &&
   (!first || r[3].charAt(0)===String(first)) && r[4]>=floor && (!manshu || r[4]>=10000));
}
export function summarizeHistory(rows) {
  const heads=[0,0,0,0,0,0];let manshu=0,highest=null;
  for(const r of rows) { heads[Number(r[3][0])-1]++; if(r[4]>=10000)manshu++; if(!highest || r[4]>highest[4]) highest=r; }
  return {count:rows.length,heads,manshu,rate:rows.length ? manshu/rows.length*100:null,highest};
}
export function rankPlayers(payload,{query='',course=1,level='',branch='',sort='course',minimum=0}={}) {
  const source=payload?.data;
  if(!source || Array.isArray(source) || typeof source!=='object') throw new Error('選手データの形式が不正です');
  const needle=normalize(query),min=finite(minimum) ?? 0,index=Math.min(5,Math.max(0,Number(course)-1 || 0));
  const rows=Object.entries(source).filter(([id,p])=>/^\d{4}$/.test(id)&&p&&typeof p.name==='string')
    .map(([id,p])=>({id,...p,courseValue:finite(Array.isArray(p.course_win)?p.course_win[index]:null)}))
    .filter(p=>(!needle || normalize(p.name).includes(needle) || p.id.includes(needle)) &&
      (!level||p.class===level) && (!branch || p.branch===branch) &&
      (p.courseValue!==null && p.courseValue>=min));
  const metric=sort==='st' ? p=>finite(p.avg_st) : sort==='national' ? p=>finite(p.win) : p=>p.courseValue;
  rows.sort((a,b)=>{
    const x=metric(a),y=metric(b); if(x===null) return 1;if(y===null) return -1;
    return (sort==='st'?x-y:y-x)||a.id.localeCompare(b.id);
  });
  return rows;
}
