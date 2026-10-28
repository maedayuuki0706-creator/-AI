// Historical win-path comparison, PRIVATE R2 only. POST-race aggregates only.
// No user supplied strings can become an arbitrary storage key.
const methods=['逃げ','差し','まくり','まくり差し','抜き','恵まれ'];
const rate=(n,d)=>d>0?Math.round(1000*n/d)/10:null;
const inRange=(v,a,b)=>Number.isInteger(v)&&v>=a&&v<=b;
async function decompress(encoded){
  const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
  return JSON.parse(await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text());
}
export async function winpathQuery(request,env) {
  if(env.DATA_BACKEND!=='r2'||!env.ARCHIVE||env.DATA_READY!=='1')return {error:'勝ち筋研究データは未接続です'};
  const qs=new URL(request.url).searchParams;
  const ids=(qs.get('ids')||'').split(',').map(s=>s.trim()).filter(Boolean);
  if(ids.length<1||ids.length>6||ids.some(id=>!/^\d{4}$/.test(id)))throw Error('invalid ids');
  const venue=qs.get('venue')||'all';
  if(venue!=='all'&&!/^(0[1-9]|1[0-9]|2[0-4])$/.test(venue))throw Error('invalid venue');
  const basis=qs.get('basis')||'frame',period=qs.get('period')||'all';
  if(!['frame','course'].includes(basis)||!['all','2025'].includes(period))throw Error('invalid filter');
  const lanes=(qs.get('lanes')||ids.map((_,i)=>String(i+1)).join(',')).split(',').map(Number);
  if(lanes.length!==ids.length||lanes.some(n=>!inRange(n,1,6)))throw Error('invalid lanes');
  const prefix=env.DATA_PREFIX||'query',cache=new Map();
  async function pack(name){
    if(!cache.has(name))cache.set(name,(async()=>{const obj=await env.ARCHIVE.get(prefix+'/winpaths/'+name);if(!obj)return null;return obj.json()})());
    return cache.get(name);
  }
  const baseline=await pack('baseline.json');
  if(!baseline)return {error:'勝ち筋集計の投入前です'};
  const out=await Promise.all(ids.map(async(id,i)=>{
    const group='p'+String(Math.floor(Number(id)/50)).padStart(3,'0')+'.json';
    const packed=await pack(group);const item=packed?.[id];
    if(!item)return {id,name:null,frame:i+1,course:lanes[i],sample:null,baseline:null,unavailable:true};
    const d=await decompress(item);
    const lane=lanes[i],key=period+'|'+venue+'|'+basis+'|'+lane;
    const sample=d.rows[key]||null;
    const reference=baseline.rows[key]||null;
    function present(r){
      if(!r)return null;
      const won=r.method||{},lost=r.loss||{},defeats=r.n-r.w;
      return {...r,
        winRate:rate(r.w,r.n),top2Rate:rate(r.t2,r.n),top3Rate:rate(r.t3,r.n),
        escapeRate:rate(won['逃げ']||0,r.n),
        makuriRate:rate(won['まくり']||0,r.n),
        makurizashiRate:rate(won['まくり差し']||0,r.n),
        sashiRate:rate(won['差し']||0,r.n),
        nigashiRate:basis==='course'&&lane===2?rate(r.in_escape,r.n):null,
        beatenByMakuriRate:basis==='course'&&lane===1?rate(lost['まくり']||0,defeats):null,
        beatenBySashiRate:basis==='course'&&lane===1?rate((lost['差し']||0)+(lost['まくり差し']||0),defeats):null,
        lostCount:defeats,avgSt:r.sn?Math.round((r.ss/r.sn)*1000)/1000:null,
        methods:methods.map(name=>({name,wins:won[name]||0,perStart:rate(won[name]||0,r.n),amongWins:rate(won[name]||0,r.w)}))
      };
    }
    return {id,name:d.name,frame:i+1,course:lanes[i],lane,sample:present(sample),baseline:present(reference),unavailable:!sample};
  }));
  return {rows:out,scope:{venue,basis,period,from:period==='all'?'2022-01-01':'2025-01-01',to:'2025-12-31'},
   definitions:{
    winRate:'指定枠または実進入コースで1着になったレース数÷該当出走数',
    escapeRate:'その選手が「逃げ」で1着となった回数÷該当出走数',
    nigashiRate:'実進入2コース時に1コースが「逃げ」で1着となった回数÷2コース出走数',
    beatenByMakuriRate:'実進入1コース時に敗れたうち相手決まり手が「まくり」の割合',
    beatenBySashiRate:'実進入1コース時に敗れたうち相手決まり手が「差し」「まくり差し」の割合',
    methodRate:'本人がその決まり手で勝利した回数÷指定枠/コース出走数'
   },
   note:'2022〜2025年の公式結果からの事後集計。2026年の出走表・展示・直近データ・相手関係を予測した数値ではありません。枠番と実進入を区別し、各率の分母と標本数を確認してください。'};
}
