# 新ゆうき EV研究｜独立ジョブ運用手順

## 現在の状態（2026-10-14）

- EV1.4以上の★、モデル別・締切前固定/過去再計算別の集計、初回1Rの結果照合は研究用Google Sheetへ反映。
- [研究用Sheet](https://docs.google.com/spreadsheets/d/1gXM8oPdzAOZkkNFly4B6jXwezV4eFSw7f7St6s49EdY/edit) は既存Google Sheetsサービスアカウントに編集権限を付与済み。
- 独立結果照合のソースは `research/yuuki_ev_sheet_sync.py`。**自動Cron未接続・CI実行未確認**。
- 研究A/Bの締切前1Rで、EV>=1.4は計38券（A19+B19）、全券外れ。ただしAの元の採用買い目は的中。標本1Rにつき優位性は判断しない。

## 独立ジョブの設定（Workで実施）

1. 既存予想・Discord/X配信・既存Actions・mainブランチの配信コードは変更しない。
2. 研究専用のRender Cron Jobなどを新規作成し、**この研究ブランチ**を参照。既存の本番Renderサービスとは独立させる。必要な料金・権限を確認してから作成する。
3. Build: `pip install "gspread>=6,<7" "google-auth>=2,<3"`。
4. Dry run: `python research/yuuki_ev_sheet_sync.py`。書込版: `python research/yuuki_ev_sheet_sync.py --write`。
5. 研究ジョブの環境に `GOOGLE_SERVICE_ACCOUNT_JSON` を**秘密変数として**設定する。非公開GitHubを参照する場合のみ読み取り用 `GITHUB_TOKEN` を設定。絶対にソース・ログへ値を出さない。
6. `python -m unittest research.test_ev_sheet_sync` を通し、Dry runで本番書込がないこと、`--write` で研究用Sheet以外が更新されないことを検証。
7. Cronはまず営業時間内30分間隔などの控えめな頻度で開始し、欠測とスプレッドシートAPIクォータを確認してから調整する。

## 制約

- このコードは研究Sheetに**既に存在する買い目**の公式結果照合と集計更新だけを扱う。
- 新規の予想原本A〜Fを追加する収集ジョブは、まだ別途必要。新規予想が何も増えない状態を「完全自動化済み」と言わない。
- 返還・同着・特殊払戻の正確な処理が未実装なので通常払戻のみ確定反映する。対象外は未確定のまま。
- 「全モデル」はA/B両モデルをそれぞれ別の仮想投資として合算した比較用集計。実際の1人の購入成績ではない。
- 確率の検証と1点100円の仮想投票は研究目的のみ。利益や実際の投票結果は保証しない。
