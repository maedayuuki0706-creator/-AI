# 研究材料の追加収集・継続保存

PR #46 のデータ専用ZIP、PR #45 の出典・仮説、PR #47/#48 の公式原本アダプターと安全ゲートを再利用する研究専用追加処理。
既存配信、予想、研究worker、Sheets、Secrets、環境変数は変更しない。

## 保存先

- コード: `research/materials-continuous-20261020`。既存コードの変更なし、新規 `research/materials_v1/` と専用CIのみ。
- 継続データ: `research-materials-state-v1`。既存 `research-venue-specialists-state` は読み取り専用。
- 新規運用入口: `.github/workflows/research-materials-update.yml`（mainにこの新規ファイルのみ追加）。専用concurrency、1ジョブ、標準ライブラリのみ。既存ワークフローは編集・停止しない。
- 旧データ: `競艇AI_追加研究データ_20251018-20261019.zip` をそのまま再利用。9,084Rを新規実績として再加算しない。
- 選手・モーターの大量の派生履歴は今回の成果ZIPに保存。研究stateの種データへ同じ大量ファイルを二重投入しない。

## 時刻と漏洩防止

取得した原文はSHA256で固定し、取得時刻・公開時刻（不明ならnull）・出典URLを保存する。本文はgzip+base64の `.gz.b64`。`base64.b64decode` の後 `gzip.decompress` で元バイトへ復元し、SHA256を検証できる。
展示時気象と結果時気象は別ディレクトリ。結果は締切後だけ取得し、予想入力の許可リストへ加えない。
過去の原文を今回補完した場合、今回の取得時刻を記録し、当時の締切前受領証に置換しない。
予想はPR #48の `build_live` を呼び、全6艇の公式原本を照合、締切3分未満の新規生成を拒否、原本の上書きを拒否する。
旧原本の再解析から新しい前向き成績は作らない。締切前オッズは120通りすべてと実受領時刻を保存し、目標600/300/180秒の±45秒を外れた値は目標オッズとして数えない。起動前に過ぎた時刻は欠測のまま。

## 遠隔保存

`worker.publish` は専用stateブランチ以外へのpushを拒否する。入力と3方式各10点の予想をpush後、遠隔ref・commit内の入力/予想・Git blob・SHA256を照合し、GitHubのHTTP Dateと実際の確認時刻を別受領証に保存する。受領が締切後なら前向き採点から除外する。
ローカル予想原本の `local_frozen_unconfirmed` は上書きせず、遠隔受領の有無は別ファイルが管理する。
更新周期は稼働時間中20秒poll（取得元への間隔は最低1秒、展示の再取得は45秒、番組60〜300秒、前検30分）。Actionsの予約起動に遅延があり得るため、目標時刻取得の保証はせず、実取得・欠測を必ず記録する。
新しいジョブは最大10分の有限実行。稼働時間中のみ同じ専用処理へ継続要求を送り、予約起動もバックアップとする。

## 研究の境界

- 近隣検潮所の推算/実測は水面自体の潮位・流速ではない。唐津は潮汐対象外。
- モーターは場×周期×機番をキーにする。旧カタログの最終確認日を超える期間へ無条件で延長しない。周期未確認は欠測。
- 一周・まわり足・直線は公式の計測図・注記と一緒に保存し、場をまたぐ絶対値比較をしない。
- 記事の仮説や決まり手を実際の攻め起点とみなさない。全艇映像未確認のレースはラベルを埋めない。
- `derive` の得意不得意は4場の公式照合済み通常レースの記述集計。全国の通算値ではない。30走未満を標本不足とし、実コースが欠けるレースを展示進入で埋めない。
- 未検証の場別・潮位・風・足係数は採用しない。同じレース・同時点入力・各10点の前向き100R→300R、暦日分離による比較が必要。

## 実行

```sh
python -m unittest research.materials_v1.test_materials -v
python -m research.materials_v1.collector --state /separate/research-state --reuse /readonly/venue-state/data/venue_specialists_v1 --source-sha COMMIT --reuse-only
python -m research.materials_v1.worker --state /separate/research-state --reuse /readonly/venue-state/data/venue_specialists_v1 --source-sha COMMIT --seconds 480 --interval 20 --publish
```

実測件数、欠測と未実施は `RESULTS.md` および専用stateの `reports/` と `runs/` を参照。性能向上の保証・本番採用・通知先追加は行わない。
