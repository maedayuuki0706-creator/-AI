# 4場専門AI Phase 2（独立研究）

対象は江戸川03・児島16・唐津23・浜名湖06、期間は2025-10-18〜2026-10-17。
PR36の江戸川監査済み全国K原本174日を再利用し、残り191日だけを取得する。
欠測値は推測補完しない。事後のST・決まり手・進入を事前入力に利用しない。

## 安全性の事前確認

- 基点: `982110bcdb4dd9c4262fde5a4bce51f887cd3e0b`（PR36研究ブランチ）。
- PR32/33/34/35を読取確認。稼働中PR34のコード・ワークフロー・保存先は変更しない。
- 新規コード `research/four_venue_phase2/`、歴史データ `data/research_four_venue_phase2/20251018_20261017/`。
- 新規LOGは `research-four-venue-phase2-state` の `data/four_venue_phase2_shadow/`。
- main、Discord、X、Secrets、既存環境変数、既存LOGへの書込みは禁止。
- 追加の定期Actionsは登録しない。収集・分析は外部の独立作業環境で最大2 GET並列。
- 自動前向き実行は未稼働。準備済みコード・事後再計算・実測を区別して報告する。
- Phase1の新ゆうき完全原本保存・浜名湖実測・7日95%以上は別管理し、未達を引き継ぐ。

## 収集

```bash
python3 -m research.four_venue_phase2.collect \
  --out data/research_four_venue_phase2/20251018_20261017 \
  --reuse /path/to/edogawa-PR36-cache
```

日別チェックポイント・SHA256付き原本を追記保存する。再開時は取得済み日を再取得しない。
公式アーカイブの取得失敗を「非開催」と判定しない。失敗日の再試行は別履歴を残す。
潮・潮流、前検資料・平均ST、映像上の攻め起点、モーター使用期間が未取得なら不明とする。

## 固定した品質監査

公式K/Bを各365日確認。予定9012Rは結果8876Rと公式中止136Rに対応し、未解明の予定Rは0。
結果は通常8192R、事故等682R、同着2R。6艇級別は全8876Rで同一選手IDを確認。
K/Bの751場日付ヘッダーも各々一致。平均STの歴史事前原本・潮・返還明細等は欠測として残す。
現行データ/研究IDは `data/research_four_venue_phase2/20251018_20261017/CURRENT.json` を参照。

## 分析・検証

`audit` → `validate`（公開コードSHAを必須指定）→ `package_report` → `archive` の順で実行。
`build_workbook.mjs` は Artifact Tool の実行環境で `workbook_data.json 出力ディレクトリ` を指定する。
研究モデルは `model_manifests/03.json`, `16.json`, `23.json`, `06.json`。
CLIは `python3 -m research.four_venue_phase2.shadow --mode preflight --model MODEL --state unused` から確認できる。

改良A/Bは研究用。Cは検証済み係数がないため停止。再計算には実際の生成時刻と元入力の時刻を別保存する。
前向き原本・GitHub受領は0Rで、自動稼働成功とは扱わない。

## 独立稼働の未解決点

新しい手動workflowは研究ブランチにのみ存在し、既定ブランチへの登録は行っていない。
GitHubのworkflow_dispatchは既定ブランチへの登録が必要なため、現状では未稼働。
https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow

代替は独立実行環境から既存入力を読み取る `shadow` CLI。恒久実行先/書込認証の確定は未完了。
既存workflowやmainの変更でこの制約を回避しない。研究workflowは他ジョブ実行/待機時に見送り、同時実行1に制限する。
