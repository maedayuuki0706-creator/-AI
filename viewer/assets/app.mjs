import {VENUES,NAMES,esc,normalize,num,fixed,pct,jstDate,dayKey,isoDay,validDay,stamp,raceSelection,raceUrl,upcoming,remaining,loadSchedule,loadScheduleSeed,loadCard,loadPrediction,grade,motorEntry,loadMeta,loadDatabase,playersList,playerMatches,loadStats} from './data.mjs';
import {initAnalytics,track} from './analytics.mjs';

const $ = id => document.getElementById(id);
const arrow = '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h16m-6-6 6 6-6 6"/></svg>';
let toastTimer;
export function toast(message) {
  const element = $('toast');
  if (!element) return;
  element.textContent = message; element.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { element.hidden = true; },3500);
}
export function empty(title, message, loading = false) {
  return '<div class="empty-state"><div class="empty-icon"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m3 7 9-4 9 4-9 4Zm0 5 9 4 9-4M3 17l9 4 9-4"/></svg></div><h3>'+esc(title)+'</h3><p>'+esc(message)+'</p>'+(loading ? '<div class="loading-line" aria-hidden="true"></div>' : '')+'</div>';
}
function setContent(target, html) {
  if (target.innerHTML === html) return;
  const focus = typeof target.contains === 'function' && target.contains(document.activeElement) ? document.activeElement?.getAttribute('href') : null;
  target.innerHTML = html;
  if (focus) [...target.querySelectorAll('a[href]')].find(link => link.getAttribute('href') === focus)?.focus({preventScroll:true});
}
const boat = lane => '<span class="boat boat-'+Number(lane)+'">'+Number(lane)+'</span>';
const pill = (text, cls = '') => '<span class="pill '+cls+'">'+esc(text)+'</span>';
function mark(value) {
  const m = grade(value);
  return '<span class="motor-mark mark-'+m.css+'" title="'+esc(m.key ? m.key+'：'+m.label : m.label)+'" aria-label="'+esc(m.key ? m.key+'評価、'+m.label : '未評価')+'">'+esc(m.mark)+'</span>';
}
function title(race, source = '') {
  return '<div class="selection-title"><span class="race-no">'+esc(race.rno)+'R</span><div><h2>'+esc(NAMES.get(race.jcd))+'</h2><p class="meta">'+esc(isoDay(race.day))+' / '+esc(source)+'</p></div></div>';
}
function replaceQuery(query) {
  try { history.replaceState({},'',location.pathname+(query ? '?'+query : '')); } catch (_) {}
}
function options(element, all = false) {
  if (element) element.innerHTML = (all ? '<option value="">全国すべて</option>' : '')+VENUES.map(([code,name]) => '<option value="'+code+'">'+esc(name)+'</option>').join('');
}
function dataError(error) {
  return error?.name === 'AbortError' ? '通信に時間がかかっています。少し待って再度お試しください。' : 'データを取得できませんでした。通信状況を確認して、もう一度お試しください。';
}
function raceCard(race, futureDay = false) {
  return '<a class="deadline-card" href="'+esc(raceUrl('/race/',race))+'" aria-label="'+esc(NAMES.get(race.jcd)+' '+race.rno+'R 締切'+race.deadline+'の出走表')+'"><div class="deadline-top"><time datetime="'+isoDay(race.day)+'T'+race.deadline+':00+09:00">'+esc(race.deadline)+'</time>'+pill(futureDay ? '開催予定' : remaining(race.at),race.at-Date.now() < 600000 && !futureDay ? 'pill-orange' : 'pill-green')+'</div><div class="deadline-venue">'+esc(NAMES.get(race.jcd))+'<b>'+race.rno+'R</b></div><div class="deadline-bottom"><span>出走表をチェック</span>'+arrow+'</div></a>';
}
function dateHeader() {
  const text = jstDate().replaceAll('-','.');
  document.querySelectorAll('[data-today]').forEach(el => { el.innerHTML = text+'<small>JAPAN STANDARD TIME</small>'; });
}
function startSchedule(home = false) {
  let date = home ? jstDate() : isoDay(new URLSearchParams(location.search).get('date')) || jstDate();
  let venue = home ? '' : new URLSearchParams(location.search).get('venue') || '';
  if (!NAMES.has(venue)) venue = '';
  let data = null, requestId = 0, lastCheck = 0, inFlight = false, error = '', automaticallyToday = home || !new URLSearchParams(location.search).has('date');
  const target = home ? $('home-races') : $('race-list'), meta = home ? $('home-schedule-meta') : $('schedule-meta');
  if (!target) return;
  if (!home) {
    $('schedule-day').value = date; options($('schedule-venue'),true); $('schedule-venue').value = venue;
    $('venue-chips').innerHTML = [['','すべて'],...VENUES].map(([code,name]) => '<button class="chip" type="button" data-venue="'+code+'" aria-pressed="'+(code === venue)+'">'+name+'</button>').join('');
  }
  function render() {
    const races = data ? upcoming(data.races).filter(r => !venue || r.jcd === venue) : [];
    const future = date > jstDate();
    if (!home) {
      $('schedule-count').textContent = data ? (venue ? NAMES.get(venue)+' / ' : '')+'締切前 '+races.length+'R'+(data.partial ? '（取得分）' : '') : inFlight ? '締切情報を確認中' : '締切情報を確認できません';
      $('schedule-status').textContent = inFlight ? '更新を確認中' : error ? '取得できませんでした' : data?.partial ? '一部の場に欠測があります' : '締切済みを自動除外';
      document.querySelectorAll('[data-venue]').forEach(b => b.setAttribute('aria-pressed',String(b.dataset.venue === venue)));
    }
    if (!data) setContent(target,empty(inFlight ? 'レース情報を確認中' : '締切情報を取得できませんでした',inFlight ? '公開済みの締切を確認しています。休止中のデータ元は起動に時間がかかる場合があります。' : '非開催と断定せず、取得できない状態として表示しています。情報を更新するか、時間を置いてご確認ください。',inFlight));
    else if (!races.length) setContent(target,empty(data.partial ? '取得済みの範囲に、締切前レースはありません' : '締切前のレースはありません',data.partial ? '一部の開催場を取得できていません。未取得分は表示していません。' : date < jstDate() ? '選択した日付のレースは終了しています。日付を変更してお探しください。' : '開催終了・非開催、または時刻の未公開が考えられます。次の開催情報をお待ちください。'));
    else setContent(target,(home ? races.slice(0,3) : races).map(r => raceCard(r,future)).join(''));
    meta.textContent = data ? data.source+' / '+stamp(data.capturedAt)+(data.partial ? ' / 一部未取得' : '')+(Date.now()-Date.parse(data.capturedAt) > 900000 ? ' / 更新から時間が経っています' : '')+(error ? ' / 最新の確認に失敗' : '') : '当日の時刻を取得するまで、過去のレースは表示しません。';
  }
  async function refresh() {
    const id = ++requestId, requestedDate = date;
    inFlight = true; error = ''; lastCheck = Date.now(); render();
    loadScheduleSeed(dayKey(requestedDate)).then(seed => {
      if (seed && id === requestId && requestedDate === date && !data) { data = seed; render(); }
    });
    try {
      const received = await loadSchedule(dayKey(requestedDate));
      if (id !== requestId || requestedDate !== date) return;
      data = received;
    } catch (e) {
      if (id === requestId) {
        if (!data || data.day !== dayKey(date) || Date.now()-Date.parse(data.capturedAt) > 1800000) data = null;
        error = dataError(e);
      }
    }
    finally { if (id === requestId) { inFlight = false; render(); } }
  }
  function setFilter(update = false) {
    if (!home) {
      const next = $('schedule-day').value;
      if (!validDay(next)) return;
      automaticallyToday = false;
      venue = $('schedule-venue').value;
      if (next !== date) { date = next; data = null; ++requestId; }
      const p = new URLSearchParams({date}); if (venue) p.set('venue',venue); replaceQuery(p.toString());
    }
    if (update || !data) refresh(); else render();
  }
  if (!home) {
    $('schedule-form').addEventListener('submit',e => { e.preventDefault(); setFilter(true); });
    $('schedule-day').addEventListener('change',() => setFilter(true));
    $('schedule-venue').addEventListener('change',() => setFilter(false));
    $('venue-chips').addEventListener('click',e => { const b = e.target.closest('[data-venue]'); if (b) { $('schedule-venue').value = b.dataset.venue; setFilter(false); } });
  }
  function tick() {
    if (document.visibilityState === 'hidden') return;
    if (automaticallyToday && date !== jstDate()) { date = jstDate(); data = null; ++requestId; if (!home) $('schedule-day').value = date; dateHeader(); refresh(); return; }
    // An old date never survives a midnight change as today's schedule.
    if (!inFlight && Date.now()-lastCheck >= 120000) refresh(); else render();
  }
  let interval = setInterval(tick,15000);
  document.addEventListener('visibilitychange',() => { if (document.visibilityState === 'visible') { if (!inFlight) refresh(); tick(); } });
  window.addEventListener('pagehide',() => clearInterval(interval));
  window.addEventListener('pageshow',e => { if (e.persisted) { clearInterval(interval); interval = setInterval(tick,15000); tick(); } });
  refresh();
}
function setupSelector(onSelect) {
  const form = $('race-form'); if (!form) return null;
  const selected = raceSelection(location.search);
  $('race-day').value = selected ? isoDay(selected.day) : jstDate();
  options($('race-venue'));
  $('race-venue').value = selected?.jcd || '01';
  $('race-number').innerHTML = Array.from({length:12},(_,i) => '<option value="'+(i+1)+'">'+(i+1)+'R</option>').join('');
  $('race-number').value = String(selected?.rno || 1);
  form.addEventListener('submit',event => {
    event.preventDefault();
    const p = new URLSearchParams({date:$('race-day').value,venue:$('race-venue').value,race:$('race-number').value});
    const next = raceSelection('?'+p);
    if (!next) { toast('開催日・レース場・レース番号を確認してください。'); return; }
    replaceQuery(p.toString()); onSelect(next);
  });
  // Changing a selector invalidates the previous forecast before another submit.
  form.addEventListener('change',() => onSelect(null));
  return selected;
}
async function homePage() {
  startSchedule(true);
  try {
    const meta = await loadMeta();
    $('home-player-count').textContent = Number(meta.player_count).toLocaleString('ja-JP');
    $('home-motor-count').textContent = Number(meta.motor_count).toLocaleString('ja-JP');
    $('home-db-meta').textContent = 'DB取得 '+stamp(meta.snapshot_at)+' / 収録時点の参考値';
  } catch (_) { $('home-db-meta').textContent = 'データベースの更新日時を確認できませんでした。'; }
}
function racePage() {
  let serial = 0;
  async function show(race) {
    const id = ++serial, target = $('race-content');
    if (!race) { target.innerHTML = empty('レースを選択してください','選択内容を変更した場合は、レースを選択ボタンで確定してください。'); return; }
    target.innerHTML = empty('出走表を確認中',NAMES.get(race.jcd)+' '+race.rno+'R の出走情報を読み込んでいます。',true);
    try {
      const card = await loadCard(race); if (id !== serial) return;
      let html = '<section class="panel">'+title(race,card.source)+'<div class="info-row">'+pill(card.deadline ? '締切 '+card.deadline : '締切未確認')+'<span class="meta">'+esc(stamp(card.captured_at))+'</span></div><div class="detail-actions"><a class="button" href="'+esc(raceUrl('/predictions/',race))+'">このレースのAI予想'+arrow+'</a><a class="button button-outline" href="'+esc(raceUrl('/motors/',race))+'">6艇のモーター比較'+arrow+'</a></div><p class="table-note">表は横にスクロールできます。選手名を押すと選手データへ進みます。</p><div class="table-scroll" tabindex="0" role="region" aria-label="6艇の出走表、横スクロール"><table class="race-table"><thead><tr><th>艇</th><th>選手 / 登録番号</th><th>級別</th><th class="number">全国勝率</th><th class="number">平均ST</th><th class="number">モーター</th><th class="number">2連率</th></tr></thead><tbody>';
      for (const b of card.boats) html += '<tr><td>'+boat(b.lane)+'</td><td>'+(b.racer_id ? '<a class="racer-name" href="/racers/?q='+encodeURIComponent(b.racer_id)+'">'+esc(b.name || '名前未取得')+'</a>' : esc(b.name || '未取得'))+'<div class="small">'+esc(b.racer_id || '登録番号未取得')+'</div></td><td>'+esc(b.current_class || '—')+'</td><td class="number">'+fixed(b.win_rate,2)+'</td><td class="number">'+fixed(b.avg_st,2)+'</td><td class="number">'+(num(b.motor_number) === null ? '—' : '<a class="racer-name" href="/motors/?venue='+race.jcd+'&motor='+num(b.motor_number)+'">'+num(b.motor_number)+'</a>')+'</td><td class="number">'+pct(b.motor_top2_rate)+'</td></tr>';
      html += '</tbody></table></div><p class="table-note">出典：公開済みの公式出走入力・読取専用フィード。取得時点の情報です。欠場・進入・締切変更は公式発表で最終確認してください。</p><button class="text-link" id="race-refresh" type="button">出走表を更新 →</button></section>';
      target.innerHTML = html;
      $('race-refresh').addEventListener('click',async () => { try { await loadCard(race,true); show(race); } catch (error) { toast(dataError(error)); } });
      track('race_detail_view',{date:race.day,venue_code:race.jcd,race_number:race.rno});
    } catch (error) { if (id === serial) target.innerHTML = empty('出走表を取得できませんでした',dataError(error)); }
  }
  const selected = setupSelector(show); if (selected) show(selected);
}
function signalText(signal) {
  let m;
  if ((m = /^course=([\d.]+)\/([\d.]+)$/.exec(signal))) return 'コース1着率 '+m[1]+'%（比較基準 '+m[2]+'%）';
  if ((m = /^motor_rate=([\d.]+)\/([\d.]+)$/.exec(signal))) return 'モーター2連率 '+m[1]+'%（比較値 '+m[2]+'%）';
  if ((m = /^motor_grade=([\d.]+)$/.exec(signal))) return 'モーターの既存評価を参照';
  if ((m = /^method=([\d.]+)$/.exec(signal))) return '決まり手の記録を参照';
  if (/^tuning=/.test(signal)) return '調整・整備の記録を参照';
  return '';
}
export function predictionHtml(prediction) {
  const p = prediction, labels = {balanced:'総合型',probability:'本命型',value:'妙味型',longshot:'高配当型'};
  let html = '<section class="panel">'+title(p,p.version)+'<div class="info-row">'+pill('公開済み','pill-green')+pill(p.deadline ? '締切 '+p.deadline : '締切時刻未取得')+'</div><p class="section-description">生成 '+esc(stamp(p.created_at))+' / '+esc(p.source)+'</p>';
  if (p.afterClose) html += '<p class="notice notice-warning">締切後に保存された予想です。事前に公開された予想としては扱えません。</p>';
  if (!p.created_at) html += '<p class="notice notice-warning">生成日時が未保存です。締切前の原本かを確認できません。</p>';
  html += '<h3 class="section-space">1着推定確率 <span class="small">保存済みのモデル値</span></h3><div class="head-probs">';
  for (let n = 1; n <= 6; n++) html += '<div class="head-prob">'+boat(n)+'<strong>'+(num(p.heads[n]) !== null && num(p.heads[n]) >= 0 && num(p.heads[n]) <= 1 ? pct(num(p.heads[n])*100) : '—')+'</strong></div>';
  html += '</div><p class="table-note">モデルの推定値です。実際の的中頻度としての校正を示すものではありません。</p></section><div class="prediction-grid">';
  for (const [key,c] of Object.entries(p.cards)) {
    const cover = c.cover.filter(x => !c.main.includes(x));
    html += '<article class="prediction-card"><div class="section-header"><h3>'+labels[key]+'</h3>'+pill(c.main.length+cover.length+'点')+'</div><p class="picks-label">本線 / '+c.main.length+'点</p><div class="picks">'+c.main.map(x => '<span class="pick">'+esc(x)+'</span>').join('')+'</div>';
    if (cover.length) html += '<p class="picks-label">抑え / '+cover.length+'点</p><div class="picks">'+cover.map(x => '<span class="pick">'+esc(x)+'</span>').join('')+'</div>';
    html += '</article>';
  }
  html += '</div><section class="panel section-space"><p class="eyebrow">WHY THESE BOATS?</p><h2>根拠・展開の記録</h2>';
  if (p.analysis) html += '<p class="notice">'+esc(p.analysis)+'</p>';
  html += '<ul class="analysis-list">';
  for (let lane = 1; lane <= 6; lane++) {
    const reason = typeof p.reasons[lane] === 'string' ? p.reasons[lane] : '';
    const signals = p.db[lane]?.signals;
    const texts = Array.isArray(signals) ? [...new Set(signals.map(signalText).filter(Boolean))] : [];
    html += '<li>'+boat(lane)+'<div><p>'+esc(reason || (texts.length ? texts.join(' / ') : 'この艇の文章による根拠は、公開原本に保存されていません。'))+'</p>'+(reason && texts.length ? '<small>'+esc(texts.join(' / '))+'</small>' : '')+'</div></li>';
  }
  html += '</ul><p class="table-note">根拠は選択した予想原本に保存された項目だけを表示しています。6艇の勝ち筋・負け筋の文章が未保存の場合、後付けで補いません。</p></section>';
  return html;
}
function predictionPage() {
  let selected = null, serial = 0, busy = false;
  function show(race) {
    selected = race; ++serial; busy = false;
    $('prediction-selection').innerHTML = race ? title(race,'公開状況は予想ボタンで確認') : '';
    $('prediction-content').innerHTML = '';
    $('prediction-open').disabled = !race;
    $('prediction-open').textContent = '予想を見る →';
    $('prediction-status').textContent = race ? 'ボタンを押すと公開状況・生成日時を確認します。' : 'レースを選択ボタンで確定してください。';
  }
  const initial = setupSelector(show); if (initial) show(initial);
  $('prediction-open').addEventListener('click',async () => {
    if (!selected || busy) return;
    const race = selected, id = ++serial; busy = true;
    $('prediction-open').disabled = true;
    $('prediction-status').textContent = '保存済みの予想を確認中…';
    $('prediction-content').innerHTML = empty('予想原本を確認中','選択したレースと一致するデータだけを表示します。',true);
    track('prediction_open',{date:race.day,venue_code:race.jcd,race_number:race.rno,entry_point:'prediction_button'});
    try {
      const prediction = await loadPrediction(race);
      if (id !== serial) return;
      $('prediction-content').innerHTML = predictionHtml(prediction);
      $('prediction-status').textContent = '公開済み / 生成 '+stamp(prediction.created_at);
      $('prediction-open').textContent = '予想を再確認 →';
    } catch (error) {
      if (id !== serial) return;
      const missing = error.status === 404 || /未公開|買い目がありません/.test(error.message);
      $('prediction-content').innerHTML = empty(missing ? 'このレースの予想は未公開です' : '公開状況を確認できませんでした',missing ? '予想原本が公開された後に、もう一度ご確認ください。' : dataError(error));
      $('prediction-status').textContent = missing ? '未公開' : '取得できませんでした（未公開とは区別しています）';
    } finally { if (id === serial) { busy = false; $('prediction-open').disabled = !selected; } }
  });
}

const legend = '<div class="grade-legend"><span><b>◎</b>S 最上位</span><span><b>○</b>A 高評価</span><span><b>△</b>B 標準</span><span><b>注意</b>C 低め</span><span><b>低</b>D 低評価</span><span><b>—</b>未評価</span></div>';
export function motorHtml(entry, jcd, meta, saved = false) {
  const fields = [['伸び','stretch'],['出足','launch'],['回り足','turn'],['行き足','run']];
  return '<div class="motor-result"><section class="motor-summary"><p class="eyebrow">MOTOR / '+esc(jcd)+'</p><h2>'+esc(NAMES.get(jcd))+' No.'+esc(entry.motor)+'</h2><div class="big-grade">'+esc(grade(entry.grade).mark)+'</div><p>総合評価 '+esc(grade(entry.grade).key || '未評価')+' / データベースの記載値</p></section><div class="motor-metrics">'+fields.map(([name,key]) => '<div class="metric"><span>'+name+'</span><div class="metric-value">'+mark(entry[key])+'</div></div>').join('')+'</div><section class="panel motor-reasons"><h3>記録と、評価の根拠</h3><dl class="definition-list">'+[['2連率',pct(entry.top2)],['3連率',pct(entry.top3)],['出走数',num(entry.starts) === null ? '—' : entry.starts+'走'],['勝率',fixed(entry.win,2)],['使用開始',entry.start || '—'],['成績の対象時点',entry.as_of || '—']].map(([k,v]) => '<div><dt>'+k+'</dt><dd>'+esc(v)+'</dd></div>').join('')+'</dl>'+legend+'<p class="notice">総合・各足の印は、既存のS〜D評価の変換です。新しい評価の算出や、未保存の選手コメントの補完はしていません。</p>'+(num(entry.starts) !== null && num(entry.starts) < 10 ? '<p class="notice notice-warning">出走数が少ないため、数値と評価は参考として確認してください。</p>' : '')+'<p class="table-note">出典：競艇AI データベース / モーターデータ<br>DB取得 '+esc(stamp(meta.snapshot_at))+(saved ? ' / 保存済みスナップショット' : '')+'。評価計算の詳細・根拠コメントの原文は、この公開データには未収録です。</p></section></div>';
}
function motorPage() {
  let searchSerial = 0, comparisonSerial = 0;
  options($('motor-venue'));
  const params = new URLSearchParams(location.search), initialJcd = params.get('venue');
  if (NAMES.has(initialJcd)) $('motor-venue').value = initialJcd;
  async function search(jcd, raw, count = true) {
    const number = Number(normalize(raw)), id = ++searchSerial;
    if (!Number.isInteger(number) || number < 1 || number > 999 || !NAMES.has(jcd)) { toast('モーター番号は1〜999で入力してください。'); return; }
    $('motor-status').textContent = 'モーターデータを確認中…';
    $('motor-result').innerHTML = empty('モーター情報を確認中',NAMES.get(jcd)+' No.'+number,true);
    try {
      const {data,meta,saved} = await loadDatabase('motors'); if (id !== searchSerial) return;
      const entry = motorEntry(data,jcd,number);
      $('motor-result').innerHTML = entry ? motorHtml(entry,jcd,meta,saved) : empty('該当するモーターのデータはありません',NAMES.get(jcd)+' No.'+number+' は公開データに未登録です。別の場・番号の値は表示しません。');
      $('motor-status').textContent = 'DB取得 '+stamp(meta.snapshot_at)+(saved ? ' / 保存済み' : '');
      if (count) track('motor_search',{venue_code:jcd,result_count:entry ? 1 : 0});
    } catch (error) { if (id === searchSerial) { $('motor-result').innerHTML = empty('モーター情報を取得できませんでした',dataError(error)); $('motor-status').textContent = '再検索でやり直せます。'; } }
  }
  $('motor-form').addEventListener('submit',e => {
    e.preventDefault();
    const jcd = $('motor-venue').value, no = normalize($('motor-number').value);
    replaceQuery(new URLSearchParams({venue:jcd,motor:no}).toString());
    search(jcd,no);
  });
  $('motor-form').addEventListener('change',() => { ++searchSerial; $('motor-result').innerHTML = ''; $('motor-status').textContent = '検索ボタンで選択内容を確定してください。'; });
  async function compare(race) {
    const id = ++comparisonSerial, target = $('motor-comparison');
    if (!race) { target.innerHTML = empty('比較するレースを選択','開催日・場・レース番号を選んで、レースを選択ボタンを押してください。'); return; }
    target.innerHTML = empty('6艇のモーターを確認中',NAMES.get(race.jcd)+' '+race.rno+'R の出走表と照合しています。',true);
    try {
      const [card,{data,meta,saved}] = await Promise.all([loadCard(race),loadDatabase('motors')]);
      if (id !== comparisonSerial) return;
      const after = Number.isFinite(Date.parse(meta.snapshot_at)) && dayKey(jstDate(new Date(meta.snapshot_at))) > race.day;
      let html = '<section class="panel">'+title(race,'6艇モーター比較')+'<p class="meta">DB取得 '+esc(stamp(meta.snapshot_at))+(saved ? ' / 保存済み' : '')+'</p>';
      if (after) html += '<p class="notice notice-warning">レース日より後に更新された評価です。過去レースの事前予想の検証には使えません。</p>';
      html += '<p class="table-note">横スクロールで各足と対象時点を比較できます。</p><div class="table-scroll" tabindex="0" role="region" aria-label="6艇のモーター比較、横スクロール"><table class="motor-table"><thead><tr><th>艇</th><th>選手 / No.</th><th>総合</th><th>伸び</th><th>出足</th><th>回り足</th><th>行き足</th><th>2連率</th><th>成績時点</th></tr></thead><tbody>';
      for (const b of card.boats) {
        const e = motorEntry(data,race.jcd,b.motor_number,race.day);
        html += '<tr><td>'+boat(b.lane)+'</td><td><strong>'+esc(b.name || '未取得')+'</strong><div class="small">No.'+esc(b.motor_number ?? '—')+'</div></td>'+['grade','stretch','launch','turn','run'].map(f => '<td>'+mark(e?.[f])+'</td>').join('')+'<td>'+pct(e?.top2)+'</td><td class="small">'+esc(e?.as_of || '未照合')+'</td></tr>';
      }
      html += '</tbody></table></div>'+legend+'<p class="table-note">場コードとモーター番号で照合。番号未取得・未登録・使用開始日がレース日より後のものは「—」です。レース直前の足色や進入はこの評価だけでは判断できません。</p><div class="detail-actions"><a class="button button-outline" href="'+esc(raceUrl('/race/',race))+'">出走表へ戻る'+arrow+'</a><a class="button" href="'+esc(raceUrl('/predictions/',race))+'">AI予想を確認'+arrow+'</a></div></section>';
      target.innerHTML = html;
    } catch (error) { if (id === comparisonSerial) target.innerHTML = empty('6艇比較を取得できませんでした',dataError(error)); }
  }
  const initial = setupSelector(compare); if (initial) compare(initial);
  if (NAMES.has(initialJcd) && /^[0-9０-９]{1,3}$/.test(params.get('motor') || '')) {
    $('motor-number').value = params.get('motor'); search(initialJcd,params.get('motor'),false);
  }
}
export function racerHtml(p, meta, saved = false) {
  const methods = [['逃げ',p.escape],['差し',p.sashi],['まくり',p.makuri],['まくり差し',p.makurisashi]];
  const available = methods.filter(([,v]) => num(v) !== null).sort((a,b) => num(b[1])-num(a[1]));
  const most = p.best_method || (available.length && num(available[0][1]) > 0 ? available.filter(x => num(x[1]) === num(available[0][1])).map(x => x[0]).join(' / ')+'（記載割合の比較）' : '未収録');
  let html = '<article class="panel racer-detail"><div class="section-header"><div><p class="eyebrow">RACER / '+esc(p.id)+'</p><h2>'+esc(p.name)+'</h2><p class="small">'+esc(p.branch || '支部未取得')+'</p></div>'+pill(p.class || '級別未取得')+'</div><div class="racer-metrics">'+[['平均ST',fixed(p.avg_st,2)],['勝率',fixed(p.win,2)],['登録番号',p.id]].map(([k,v]) => '<div class="metric"><span>'+k+'</span><div class="metric-value">'+esc(v)+'</div></div>').join('')+'</div><h3>コース別1着率</h3><div class="course-bars">';
  for (let i = 0; i < 6; i++) {
    const value = p.course_win?.[i], valid = num(value) !== null && num(value) >= 0 && num(value) <= 100;
    html += '<div class="course-row" aria-label="'+(i+1)+'コース1着率 '+(valid ? pct(value) : '未取得')+'">'+boat(i+1)+'<div class="course-track" aria-hidden="true"><span style="width:'+(valid ? num(value) : 0)+'%"></span></div><span class="course-value">'+(valid ? pct(value) : '—')+'</span></div>';
  }
  html += '</div><h3>決まり手の割合</h3><div class="method-grid">'+methods.map(([k,v]) => '<div class="method-cell"><span>'+k+'</span><strong>'+pct(v)+'</strong></div>').join('')+'</div><p class="section-description"><strong>最多の決まり手：</strong>'+esc(most)+'</p><h3>過去成績の対象と、データ不足</h3><dl class="definition-list">'+[['対象期間',p.period || '未収録'],['データ対象日',p.as_of || '未収録'],['サンプル数',num(p.sample_count) === null ? '未収録' : p.sample_count+'走'],['レースごとの成績履歴','未収録']].map(([k,v]) => '<div><dt>'+k+'</dt><dd>'+esc(v)+'</dd></div>').join('')+'</dl><p class="notice">— は未登録、0.0%は記載されている数値です。母数と集計期間が分からない項目から、現在の実力や直近の好不調は断定できません。</p><p class="table-note">出典：競艇AI データベース / 選手データ<br>DB取得 '+esc(stamp(meta.snapshot_at))+(saved ? ' / 保存済みスナップショット' : '')+'。掲載された過去集計値であり、当日の成績を保証するものではありません。</p></article>';
  return html;
}
function racerPage() {
  let serial = 0, bundle = null, list = [], matches = [], selected = '';
  const target = $('racer-content'), status = $('racer-status');
  function render() {
    if (!matches.length) { target.innerHTML = empty('一致する選手が見つかりません','名前の一部や登録番号を変更して、お試しください。'); return; }
    const visible = matches.slice(0,30), active = visible.find(p => p.id === selected) || visible[0]; selected = active.id;
    const results = '<aside class="racer-results" aria-label="選手検索結果"><p class="result-count">'+matches.length+'名が一致'+(matches.length > 30 ? ' / 先頭30名を表示' : '')+'</p>'+visible.map(p => '<button type="button" class="racer-result" data-racer-id="'+p.id+'" aria-pressed="'+(p.id === selected)+'"><strong>'+esc(p.name)+'</strong><small>'+p.id+' / '+esc(p.class || '—')+' / '+esc(p.branch || '—')+'</small></button>').join('')+'</aside>';
    target.innerHTML = '<div class="racer-layout">'+results+racerHtml(active,bundle.meta,bundle.saved)+'</div>';
  }
  async function search(count = true) {
    const query = $('racer-query').value.trim(); if (!normalize(query)) return;
    const id = ++serial; selected = '';
    status.textContent = '選手データを確認中…'; target.innerHTML = empty('選手データを確認中','データベースの公開スナップショットを読み込んでいます。',true);
    replaceQuery(new URLSearchParams({q:query}).toString());
    try {
      if (!bundle) { bundle = await loadDatabase('players'); list = playersList(bundle.data); }
      if (id !== serial) return;
      matches = playerMatches(list,query);
      render();
      status.textContent = 'DB '+list.length.toLocaleString('ja-JP')+'名 / '+stamp(bundle.meta.snapshot_at)+(bundle.saved ? ' / 保存済み' : '');
      if (count) track('racer_search',{query_length:normalize(query).length,result_count:matches.length});
    } catch (error) { if (id === serial) { target.innerHTML = empty('選手データを取得できませんでした',dataError(error)); status.textContent = '再検索でやり直せます。'; } }
  }
  $('racer-form').addEventListener('submit',e => { e.preventDefault(); search(); });
  document.querySelectorAll('[data-racer-query]').forEach(button => button.addEventListener('click',() => { $('racer-query').value = button.dataset.racerQuery; search(); }));
  target.addEventListener('click',e => { const b = e.target.closest('[data-racer-id]'); if (b) { selected = b.dataset.racerId; render(); } });
  const q = new URLSearchParams(location.search).get('q');
  if (q && q.length <= 40) { $('racer-query').value = q; search(false); }
}
export function scoreMetrics(row) {
  const judged = num(row.judged), hits = num(row.hits), stake = num(row.stake_yen), returned = num(row.return_yen);
  return {judged,hits,hitRate:judged > 0 && hits !== null && hits >= 0 && hits <= judged ? hits/judged*100 : null,roi:stake > 0 && returned !== null && returned >= 0 ? returned/stake*100 : null,stake,returned,profit:stake !== null && returned !== null ? returned-stake : null};
}
const LABELS = {main:'メインくん',mid_odds:'中穴くん',longshot:'穴くん',hiyori:'日和',prototype1:'PT1',prototype2:'PT2',prototype3:'PT3 / ゆうき',selected:'厳選くん'};
const yen = value => num(value) === null ? '—' : Number(value).toLocaleString('ja-JP')+'円';
export function statsHtml(stats, venue = '') {
  const stream = venue ? stats.venues[venue] : stats.streams;
  if (!stream || !Object.keys(stream).length) return empty('この条件の公開集計はありません','集計のないAI・場を、0%と扱って表示することはありません。');
  const rows = Object.entries(stream).map(([key,row]) => ({key,row,...scoreMetrics(row)})).sort((a,b) => (b.roi ?? -1)-(a.roi ?? -1));
  let html = '<p class="stats-date">対象日 '+esc(isoDay(stats.day))+' / '+esc(venue || '全国')+'</p><div class="stats-cards">';
  for (const m of rows.slice(0,4)) html += '<article class="stats-card"><h3>'+esc(LABELS[m.key] || m.row.label || m.key)+'</h3><p class="roi-value '+(m.roi >= 100 ? 'good-return' : '')+'">'+(m.roi === null ? '—' : fixed(m.roi))+'<small>'+(m.roi === null ? '' : '%')+'</small></p><p class="small">回収率</p><p class="hit-value">的中率 <b>'+pct(m.hitRate)+'</b></p><p class="small">判定 '+(m.judged ?? '—')+'R / 仮想購入</p></article>';
  html += '</div><section class="panel section-space"><div class="section-header"><div><p class="eyebrow">PERFORMANCE TABLE</p><h2>AI別の検証結果</h2></div>'+pill('1点100円')+'</div><p class="table-note">対象レースはAIごとに異なります。横にスクロールして購入額・払戻額まで確認できます。</p><div class="table-scroll" tabindex="0" role="region" aria-label="AI別の仮想購入成績、横スクロール"><table class="score-table"><thead><tr><th>AI</th><th class="number">判定R</th><th class="number">的中</th><th class="number">的中率</th><th class="number">回収率</th><th class="number">仮想購入</th><th class="number">払戻</th><th class="number">収支</th><th class="number">万舟</th><th class="number">トリガミ</th><th class="number">平均点数</th></tr></thead><tbody>';
  for (const m of rows) html += '<tr'+(m.hitRate >= 55 && m.roi >= 100 ? ' class="highlight"' : '')+'><td>'+esc(LABELS[m.key] || m.row.label || m.key)+(m.judged !== null && m.judged < 30 ? '<span class="stats-sample">少数サンプル・参考</span>' : '')+'</td><td class="number">'+(m.judged ?? '—')+'</td><td class="number">'+(m.hits ?? '—')+'</td><td class="number">'+pct(m.hitRate)+'</td><td class="number"><strong>'+pct(m.roi)+'</strong></td><td class="number">'+yen(m.stake)+'</td><td class="number">'+yen(m.returned)+'</td><td class="number">'+yen(m.profit)+'</td><td class="number">'+(num(m.row.manshu) ?? '—')+'</td><td class="number">'+(num(m.row.torigami) ?? '—')+'</td><td class="number">'+fixed(m.row.avg_points)+'</td></tr>';
  html += '</tbody></table></div><p class="table-note">黄色は的中率55%以上かつ回収率100%以上。期間合計ではなく、表示日の集計です。未確定は除外し、トリガミは除外していません。</p><p class="meta">集計更新 '+esc(stamp(stats.generated_at))+(stats.saved ? ' / 保存済みスナップショット' : '')+'</p><p class="notice">仮想購入の検証結果です。実際の利益・今後の成績を示すものではありません。万舟はAI別の的中数のため、AI間で同じレースが重複します。</p><a class="text-link section-space" href="/lab/method/">集計方法と比較の読み方'+arrow+'</a></section>';
  return html;
}
function labPage() {
  let serial = 0, stats = null;
  const target = $('stats-content'), status = $('stats-status');
  options($('stats-venue'),true); $('stats-venue').options[0].textContent = '全国集計';
  function render() { if (stats) target.innerHTML = statsHtml(stats,NAMES.get($('stats-venue').value) || ''); }
  async function load(date = '') {
    const id = ++serial;
    status.textContent = '公開済みの成績を確認中…'; target.innerHTML = empty('成績を確認中','対象日の公開集計を読み込んでいます。',true);
    try {
      const data = await loadStats(date); if (id !== serial) return;
      stats = data; $('stats-day').value = isoDay(data.day);
      status.textContent = (data.saved ? '保存済み / ' : '')+'1点100円・配信済み予想・未確定除外 / '+stamp(data.generated_at);
      render();
    } catch (error) { if (id === serial) { stats = null; target.innerHTML = empty('この日付の成績を確認できませんでした','公開集計がない場合と通信できない場合があります。別の日付の成績を代入せずに表示しています。'); status.textContent = dataError(error); } }
  }
  $('stats-form').addEventListener('submit',e => { e.preventDefault(); load($('stats-day').value); });
  $('stats-venue').addEventListener('change',render);
  $('stats-latest').addEventListener('click',() => load());
  load();
}
export function boot() {
  dateHeader(); initAnalytics(toast);
  document.querySelectorAll('[data-share]').forEach(button => button.addEventListener('click',async () => {
    const url = new URL(location.pathname,location.origin);
    const params = new URLSearchParams(location.search);
    for (const key of ['date','venue','race','motor']) if (params.has(key)) url.searchParams.set(key,params.get(key));
    try {
      if (navigator.share) await navigator.share({title:document.title,url:url.href});
      else { await navigator.clipboard.writeText(url.href); toast('ページのURLをコピーしました。'); }
    } catch (error) { if (error.name !== 'AbortError') toast('共有できませんでした。アドレス欄のURLをコピーしてください。'); }
  }));
  const page = document.body.dataset.page;
  // Preserve old shared links to the original one-page viewer.
  if (page === 'home' && raceSelection(location.search)) { location.replace(raceUrl('/race/',raceSelection(location.search))); return; }
  const pages = {home:homePage,races:() => startSchedule(false),race:racePage,predictions:predictionPage,motors:motorPage,racers:racerPage,lab:labPage};
  try { pages[page]?.(); }
  catch (_) { toast('表示の準備に失敗しました。ページを再読み込みしてください。'); }
}

if (typeof document !== 'undefined' && typeof window !== 'undefined' && !globalThis.NAVI_TEST_MODE) boot();
