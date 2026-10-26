"""Generate crawlable static pages. No server, credentials, upstream writes or paid dependencies.

python viewer/build_pages.py
python viewer/build_pages.py --output /absolute/preview/dist --preview --origin https://...
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import re
import shutil
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
PRODUCTION = "https://boat-ai-readonly-view.onrender.com"
PATHS = {
    "home": ("/", "ホーム", "home"),
    "races": ("/races/", "レース一覧", "flag"),
    "predictions": ("/predictions/", "AI予想", "spark"),
    "motors": ("/motors/", "モーター", "motor"),
    "racers": ("/racers/", "選手データ", "user"),
    "analysis": ("/analysis/", "データ分析", "chart"),
    "lab": ("/lab/", "AI成績・研究室", "lab"),
}
ICONS = {
    "home": '<path d="m3 10 9-7 9 7v10H3Z"/><path d="M9 20v-7h6v7"/>',
    "flag": '<path d="M5 21V4m0 0h14l-3 5 3 5H5"/><path d="M9 4v10m5-10v10M5 9h14"/>',
    "spark": '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z"/><path d="M19 2v4m-2-2h4"/>',
    "motor": '<path d="M8 6h8v11H8zM6 9H3v6h5m8-6h4v8h-4m-5-14h5m-3 0v3m-3 11v4h7m0 0v-4"/><path d="M11 10h2m-2 3h2"/>',
    "user": '<circle cx="12" cy="7" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2M8 21h8"/>',
    "chart": '<path d="M4 21V3M4 21h17M8 17v-5m5 5V7m5 10v-9"/>',
    "lab": '<path d="M9 3h6m-5 0v7L4 20a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1l-6-10V3M8 15h8"/><path d="M10 18h.01M14 17h.01"/>',
    "arrow": '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    "share": '<path d="M12 16V3m-4 4 4-4 4 4M5 12v9h14v-9"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "search": '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
    "refresh": '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M5 8a8 8 0 0 1 13-3l2 3M4 16l2 3a8 8 0 0 0 13-3"/>',
    "layers": '<path d="m3 7 9-4 9 4-9 4Zm0 5 9 4 9-4M3 17l9 4 9-4"/>',
}


def icon(name: str) -> str:
    return '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">' + ICONS[name] + "</svg>"


ARROW = icon("arrow")


def heading(number: str, english: str, title: str, description: str) -> str:
    return f'<div class="page-heading"><div><p class="eyebrow">{english}</p><h1>{title}</h1><p>{description}</p></div><span class="page-number" aria-hidden="true">{number}</span></div>'


def empty(title: str, description: str, loading: bool = False) -> str:
    return f'<div class="empty-state"><div class="empty-icon">{icon("layers")}</div><h3>{title}</h3><p>{description}</p>' + ('<div class="loading-line" aria-hidden="true"></div>' if loading else '') + '</div>'


def section_header(en: str, title: str, link: str = "", label: str = "") -> str:
    return f'<div class="section-header"><div><p class="eyebrow">{en}</p><h2>{title}</h2></div>' + (f'<a class="text-link" href="{link}">{label}{ARROW}</a>' if link else '') + '</div>'


def selector() -> str:
    return f'''<form id="race-form" class="panel filter-panel">
<div class="filter-row four"><label>開催日<input type="date" id="race-day" required aria-label="開催日"></label>
<label>レース場<select id="race-venue" required aria-label="レース場"></select></label><label>レース<select id="race-number" required aria-label="レース番号"></select></label>
<button class="button" type="submit">レースを選択{ARROW}</button></div>
<p class="form-help">全国のレースを探すなら、<a class="text-link" href="/races/">締切順のレース一覧へ →</a></p></form>'''


RESEARCH = [
    ("six-boat", "01", "SCENARIO", "6艇すべてに、勝ち筋と負け筋を。", "攻めの起点、他艇の反応、2着・3着への連動を順に考える。"),
    ("manshu", "02", "HIGH PAYOUT", "万舟を、結果だけで終わらせない。", "風・進入・足色。事前に見えていた材料と、見えていなかった材料を分ける。"),
    ("method", "03", "VERIFICATION", "的中率と回収率を、同じ目線で。", "点数・購入額・判定数をそろえて、予想の強みと課題を確かめる。"),
]


def research_cards() -> str:
    return '<div class="research-grid">' + ''.join(
        f'<a class="research-card" href="/lab/{slug}/"><div class="research-symbol">{number}</div><p class="eyebrow">{en}</p><h3>{title}</h3><p>{desc}</p><span class="text-link">研究ノートを読む{ARROW}</span></a>'
        for slug, number, en, title, desc in RESEARCH
    ) + '</div>'


HOME = f'''
<section class="hero" aria-labelledby="home-title"><div class="hero-copy"><p class="eyebrow">EVERY RACE HAS A STORY.</p>
<h1 id="home-title">そのレースを、<br><span>もっと深く。</span></h1>
<p class="hero-description">レースも、モーターも、選手も。<br>データとAIで、ボートレースの見方が変わる。</p>
<div class="hero-actions"><a class="button button-lime" href="/races/">今日のレースを探す{ARROW}</a><a class="text-link" href="/lab/">AIの成績を見る{ARROW}</a></div></div>
<div class="hero-art" aria-hidden="true"><div class="race-orbit"><div class="orbit-core"></div></div><div class="art-label"><b>RACE.</b><b>DATA.</b><b>INSIGHT.</b><small>6 BOATS. COUNTLESS STORIES.</small></div></div></section>
<div class="hero-footer"><span>自分の見たい情報へ。競艇ファンのためのデータナビ。</span><div class="six-dots" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i></div></div>
<section class="section" aria-labelledby="next-title">{section_header("UPCOMING RACES", '<span id="next-title">次のレースへ。</span>', "/races/", "すべてのレース")}
<div id="home-races" class="deadline-grid" aria-live="polite">{empty("締切情報を確認中", "開催が確認できたレースを、締切時刻の早い順に表示します。", True)}</div>
<p id="home-schedule-meta" class="deadline-meta">全国24場のうち、取得できた開催場が対象です。</p></section>
<section class="section">{section_header("EXPLORE", "知りたいことから、選ぼう。")}
<div class="entry-grid">''' + ''.join(
    f'<a class="entry-card" href="{path}"><div class="entry-top">{icon(name)}<span class="eyebrow">{i:02}</span></div><p class="eyebrow">{en}</p><h3>{title}</h3><p>{description}</p><span class="entry-arrow">{ARROW}</span></a>'
    for i, (path, name, en, title, description) in enumerate([
        ("/races/", "flag", "RACE SCHEDULE", "全国のレース", "締切が近いレースから。<br>気になる出走表をチェック。"),
        ("/predictions/", "spark", "AI PREDICTIONS", "AI予想", "買い目と、その根拠。<br>選んだレースをじっくり読む。"),
        ("/motors/", "motor", "MOTOR ANALYSIS", "モーターを知る", "伸び・出足・回り足・行き足。<br>6艇の違いを比較する。"),
        ("/racers/", "user", "RACER DATABASE", "選手を調べる", "得意コースと決まり手。<br>数字から選手の個性を探る。"),
        ("/analysis/", "chart", "DATA ANALYSIS", "結果・コース分析", "収録済み公式結果を条件検索。<br>万舟の傾向と選手コース実績を探る。"),
    ], 1)
) + f'''</div></section>
<section class="home-lower"><a class="lab-feature" href="/lab/"><p class="eyebrow">BOAT AI LAB</p><h2>的中の、その先まで。</h2><p>当たった理由も、外れた理由も。<br>的中率だけに寄らず、回収率と展開から予想を検証する。</p><!--home-latest--><span class="text-link">AI成績・研究室へ{ARROW}</span><div class="lab-lines" aria-hidden="true"></div></a>
<div><div class="section-header"><div><p class="eyebrow">RESEARCH NOTES</p><h2>レースを見る、もう一つの目。</h2></div></div><div class="research-links">''' + ''.join(
    f'<a class="research-link" href="/lab/{slug}/"><span class="article-no">{number}</span><div><h3>{title}</h3><p>{en} / 研究の考え方</p></div>{ARROW}</a>'
    for slug, number, en, title, desc in RESEARCH
) + '''</div></div></section>
<aside class="db-strip" aria-label="データの収録情報"><div><strong>データで、観戦をもっと面白く。</strong><p class="meta" id="home-db-meta">データベースの更新日時を確認中</p></div><div class="db-numbers"><span><b id="home-player-count">—</b>選手</span><span><b id="home-motor-count">—</b>モーター</span></div></aside>
'''

RACES = heading("01", "RACE SCHEDULE", "レースを、探す。", "全国24場の開催レースを、締切時刻の早い順に。気になるレースから、出走表へ進めます。") + f'''
<form class="panel filter-panel" id="schedule-form"><div class="filter-row"><label>開催日<input type="date" id="schedule-day" required></label><label>レース場<select id="schedule-venue"><option value="">全国すべて</option></select></label><button type="submit" class="button button-outline">{icon("refresh")}情報を更新</button></div><p class="form-help">締切を過ぎたレースは自動で一覧から外れます。時刻は日本時間（JST）です。</p></form>
<div id="venue-chips" class="venue-chips" role="group" aria-label="レース場の絞り込み"></div>
<div class="list-toolbar"><strong id="schedule-count">締切情報を確認中</strong><span id="schedule-status" role="status">公開済みの時刻だけを表示</span></div>
<div id="race-list" class="race-list" aria-live="polite">{empty("レース情報を確認中", "取得に時間がかかる場合があります。", True)}</div><p id="schedule-meta" class="deadline-meta"></p>
<details class="panel analysis-details section-space"><summary>表示されないレースについて</summary><p class="section-description">締切が未公開、情報の取得に失敗、または開催終了の場合は表示しません。データを取得できない状態と非開催は区別して表示します。日程の変更・中止を含め、最新情報は公式発表でご確認ください。</p></details>
'''

RACE = heading("", "RACE CARD", "出走表", "6艇の顔ぶれと基本データを確認。気になる選手やモーターへ、そのまま進めます。") + selector() + f'''
<div id="race-content" class="section min-content" aria-live="polite">{empty("レースを選択してください", "レース一覧、または上の開催日・場・レース番号から選べます。")}</div>'''

PREDICTIONS = heading("02", "AI PREDICTIONS", "予想を、読み解く。", "買い目だけでなく、選ばれた理由まで。見たいレースを選んでから、AI予想を開いてください。") + selector() + f'''
<div id="prediction-selection" class="section"></div>
<section class="optin-panel" aria-labelledby="prediction-gate-title"><p class="eyebrow">YOUR RACE. YOUR CHOICE.</p><h2 id="prediction-gate-title">気になるレースの、その先へ。</h2><p>「予想を見る」を押すと、保存済みのAI予想・買い目・公開されている根拠を表示します。</p>
<button class="button button-lime" type="button" id="prediction-open" disabled>{icon("spark")}予想を見る{ARROW}</button><p class="meta" id="prediction-status" role="status">まずレースを選んでください。</p></section>
<div id="prediction-content" class="section" aria-live="polite"></div>
<p class="table-note">予想は参考情報です。生成後に出走条件やオッズが変わる場合があります。未公開・未取得のデータを推測して補いません。</p>
'''

MOTORS = heading("03", "MOTOR ANALYSIS", "足の違いを、見つける。", "伸び・出足・回り足・行き足。モーター番号から、選択レースの6艇比較から、気になる足を調べよう。") + f'''
<section aria-labelledby="motor-search-title"><h2 id="motor-search-title" class="small">場とモーター番号で検索</h2><form class="panel filter-panel section-space" id="motor-form"><div class="filter-row motor-search"><label>レース場<select id="motor-venue" required></select></label><label>モーター番号<input id="motor-number" type="text" inputmode="numeric" pattern="[0-9０-９]{{1,3}}" placeholder="例：12" required maxlength="3"></label><button class="button" type="submit">{icon("search")}モーターを検索</button></div><p class="form-help">総合評価 S＝◎ / A＝○ / B＝△ / C＝注意 / D＝低。既存の評価を表示用の印に変換しています。</p></form>
<div id="motor-result" aria-live="polite"></div><p class="inline-status" id="motor-status" role="status"></p></section>
<section class="section">{section_header("SIX-BOAT COMPARISON", "6艇のモーターを、比べる。")}''' + selector() + f'''<div id="motor-comparison" class="section-space" aria-live="polite">{empty("比較するレースを選択", "出走表から来た場合は、そのレースの6艇を比較します。")}</div></section>
'''

RACERS = heading("04", "RACER DATABASE", "数字から、選手を知る。", "コース別1着率、平均スタートタイミング、決まり手。選手名や登録番号で、その選手の特徴を探せます。") + f'''
<form class="panel filter-panel" id="racer-form"><div class="filter-row search-row"><label>選手名・登録番号<input id="racer-query" type="search" placeholder="例：毒島誠、4238" maxlength="40" autocomplete="off" required></label><button class="button" type="submit">{icon("search")}検索</button></div>
<div class="search-suggestions"><span>気になる選手から</span><button type="button" class="chip" data-racer-query="毒島誠">毒島 誠</button><button type="button" class="chip" data-racer-query="茅原悠紀">茅原 悠紀</button><button type="button" class="chip" data-racer-query="守屋美穂">守屋 美穂</button></div></form>
<p id="racer-status" class="inline-status" role="status">名前の一部・全角の登録番号でも検索できます。</p><div id="racer-content" class="min-content" aria-live="polite">{empty("知りたい選手を検索", "検索するまで選手データは読み込みません。")}</div>
'''

LAB = heading("05", "BOAT AI LAB", "予想を、検証する。", "的中率と回収率、場ごとの相性、万舟の手がかり。結果を積み重ねて、次のレースの見方へつなげる研究室。") + f'''
<div class="panel lab-intro"><div><p class="eyebrow">OPEN DATA. HONEST RESULTS.</p><h2>いい数字も、課題も、そのまま。</h2><p>配信済みの予想を1点100円で仮想購入した公開集計です。対象日・判定数・購入額をそろえ、条件が違う成績は混ぜません。</p></div><div class="lab-badge" aria-hidden="true">{icon("lab")}</div></div>
<form id="stats-form" class="stats-controls"><label>対象日<input type="date" id="stats-day"></label><label>場別で見る<select id="stats-venue"><option value="">全国集計</option></select></label><button class="button button-outline" type="submit">集計を見る{ARROW}</button><button class="text-link" type="button" id="stats-latest">最新の集計へ →</button></form>
<p id="stats-status" class="inline-status" role="status">公開済みの成績を確認中</p><div id="stats-content" class="section-space" aria-live="polite">{empty("公開成績を確認中", "未確定のレースは成績から除外します。", True)}</div>
<section class="section">{section_header("RESEARCH NOTES", "レースの奥行きを、深掘り。")}{research_cards()}</section>
<section class="section panel"><p class="eyebrow">RESEARCH LOG</p><h2>勝ち筋・負け筋の記録</h2><p class="section-description">公開するLOGは、事前に保存した根拠と結果の区別、公開範囲、個人情報の有無を確認したものに限ります。公開用の展開LOGは現在準備中です。</p><p class="table-note">公開されていない研究記録や、未検証の確率・期待値は掲載しません。</p></section>
'''

ARTICLES = {
    "six-boat": ("SCENARIO / RESEARCH NOTE", "6艇すべてに、勝ち筋と負け筋を。", "誰が勝つかの前に、誰がどう攻めるかを。", '''
<h2>1号艇から6号艇まで、一度は頭に置く</h2><p>インが強いレースでも、外の艇に勝つ道がまったくないとは限りません。各艇を1着と仮定して、どんなスタート、進入、足色、ターンなら成立するかを順に考えます。根拠が足りない筋は、可能性と確認済みの事実を分けて残します。</p>
<h2>攻めた艇と、展開を受ける艇</h2><p>まくり、差し、まくり差しでは、空く水面や残りやすい艇が変わります。攻めの起点を置いたら、内艇が抵抗するか、外艇が連動するかまで進め、2着・3着の候補につなげます。</p>
<div class="table-scroll" tabindex="0" role="region" aria-label="展開を考える順序"><table><thead><tr><th>見る順序</th><th>確認すること</th></tr></thead><tbody><tr><td>進入・起こし</td><td>想定コース、深さ、助走距離</td></tr><tr><td>攻めの入口</td><td>平均ST・今節の足・選手の得意な攻め</td></tr><tr><td>内艇の反応</td><td>先マイ、抵抗、差し場の有無</td></tr><tr><td>外艇の連動</td><td>追走、差し抜け、引き波の影響</td></tr><tr><td>負け筋</td><td>想定した攻めが成立しない条件</td></tr></tbody></table></div>
<h2>「足がいい」から、その先へ</h2><p>伸びがよければ攻めの入口を作れるか。出足がよければターン後に残れるか。モーターの数字だけで結論を出さず、相手関係と水面条件に結びつけて読みます。</p>
<h2>事前の仮説と、事後の検証を分ける</h2><p>レース後の情報で事前予想を書き換えず、保存した仮説と実際の動きを照合します。的中しても想定と違う展開なら、その違いが次の研究材料になります。</p>
<p class="notice">このノートは分析の考え方です。すべての公開予想に6艇分の展開分析が保存されていることを示すものではありません。</p>
'''),
    "manshu": ("HIGH PAYOUT / RESEARCH NOTE", "万舟を、結果だけで終わらせない。", "事前に見えていた材料へ、戻って考える。", '''
<h2>高配当の結果と、狙えた根拠は別</h2><p>人気薄が勝ったという結果だけで、予想できたとは言えません。展示、進入、風や波、選手のスタート傾向など、締切前に確認できた情報から筋道を作れたかを振り返ります。</p>
<h2>見るのは、攻めが生まれる組み合わせ</h2><p>内側のスタートが遅れ、外側に攻められる艇がいる。進入の変化で助走や隊形が変わる。水面条件がターンや足の差を大きくする。一つの指標に決めつけず、攻めの入口と連動する艇を探します。</p>
<h2>取れた万舟も、取れなかった万舟も</h2><p>的中したレースだけを集めると、根拠の強さを見誤ります。事前に警戒したが荒れなかったレース、警戒できず高配当になったレースも同じ条件で比較し、対象数と再現性を確かめます。</p>
<h2>事故と、読み違いを分ける</h2><p>事故や失格が絡んだ結果と、通常の攻防から生まれた結果を区別します。後者では、どの艇の勝ち筋、どの艇の負け筋を見落としたかを言葉で残します。</p>
<p class="notice">万舟は3連単100円あたりの払戻が10,000円以上となるレースを指します。成績表の「万舟」は、各AIが的中した件数です。</p>
'''),
    "method": ("VERIFICATION / RESEARCH NOTE", "的中率と回収率を、同じ目線で。", "同じ条件で比べると、見えてくることがある。", '''
<h2>的中率は、当たったレースの割合</h2><p>的中率は「的中したレース数 ÷ 判定対象レース数 × 100」で見ます。買い目の点数が増えれば当たりやすさも変わるため、平均点数や購入額も一緒に確認します。未確定のレースは判定対象に含めません。</p>
<h2>回収率は、購入額に対していくら戻ったか</h2><p>回収率は「払戻総額 ÷ 仮想購入総額 × 100」です。このサイトの成績は公開集計の1点100円ルールに基づく仮想購入で、実際の入出金記録ではありません。集計がない場合や購入額が0円の場合は、0%と扱わず未集計と表示します。</p>
<h2>的中しても、収支がマイナスのことがある</h2><p>払戻がそのレースの購入額を下回る状態がトリガミです。的中の有無と、収支がプラスかどうかは別々に確認します。標準の成績では、トリガミを除外せず表示します。</p>
<h2>対象の違いを、隠さない</h2><p>AIごとに配信対象が異なる場合、全国集計でも比較しているレースは一致しません。対象日、場、判定数、平均点数を見てください。短い期間や少ないサンプルの好成績だけで、将来の優位性を判断することはできません。</p>
<h2>表示のルール</h2><p>的中率55%以上かつ回収率100%以上の行を黄色で強調します。これは表示上の基準であり、推奨購入や将来の利益を示すものではありません。</p>
'''),
}

SOURCES = heading("", "SOURCES & METHODOLOGY", "出典と、表示のルール。", "データの出どころと、どのように表示しているか。") + '''
<article class="article-body"><h2>このサイトについて</h2><p>競艇AIナビは独立した情報サイトです。BOAT RACE公式サイトや各レース場の公式サービスではありません。</p>
<h2>出典</h2><ul><li>開催・締切・出走表：BOAT RACE公開情報を基にした、既存の読取専用フィード・保存データ。</li><li>モーター・選手データ：競艇AI データベースの公開用スナップショット。各画面に取得日時とデータの対象時点を表示。</li><li>AI予想：公開リポジトリに保存された予想原本。選択レースと一致するものだけを表示。</li><li>AI成績：配信済み予想を1点100円で仮想購入した公開集計。未確定は除外。</li><li>研究ノート：当サイトが編集した分析方法の説明。個別レースの事前原本とは区別。</li></ul>
<h2>最新性とデータ不足</h2><p>情報には更新の遅れがあります。未取得・未評価は「—」、予想原本がない場合は「未公開」と表示し、別の日付・別レースの値で補いません。モーター評価は表示時点のスナップショットで、過去レースの事前評価とは限りません。</p>
<h2>利用条件について</h2><p>BOAT RACEのサイトポリシーでは、コンテンツの権利、許諾の範囲、リンクの条件、大量アクセス等の禁止事項が定められています。出典を示すことだけで転載・再配布・商用利用の許諾が得られるわけではありません。元情報の利用条件と権利者の許諾範囲は、一般公開・広告導入の前に運営側で確認します。</p>
<p><a href="https://www.boatrace.jp/owpc/pc/extra/policy.html" target="_blank" rel="noopener noreferrer">BOAT RACE サイトポリシー（出典・利用条件の確認先）</a></p>
<h2>予想と成績</h2><p>予想は的中や利益を保証するものではありません。未校正の確率を新しく作ったり、データのないレースに買い目を補ったりしません。成績は対象日と母数を明示し、累積成績として読み替えません。</p>
<h2>公開する研究情報</h2><p>研究記録の公開は確認済みの範囲に限ります。内部の記録、認証情報、配信先、個人情報は掲載しません。</p></article>
'''

PRIVACY = heading("", "PRIVACY & ANALYTICS", "プライバシーと解析設定。", "見たい情報を、安心して探せるように。") + '''
<article class="article-body"><h2>アクセス解析の状態</h2><p id="analytics-state">Google Analyticsは初期状態では無効です。計測IDの設定と運営側での有効化が行われるまで、Googleの計測タグを読み込みません。</p>
<h2>計測を有効にした場合</h2><p>改善のため、ページ閲覧、レース詳細の表示、予想ボタン、モーター検索、選手検索、Xからの流入を計測する準備があります。解析を許可するまではGoogleのタグを読み込まず、許可前の操作は送信しません。検索文字列そのものはイベントに含めません。</p>
<p>広告用の保存・広告パーソナライズ・広告へのユーザーデータ送信は許可しない設定です。広告や課金の機能は導入していません。</p>
<h2>このブラウザに保存する情報</h2><p>解析を設定した場合、解析の許可・拒否の選択をこのブラウザに保存します。確認済みの開催締切表を同じタブでの再表示のために一時保存し、古い日付や期限を過ぎた保存データは再利用しません。検索結果はページを閉じるまでのメモリに保持します。会員登録や氏名・連絡先の入力は求めません。</p>
<h2>選択を変更する</h2><p>下のボタンから解析の設定を確認できます。拒否しても、すべての閲覧・検索機能を利用できます。</p>
<button type="button" class="button button-outline" data-consent-settings>アクセス解析の設定を開く</button>
<h2>データの取得先</h2><p>閲覧に必要な情報を、公開済みデータの配信元から取得します。データ提供元やホスティング事業者が通信に必要な情報を処理する場合があります。</p>
<p><a href="https://policies.google.com/privacy?hl=ja" target="_blank" rel="noopener noreferrer">Googleのプライバシーポリシー</a></p></article>
'''

PAGES = {
    "/": ("home", "競艇AIナビ｜レース・AI予想・モーター・選手データ", "レースも、モーターも、選手も。全国24場の締切情報、保存済みAI予想、モーター評価、選手データ、AI成績と研究を見たい情報から探せます。", HOME),
    "/races/": ("races", "全国24場のレース一覧・締切順｜競艇AIナビ", "全国24場の開催レースを締切時刻順に表示。締切済みを自動除外し、気になるレースの出走表へ進めます。", RACES),
    "/race/": ("race", "レース出走表・6艇データ｜競艇AIナビ", "選択レースの6艇の出走表、平均ST、モーターを確認。選手データ、モーター比較、AI予想へ進めます。", RACE),
    "/predictions/": ("predictions", "AI予想・買い目と根拠｜競艇AIナビ", "選んだレースの保存済みAI予想をボタンで表示。買い目、生成日時、公開状況、公開されている根拠を確認できます。", PREDICTIONS),
    "/motors/": ("motors", "モーター情報・足の評価と6艇比較｜競艇AIナビ", "場・モーター番号で検索。総合、伸び、出足、回り足、行き足の既存評価と2連率、更新日時を表示し6艇を比較します。", MOTORS),
    "/racers/": ("racers", "選手データ検索・コース別1着率と平均ST｜競艇AIナビ", "選手名・登録番号で検索し、1〜6コース1着率、平均ST、決まり手と過去成績の公開スナップショットを確認。", RACERS),
    "/lab/": ("lab", "AI成績・研究室｜的中率・回収率・万舟研究｜競艇AIナビ", "AI別・場別の的中率と回収率を対象日・判定数付きで確認。1点100円の仮想購入集計と展開・万舟の研究ノートを公開。", LAB),
    "/sources/": ("sources", "データの出典と表示ルール｜競艇AIナビ", "競艇AIナビのデータ出典、更新日時、欠測の扱い、モーター評価の変換、公開情報の利用条件と研究情報の表示ルール。", SOURCES),
    "/privacy/": ("privacy", "プライバシー・アクセス解析設定｜競艇AIナビ", "アクセス解析の状態と、同意設定、データの取扱いについて。解析は初期状態で無効、拒否しても閲覧できます。", PRIVACY),
}
for slug, (en, title, desc, body) in ARTICLES.items():
    article = '<div class="article">' + heading("", en, title, desc) + '<p class="article-meta">編集ノート / 分析の考え方 · 2026.10.19</p><article class="article-body section-space">' + body + '<a class="button" href="/lab/">AI成績・研究室に戻る →</a></article></div>'
    PAGES[f"/lab/{slug}/"] = ("lab-article", title + "｜競艇AIナビ", desc, article)


def render(path: str, page: tuple, origin: str, preview: bool, verification: str) -> str:
    key, title, description, body = page
    if key == "home":
        try:
            stats = json.loads((ROOT / "data/public/stats.json").read_text(encoding="utf-8"))
            day = stats["day"]
            latest = f'保存済み公開成績：{day[:4]}.{day[4:6]}.{day[6:8]} / {len(stats["streams"])}系統のAI'
            body = body.replace("<!--home-latest-->", f'<p class="section-description">{html.escape(latest)}</p>')
        except (OSError, ValueError, KeyError):
            body = body.replace("<!--home-latest-->", "")
    current = "races" if key == "race" else "lab" if key == "lab-article" else key
    nav = ''.join(f'<a class="nav-link" href="{url}"' + (' aria-current="page"' if name == current else '') + f'>{icon(symbol)}<span>{label}</span></a>' for name, (url, label, symbol) in PATHS.items())
    robot = "noindex, nofollow" if preview else "noindex, follow" if key in {"race", "404"} else "index, follow"
    canonical = origin.rstrip("/") + path
    schema = {"@context": "https://schema.org", "@type": "WebSite" if key == "home" else "WebPage", "name": title, "description": description, "url": canonical, "inLanguage": "ja"}
    verification_meta = f'<meta name="google-site-verification" content="{html.escape(verification, quote=True)}">' if verification and not preview else ""
    breadcrumb = "" if key == "home" else f'<nav class="breadcrumb" aria-label="パンくず"><a href="/">ホーム</a><span aria-hidden="true">/</span>' + ('<a href="/lab/">研究室</a><span aria-hidden="true">/</span>' if key == "lab-article" else '') + f'<span>{html.escape(title.split("｜")[0])}</span></nav>'
    return f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#10273e"><title>{html.escape(title)}</title><meta name="description" content="{html.escape(description, quote=True)}">
<meta name="robots" content="{robot}"><link rel="canonical" href="{canonical}">{verification_meta}
<meta property="og:type" content="website"><meta property="og:locale" content="ja_JP"><meta property="og:site_name" content="競艇AIナビ">
<meta property="og:title" content="{html.escape(title, quote=True)}"><meta property="og:description" content="{html.escape(description, quote=True)}"><meta property="og:url" content="{canonical}">
<meta property="og:image" content="{origin}/assets/og.png"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta property="og:image:alt" content="競艇AIナビ — RACE. DATA. INSIGHT.">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{html.escape(title, quote=True)}"><meta name="twitter:description" content="{html.escape(description, quote=True)}"><meta name="twitter:image" content="{origin}/assets/og.png">
<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/assets/site.css?v=20261019">
<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False).replace("<", "&lt;")}</script>
<script src="/assets/site-config.js"></script><script type="module" src="/assets/app.mjs?v=20261019"></script></head>
<body data-page="{key}"><a class="skip" href="#main">本文へ進む</a>
<header class="site-header"><div class="wrap"><div class="masthead"><a class="brand" href="/" aria-label="競艇AIナビ ホーム"><span class="brand-symbol" aria-hidden="true"><svg viewBox="0 0 30 30" fill="none"><path d="m4 20 7-12 5 9 5-9 5 12M4 25h22" stroke="currentColor" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span class="brand-name">競艇AIナビ<span class="brand-en">BOAT RACE · DATA & INSIGHT</span></span></a>
<div class="header-aside"><div class="header-date" data-today>JAPAN STANDARD TIME<small>INDEPENDENT BOAT RACE MEDIA</small></div><button class="share-button" type="button" data-share aria-label="このページを共有">{icon("share")}</button></div></div><nav class="main-nav" aria-label="メインメニュー">{nav}</nav></div></header>
<main id="main" class="wrap"><div class="utility-bar"><span><i class="status-dot" aria-hidden="true"></i>DATA DRIVEN. FAN FOCUSED.</span>{'<span class="preview-label">公開前プレビュー</span>' if preview else '<span>レースを、もっと面白く。</span>'}</div>{breadcrumb}{body}
<aside class="ad-slot" data-ad-placement="{current}-bottom" aria-label="広告"></aside>
<noscript><div class="notice">レース・検索データの表示にはJavaScriptが必要です。研究ノートと出典はそのまま閲覧できます。</div></noscript></main>
<footer class="site-footer"><div class="wrap footer-main"><div><a class="footer-brand" href="/">競艇AIナビ</a><p class="footer-copy">そのレースを、もっと深く。<br>データの取得日時・出典を明示する、独立したボートレース情報サイト。</p></div>
<nav class="footer-links" aria-label="フッターメニュー"><a href="/races/">レース一覧</a><a href="/predictions/">AI予想</a><a href="/motors/">モーター情報</a><a href="/racers/">選手データ</a><a href="/analysis/">結果・選手分析</a><a href="/lab/">AI成績・研究室</a><a href="/sources/">出典・表示ルール</a><a href="/privacy/">プライバシー</a><button class="text-link" type="button" data-consent-settings>解析設定</button></nav></div>
<div class="wrap footer-bottom"><span>© 2026 競艇AIナビ · BOAT AI NAVI</span><span>INDEPENDENT MEDIA · 公式サービスではありません</span></div></footer>
<div id="consent-panel" class="consent" role="region" aria-label="アクセス解析の選択" hidden><strong>より使いやすいサイトにするために</strong><p>閲覧やボタン操作の解析を許可しますか。許可するまでGoogleの計測タグを読み込みません。拒否してもすべての機能を使えます。</p><div class="consent-actions"><button class="button" type="button" id="consent-accept">解析を許可する</button><button class="button button-outline" type="button" id="consent-decline">許可しない</button><a href="/privacy/">取扱いを確認</a></div></div>
<div class="toast" id="toast" role="status" hidden></div></body></html>
'''


def build(output: Path, origin: str, preview: bool = False, verification: str = "", measurement_id: str = "", analytics: bool = False):
    if urlparse(origin).scheme != "https" or not urlparse(origin).netloc or urlparse(origin).path not in {"", "/"}:
        raise ValueError("origin must be an HTTPS origin without a path")
    if measurement_id and not re.fullmatch(r"G-[A-Z0-9]+", measurement_id):
        raise ValueError("GA4 ID must look like G-XXXXXXXXXX")
    if analytics and (not measurement_id or preview):
        raise ValueError("Analytics requires a real measurement ID and production mode")
    output.mkdir(parents=True, exist_ok=True)
    if output.resolve() != ROOT.resolve():
        for folder in ("assets", "data/public", "data/cards", "data/races"):
            src = ROOT / folder
            if src.exists():
                shutil.copytree(src, output / folder, dirs_exist_ok=True)
    (output / "assets").mkdir(exist_ok=True)
    config = {"preview": preview, "origin": origin, "analytics": {"enabled": analytics, "measurementId": measurement_id if analytics else ""}}
    (output / "assets/site-config.js").write_text("window.NAVI_CONFIG = " + json.dumps(config, ensure_ascii=False) + ";\n", encoding="utf-8")
    for path, page in PAGES.items():
        target = output / path.strip("/") / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(path, page, origin, preview, verification), encoding="utf-8")
    error_page = ("404", "ページが見つかりません｜競艇AIナビ", "指定されたページを確認できませんでした。", heading("", "PAGE NOT FOUND", "ページが見つかりません。", "URLを確認するか、ホームから見たい情報を探してください。") + '<a class="button" href="/">ホームに戻る →</a>')
    (output / "404.html").write_text(render("/404.html", error_page, origin, preview, verification), encoding="utf-8")
    allowed = [path for path, page in PAGES.items() if page[0] != "race"]
    sitemap = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>{origin}{path}</loc></url>' for path in allowed) + '</urlset>\n'
    (output / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    (output / "robots.txt").write_text("User-agent: *\nDisallow: /\n" if preview else f"User-agent: *\nAllow: /\nSitemap: {origin}/sitemap.xml\n", encoding="utf-8")
    print(json.dumps({"pages": len(PAGES) + 1, "output": str(output), "preview": preview, "analytics_enabled": analytics}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT)
    parser.add_argument("--origin", default=PRODUCTION)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--verification", default="")
    parser.add_argument("--measurement-id", default="")
    parser.add_argument("--analytics", action="store_true")
    args = parser.parse_args()
    build(args.output, args.origin.rstrip("/"), args.preview, args.verification, args.measurement_id, args.analytics)
