# 江戸川 Phase 2（独立研究・未採用）

対象は2025-10-18〜2026-10-17。元履歴ブランチをベースに追加のみ。
既存のDiscord/X、予想エンジン、データ取得、Secrets、既存環境変数、mainを変更しない。

## 現状

- Phase 2-A: 元2,041Rを公式174日で監査。追加28R、統合2,069R。
- 正常1,850R、異常を含む219R。元212Rの通常着順不足は公式の異常着順に対応。
- B: コース/決まり手/連動/風・波/選手を記述分析。潮流、全国比較、映像ラベル等は不足。
- C: A/Bは研究候補として実装。Cは検証済み係数がなく停止。
- D: 学習1,322R・検証429R・最終99R。既存締切前原本18Rと同入力の後付け比較。
- E/F: 独立原本・受領・結果・レビューの基盤と結合試験まで。前向き実測0R。
- Phase 1: 未完了。新ゆうき完全LOG・浜名湖・7日95%の追跡は別管理。

**新規workflowは研究ブランチだけに置き、未稼働。** GitHubのdefault branch登録が
必要なため、main無断変更禁止の条件下では自動起動したと報告しない。
既存登録済みworkflowは一切変更していない。独立実行環境で以下CLIを使える。

## 再現

Python 3.12、標準ライブラリとOSのlibarchive（LZH読取）が必要。

```bash
python -m unittest discover -s research/edogawa_phase2/tests -v
python -m research.edogawa_phase2.acquire --source data/research_edogawa_history/20251018_20261017/races.csv --out data/research_edogawa_phase2/20261018 --workers 2
python -m research.edogawa_phase2.study --source data/research_edogawa_history/20251018_20261017/races.csv --acquisition data/research_edogawa_phase2/20261018/acquisition/84b032ee2887a748e113354fc8f8b3611eb96ee38d68183cca98d4a9bbb8c0f8.json --out data/research_edogawa_phase2/20261018/studies
```

大きいJSON/CSVはGitにgzip版を保存する。必要時にgzip展開してから指定する。
公式LZH原本は official_raw_archives.zip 内のraw/にSHA256名で保持（展開して利用）。decoded/は原本から再生成できる作業用で
Git保存しない。公式Kにない返還の詳細や未取得の潮流を推測して埋めない。

`study.py`のrun_idは元CSV・公式取得manifest・監査コードから決定。
`validate.py`は既存のモデル/評価出力を上書きせず、不整合があれば拒否する。
最終評価を見た後のモデル規則変更には新しい未来評価が必要。

## 予想と照合

独立ブランチ `research-edogawa-phase2-state` の
`data/edogawa_phase2_shadow/` のみ書き込む。既存研究LOGは読み取り専用。

```bash
python -m research.edogawa_phase2.shadow --model research/edogawa_phase2/model_manifest.json --state STATE_CHECKOUT --mode preflight
python -m research.edogawa_phase2.feed --model research/edogawa_phase2/model_manifest.json --source-state READONLY_VENUE_CHECKOUT --state STATE_CHECKOUT --rno 1 --mode capture
```

captureは当日、展示6艇がそろった既存原本に限定。既存の入力digestと予想digest、
締切前受領を先に検証し、A/Bが同じ入力を使う。コードSHA・モデルdigest・採否理由・
6艇の勝ち筋/負け筋・他5艇の反応を原本に保存。3分前を切った新規生成は拒否する。
Git push後のリモート読戻しが締切後なら受領失敗扱い。結果と分析は別ファイル。

停止時は既存原本を `shadow --mode resume --forecast PATH --publish` で再送する。
再計算・原本差替えはしない。遅い受領を成功へ変換しない。
`shadow --mode review --forecast PATH --receipt PATH --result PATH` は結果とレビューを分離。
結果はrace_id・observed_at・trifecta・method・payout_per_100・normal_verified・refund_lanes等。
映像根拠のない攻め起点は判定不能。過去オッズ原本がないROI/トリガミ率は未算出。

## 安全・資源

- スケジュールなし、手動1R/回、独立concurrency、3分上限。
- 公式の追加取得なし。既存研究入力の読み取りのみ。
- 状態は新規ファイルのみ、固定ブランチ/固定prefix、forceなし、最大3回のpush再試行。
- 競合は原本を統合/上書きせず失敗として保持。GitHub標準の失敗表示と7日artifact。
- 稼働時はqueued/started/completed時刻・baselineの遅延を監視し、競合時は研究を増やさない。
- 現在は実稼働なし。100R初期診断/300R中間評価、7日保存率を未達として明示する。

`reused_sources.json` に既存の純粋研究エンジンのSHA256を固定し、無変更で再利用。
本研究に配信モジュール、外部送信、課金、APIキーの読み取り処理はない。
