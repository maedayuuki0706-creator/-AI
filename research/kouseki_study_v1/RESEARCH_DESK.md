# 航跡 — BOAT LAB 専属アナリスト研究室

## 起動と入力

Python 3.10以上・openpyxlを使う。データはリポジトリ外の本人用フォルダに置く。サーバーは127.0.0.1のみで待ち受ける。分析画面単体はHTMLとして端末内に持ち出せる。共有された端末ではファイルへのアクセス権が必要。

```sh
python -m unittest discover -s research/kouseki_study_v1
python research/kouseki_study_v1/local_desk.py --data /private/snapshot/data --db /private/official_results_2022_2025.sqlite --g1 /private/tokoname.xlsx
```

ブラウザで http://127.0.0.1:8873/ を開き、保存番組表の日付・場・Rを選ぶ。日付不明・出走表欠落はエラーまたは未収録になる。既定の収録監査は選択日までの7日間。

```sh
python research/kouseki_study_v1/desk.py --data /private/snapshot/data --db /private/official_results_2022_2025.sqlite --g1 /private/tokoname.xlsx --day YYYYMMDD --venue 08 --race 12 --audit-start YYYYMMDD --audit-end YYYYMMDD --out /private/new-report.html
```

出力先は新しいファイル名を使う。完全番組表に対する24場別・レース別欠損は次でJSON化できる。検証日はJSTの終了済み開催日を指定する。

```sh
python research/kouseki_study_v1/coverage_audit.py --cards /private/snapshot/data/race_cards --archive /private/snapshot/data/exhibition_log --start YYYYMMDD --end YYYYMMDD
```

## 日次更新

1. main と研究用展示保存ブランチ research-venue24-state-20261101 のコミットを記録し、git archive で新しいローカルフォルダに展開する。前者から data/race_cards・exhibition_log・official_results・motor_cycles.json、後者から data/venue24_v2/daily_source を同じ構造で配置する。
2. 前日と未解決日を監査する。完全番組表なしは母数不明。開催中止と未保存を混同しない。差異は公式開催一覧、キャッシュ時刻、登録番号、艇番と実進入を確認する。
3. 分割展示は日別CSV・取得監査JSONを組にして保存する。江戸川は公式展示。再取得は提供元の公開条件を確認し、日別ファイル単位で実施。既存原本との差分は新しいスナップショットで管理する。
4. 私有資料の公式Kデータベースは読み取り専用。収録期間・除外条件は同梱audit.jsonで確認。常滑G1ワークブックは「全288R」シートを使う。出力・原本・認証情報をコミットしない。
5. テスト後に実データでHTMLを生成し、結果照合・類似例の件数・展示列・各部門の分母を確認する。Live予測用には時刻が固定された締切前原本が別途必要。

## 部門と分析ロジック

| 部門 | 現在の分析 | 判定限界 |
|---|---|---|
| 選手 | 登録番号と実進入で集計。全国の保存選手検索、全走・コース別直近10、30/90/180/365日の出走数と着率・ST | 保存された正常完走のみ。期間内の空白、級別・優出等の補正、公式勝率に注意 |
| 勝ち筋 | 同コースの既知決まり手完走に対する勝利と、既知勝利に占める決まり手構成を別集計 | 他艇勝利時の決まり手は直接の敗因を示さない |
| 相互関係 | 実コースと決まり手を条件に2・3着の実コースを比較。2コース出走時のイン逃げ、隣接ST差 | 進入変更やまくりの発生確率は未推定 |
| モーター | 場・確認済み周期・機番単位で連対率。同じ使用選手・コースの過去日の他機実績から2連対の平均との差を算出 | 比較可能走数を表示。事故・整備イベント、相手構成の調整は未検証 |
| 展示 | 公式展示と当該場の計測名を保持した分割展示。完備した列で競技順位方式。同着は同順位 | 二次資料は締切前原本として使えない |
| 水面 | 同場の風速別イン1着・万舟率、当該レースの風速・波高 | 潮向・変化量、風向の水面基準への変換は未検証 |
| スタート | 実コース別本番STの平均・標準偏差、全艇有効時のST順位、隣接内艇との差 | 展示STからの個人予測は未採用 |
| 類似レース | 同場、6枠の級別構成が完全一致、有効な展示6値が必要。距離は艇番別展示順位の絶対差の平均 | サンプル不足でも検索条件を自動緩和しない |
| 傾向発見 | 2022〜24年で風速閾値4m/sの逃げ率低下が最大の場を選択。各群100件以上。選んだ場だけ2025年で再検証 | 選手や開催日内の相関は未調整。場ごとに別の閾値を最適化しない |
| 総合 | 同一レースの6艇・機力・連動・類似例・保留条件を関連付ける | 低標本は分母・区間で表示。シナリオの確率と結果後の条件付き頻度は別扱い |

## 検証と変更履歴

この版では既存の analytics・analyst_context・coverage_audit を再利用し、公式K読込、条件付き連動、探索期間と翌年検証、機力の使用者補正、分割展示比較、単一HTML・ローカル閲覧を追加。公開研究CIの生成物アップロードを除いた。テストデータは計算の境界値確認専用で、実績には算入しない。

同場のイン逃げ基準値は2022〜24年に成功数+1、走数+2で推定。未使用2025年に実測との差・Brier・自然対数Log Lossを算出し、全国固定の基準と比較する。日別再学習・ライブ確率校正・信頼度に応じた判断の検証は別工程。公式成績の正常完走限定に伴う選択バイアスと、モーター・選手を繰り返し観測する依存性がある。Wilson区間はレースを独立とした目安。

実データでの照合件数・成績・不足と原本識別情報は本人用の実行出力に収める。全日全場収録・実機Safari・Discordの実送信は個別に確認する。

## 追加資料と再現

- 二次結果は BoatraceOpenAPI/results の gh-pages、docs/v2/YYYY/YYYYMMDD.json を使う。1日1ファイルの原本hashを索引に保存する。正常な6選手・6艇・実進入・着順が揃った結果だけを採用し、公式Kに存在するレースは3連単組番、金額、艇番に対応する登録・進入・着順を照合する。年別の除外件数と照合件数は画面に表示される。二次の正常完走数を開催予定件数には使用しない。
- 二次番組は BoatraceOpenAPI/programs の同じ形式で別索引にする。未知の開催中止・不成立・事故を一律欠損と認定しない。公式の代替照合に使った番組・結果ともに事後の保存である。
- データ拡張時は公式K（年次検証の固定基準）と二次索引を別々に保持する。元データに対する書込みは行わない。以下の出力は新規ファイル名に限定される。

```sh
python research/kouseki_study_v1/extended_history.py --files /private/results/docs/v2 --official /private/official_results_2022_2025.sqlite --out /private/snapshot/data/extended.sqlite --start 20210101 --end YYYYMMDD --revision RESULTS_COMMIT_SHA
python research/kouseki_study_v1/program_history.py --files /private/programs/docs/v2 --out /private/snapshot/data/programs.sqlite --start 20210101 --end YYYYMMDD --revision PROGRAMS_COMMIT_SHA
```

- BOAT RACE公式「ダウンロード・他」掲載の半期ファン手帳を展開し、data/racer_terms/YYYY-1.txt（前期）または YYYY-2.txt（後期）としてCP932固定長のまま保存。対になるJSONにurl、acquired_at、sha256、rowsを記録。公式レイアウトの登録番号、勝率、算出期間、コース別進入・着順・STとスタート順位を使用する。適用期と算出終了日を両方確認する。
- data/program_source/YYYYMMDD.json は BoatraceOpenAPI/api v1 の番組。対になる YYYYMMDD.meta.json に取得時刻・URL・SHA256を記録。6艇の登録番号一致を条件として、当該番組の全国・当地勝率、連対率、Fを表示する。事前に内容が不変だったことは保証できない。
- 気象庁「潮位表」のテキストデータ版を data/tide/YYYY-観測地点コード.txt に原形で保存。同名の .json にURL、取得日時、SHA256を記録する。data/venue_tide_profiles.json で場と地点・潮汐適用可否を確認。締切以前の直近正時と1時間前の掲載値の差をcmで出す。天文潮位と実測・流速・潮止まりを混同しない。
- 分割展示は同場・艇名照合・6値が有効な列だけで実コース別の展示上位と着順を比較。機番別の整備比較は同一周期の記録に限り、直前3走と当走を含む次の3走を上限とする。
- 類似レースは厳密条件の他に、利用者が明示的に開ける距離検索を提供する。級・展示順位・展示進入・チルト・風・波の6軸が揃った過去レースを等重みで比較する。距離式と件数・払戻分布は結果とともに表示する。

公式資料： https://www.boatrace.jp/owpc/pc/extra/data/download.html 、https://www.boatrace.jp/owpc/pc/extra/data/layout.html 。水面資料： https://www.data.jma.go.jp/kaiyou/db/tide/suisan/ 。二次資料： https://github.com/BoatraceOpenAPI/results 、https://github.com/BoatraceOpenAPI/programs 。

保存番組の全艇番号・登録番号を確認した索引を作ると、展示保存以前の日も番組と着順履歴を選択できる。展示欠損はそのまま表示される。

```sh
python research/kouseki_study_v1/lineup_store.py --folder /private/programs/docs/v2 --out /private/snapshot/data/lineups.sqlite --start 20210101 --end YYYYMMDD --revision PROGRAMS_COMMIT_SHA
```

「進入変更を試す」は内から6艇の順列を入力して、各選手がその実コースで走った365日内の成績・母数を再表示する。進入の深さは未観測。「番組表gradeコード」は1＝SG、2＝G1系、3＝G2、4＝G3、5＝一般で、併催等は開催レベルの記録である。
