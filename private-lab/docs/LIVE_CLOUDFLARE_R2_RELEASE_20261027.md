# 航跡 BOAT LAB｜Cloudflare R2実データ接続 引継ぎ（2026-10-27）

## 実施済み（実リソース照合）

- 対象: GitHub `maedayuuki0706-creator/-AI` の研究ブランチ `research/private-cloudflare-20261027`、ドラフト PR #54。既存の本番システム、main、Secrets、Render、Discord、Xには変更なし。
- Cloudflare Worker: `boat-private-lab`。URL: `https://boat-private-lab.maedayuuki0706.workers.dev/`。
- Access: Worker単位の `航跡 BOAT LAB Owner Only` アプリが存在し、Allowメール1件のみ。外部ブラウザの未認証 `/api/status` が **Cloudflare Access ログイン画面** になることを再確認。プレビューURL無効。**許可外メールでの拒否試験・更新後iPhone Safari実機は未確認**。
- 非公開R2: `boat-private-lab-archive`。管理された `r2.dev` の公開は無効、カスタム公開ドメイン0。Workerの `ARCHIVE` Binding を確認。
- R2プライベートデータ: `releases/official-2022-2025-v1/query/packs/` に **393個の圧縮データパック**。欠けていた `races/2022-11.json`, `days/2023-11-4.json`, `days/2024-04-4.json` は補充済み。
- 追加インデックス: `packs/maps/days-2022.json`, `days-2023.json`, `days-2024.json`, `days-2025.json`, `players.json` の5個を **private R2** に作成済み。
- R2内圧縮パックの元ファイル照合:
  - `days/*.json` 1,461日（2022/365, 2023/365, 2024/366, 2025/365）
  - `races/*.json` 1,461日
  - `players/*.json` 1,794選手
  - `summaries/*.json` 51個
  - `motors/*.json` 25個、`previews/*.json` 25個、メタ索引2個
  - **元ファイル計4,819個**。元ファイルが入っていた公式2022〜2025年研究エクスポート（公式205,269 R / 1,231,614出走）をバケット内圧縮パックに保存。
  - モーター・プレビューのR2ファイルはプレースホルダーで2026年詳細実データはまだ入っていない。
- Live Worker: 既存ステージングブリッジにgzipパック読み取り・R2照会を追加してCloudflare API経由でデプロイ。環境変数は `DATA_READY=1`, `DATA_PREFIX=releases/official-2022-2025-v1/query`。Allow認証とJWT検証、未認証遮断を保持。
- GitHubへ将来デプロイ用の `src/packed-r2.mjs`、`r2-api.mjs` 内の `R2_PACKED=1` 分岐、`wrangler.json` 接続情報、およびダミーgzipテスト `tests/packed-r2.test.mjs` を保存。別のローカルNode22検証は11件成功。

## 重要な未検証と未取得

1. **更新後のオーナー本人ログインとiPhone Safari画面操作**。ホーム、レース、選手、万舟、水面、モーター表示と応答速度を確認する。実機で動いたと推測して「完成」とは呼ばない。
2. Access未認証はログイン誘導を確認済みだが、**許可外メールが確実に拒否されるかの実ブラウザ試験**は未実施。
3. `/api/status` の**認証済み実レスポンス**はこの環境から取得できないため、205,269件がブラウザ経由で表示できるか未確認。R2の静的保存・ファイル数確認と区別する。
4. 2026年10月の展示、直前オッズ、前検・モーター正式履歴は未接続。2022〜2025年の研究データのみ接続済み。AI予想LOGの回収率・潮位・最新の自動更新は未接続。
5. Worker free枠の本番CPUとR2 API読取コストは実測未確認。gzip復元による処理時間に注意。
6. Workerのライブスクリプトは `staging-bridge.mjs` を元に API パック処理をインライン追加した **運用版**。GitHubの `src/worker.mjs` は同等のgzip reader分岐を持つが、UI静的配信方式が異なる。安全に再デプロイする際はAccess/認証vars/ルーティングとR2バインディングを確認し、現在の本番を不用意に置き換えない。

## 設定と再試行

- メインURL（Accessで保護）: `https://boat-private-lab.maedayuuki0706.workers.dev/`
- GitHub `wrangler.json` には `R2_PACKED=1` と `DATA_PREFIX=releases/official-2022-2025-v1/query` を設定。個人の認証情報は空、非公開設定は Cloudflare 側の bindings に保持。
- 巻き戻し：Workers の旧バージョンへ戻すか、`DATA_READY=0` でステージ画面の未取得APIへ戻す。R2パックと元DBを消さずに調査する。
- R2原本は公開GitHub・公開Worker assetsには一切置かない。Libraryの `/競艇AI研究/航跡R2一時転送/` は非公開の転送素材が残るため、勝手に一般共有しない。
- PR #54の承認なしマージ禁止。本番Discord・X・公開Render・予想AIは無変更。

## 次の最優先

iPhone Safari の所有者セッションでホーム画面を開く → ホームに公式205,269Rが表示されるか → `#races` の結果検索、`#players` で「毒島」、`#water`、`#manshu`、`#data` の状態を確認 → Cloudflare Workers のエラー/CPUログ確認。もし読み込みエラーならWorkersのR2読み取りログを確認し、必要時に `DATA_READY=0` へロールバックする。