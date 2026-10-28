// Historical, read-only win-path comparison UI. No forecast is generated.
export async function renderWinpaths(root,ctx) {
  const {get,el,venues,fmt}=ctx;
  const percent=x=>x===null||x===undefined?'未取得':Number(x).toFixed(1)+'%';
  const num=x=>x===null||x===undefined?'未取得':fmt(x);
  const heading=el('p','', '出走する6艇を、枠番別・実進入コース別の過去実績から比較。決まり手と敗れ方を数字で確かめる。');
  root.append(heading);
  const intro=el('div','notice','現在の収録範囲は2022〜2025年。2026年の出走表は未接続のため、登録番号を手入力して比較してください。これは事後統計であり、当日予想や勝率予測ではありません。');
  root.append(intro);
  const form=el('form','winpath-form');
  const filters=el('div','winpath-filters');
  const field=(parent,title,control)=>{
    const l=el('label','',title);l.append(control);parent.append(l);return control;
  };
  const option=(value,title)=>new Option(title,value);
  const venue=el('select');venue.append(option('all','全国24場'));venues.forEach((name,i)=>venue.append(option(String(i+1).padStart(2,'0'),name)));
  field(filters,'対象の競艇場',venue);
  const basis=el('select');basis.append(option('frame','出走枠（1〜6号艇）'),option('course','実進入コース（1〜6）'));
  field(filters,'集計する位置',basis);
  const period=el('select');period.append(option('2025','2025年（新しい収録年）'),option('all','2022〜2025年（母数重視）'));
  field(filters,'集計期間',period);
  form.append(filters);
  const grid=el('div','winpath-inputs'),inputs=[];
  for(let i=1;i<=6;i++){
    const card=el('div','winpath-slot');
    card.append(el('div','winpath-slot-title',i+'号艇'));
    const id=el('input');id.type='text';id.inputMode='numeric';id.maxLength=4;id.pattern='[0-9]{4}';id.placeholder='選手登録番号';
    id.setAttribute('aria-label',i+'号艇の選手登録番号');
    card.append(id);
    const course=el('select');course.setAttribute('aria-label',i+'号艇の想定進入コース');
    for(let j=1;j<=6;j++)course.append(option(String(j),j+'コース'));
    course.value=String(i);
    card.append(course);inputs.push({id,course,frame:i});grid.append(card);
  }
  form.append(grid);
  const action=el('button','','勝ち筋を比較する');action.type='submit';form.append(action);
  root.append(form);
  const results=el('section','winpath-results');root.append(results);
  const small=(parent,text)=>parent.append(el('div','muted',text));
  const cell=(label,value,note='')=>{const wrap=el('div','winpath-metric');wrap.append(el('small','',label),el('strong','',value));if(note)wrap.append(el('span','muted',note));return wrap;};
  function renderCard(entry,source){
    const box=el('article','winpath-card');
    const title=el('div','winpath-card-title');
    title.append(el('strong','',entry.frame+'号艇　'+(entry.name||'選手不明')),el('span','',entry.id+' · '+(source.scope.basis==='frame'?'枠':'コース')+' '+entry.lane));
    box.append(title);
    const d=entry.sample,b=entry.baseline;
    if(!d){box.append(el('p','','この条件の実績が未取得です。全国・全期間・別コースを試してください。'));return box;}
    const summary=el('div','winpath-metrics');
    summary.append(cell('1着率',percent(d.winRate),'出走 '+num(d.n)+'回'),cell('2連対率',percent(d.top2Rate)),cell('3連対率',percent(d.top3Rate)),cell('平均ST',d.avgSt===null?'未取得':d.avgSt.toFixed(3)+'秒'));
    box.append(summary);
    if(d.n<10){box.append(el('div','notice','標本が10走未満。偶然の影響が大きいため、傾向を強く判断しないでください。'));}
    const keyStats=el('div','winpath-metrics');
    if(entry.lane===1){
      keyStats.append(cell('逃げ率',percent(d.escapeRate),'本人の逃げ勝利／この位置の全出走'),cell('まくられ率',percent(d.beatenByMakuriRate),'まくり負け／この位置の敗戦 '+num(d.lostCount)+'走'),cell('差され率',percent(d.beatenBySashiRate),'差し・まくり差し負け／敗戦'));
    }else{
      keyStats.append(cell('まくり勝ち率',percent(d.makuriRate)),cell('まくり差し勝ち率',percent(d.makurizashiRate)),cell('差し勝ち率',percent(d.sashiRate)),cell('逃し率',percent(d.escapeAllowedRate),'相手1コースの逃げ成功／全出走'));
      if(source.scope.basis==='course'&&entry.lane===2)keyStats.append(cell('逃がし率',percent(d.nigashiRate),'2コース時の相手1コース逃げ成功'));
    }
    box.append(el('h3','','勝ち方・負け方'),keyStats);
    const base= b&&d.n>=20 ? b : null;
    if(base&&base.n>=100){
      const delta=(d.winRate-base.winRate).toFixed(1);
      const direction=d.winRate>=base.winRate?'+':'';
      box.append(el('p','source','この位置の1着率：本人 '+percent(d.winRate)+'／同じ集計条件の全選手平均 '+percent(base.winRate)+'（差 '+direction+delta+'ポイント）。出走相手の強さ等は補正していません。'));
    }
    const methods=el('details');
    methods.append(el('summary','','決まり手別の内訳（勝利数と率）'));
    const tbl=el('table');tbl.append((()=>{
      const tr=el('tr');['決まり手','1着回数','全出走比','1着内構成比'].forEach(t=>tr.append(el('th','',t)));return tr;
    })());
    d.methods.forEach(m=>{const tr=el('tr');[m.name,num(m.wins),percent(m.perStart),percent(m.amongWins)].forEach(t=>tr.append(el('td','',t)));tbl.append(tr);});
    const wrapper=el('div','table-wrap');wrapper.append(tbl);methods.append(wrapper);box.append(methods);
    const hasSample=d.n>=20;
    if(hasSample){
      const comparisons=d.methods.filter(m=>m.wins>=2).map(m=>{
        const baselineRate=b?.methods?.find(x=>x.name===m.name)?.perStart;
        return {name:m.name,rate:m.perStart,delta:baselineRate===null||baselineRate===undefined?null:m.perStart-baselineRate};
      }).filter(x=>x.delta!==null).sort((a,b)=>b.delta-a.delta);
      if(comparisons.length&&comparisons[0].delta>=3)box.append(el('p','winpath-insight','過去の注目点：'+comparisons[0].name+'勝ち率が同条件の平均より約'+comparisons[0].delta.toFixed(1)+'ポイント高い。'));
    }
    return box;
  }
  form.addEventListener('submit',async e=>{
    e.preventDefault();const selected=inputs.filter(x=>x.id.value.trim());
    results.replaceChildren();
    if(!selected.length){results.append(el('p','empty','最低1艇の登録番号を入力してください。'));return;}
    const ids=selected.map(x=>x.id.value.trim());
    if(ids.some(id=>!/^\d{4}$/.test(id))){results.append(el('p','empty','登録番号は4桁で入力してください。'));return;}
    const frames=selected.map(x=>x.frame);
    const lanes=selected.map(x=>basis.value==='frame'?x.frame:Number(x.course.value));
    const params=new URLSearchParams({ids:ids.join(','),frames:frames.join(','),lanes:lanes.join(','),venue:venue.value,basis:basis.value,period:period.value});
    action.disabled=true;results.append(el('p','loader','選手別データを照合中…'));
    try{
      const data=await get('winpaths?'+params.toString());
      results.replaceChildren();
      results.append(el('p','source','集計範囲：'+data.scope.from+'〜'+data.scope.to+'。分母は各選手の該当条件の出走回数です。'));
      data.rows.forEach(r=>results.append(renderCard(r,data)));
      results.append(el('div','notice',data.note));
      small(results,'用語：1枠／1コースの「まくられ率・差され率」はその位置で敗れたレースを分母にします。「逃し率」は相手の逃げ成功／全出走。「2コース逃がし率」は実進入2コース全出走を分母にします。艇番と進入を混同しません。');
    }catch(err){results.replaceChildren(el('p','empty',err.message||'比較できませんでした。'));}
    finally{action.disabled=false;}
  });
}
