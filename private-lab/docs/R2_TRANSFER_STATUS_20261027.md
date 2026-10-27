# 航跡 BOAT LAB｜Cloudflare R2 移行チェックポイント（2026-10-27）

## 実確認できた現在地
- 分離作業先: `research/private-cloudflare-20261027`、ドラフトPR #54。main/Render/Discord/X/本番AIは変更しない。
- Cloudflare R2バケット `boat-private-lab-archive` 作成済み。R2 managed public URL は無効、custom domain は0件。
- Worker `boat-private-lab` に `ARCHIVE` R2 binding 設定済み。既存Access認証用bindingを保持。
- Accessアプリ `航跡 BOAT LAB Owner Only` 設置。許可はオーナーの単一メールルール。Worker preview URL無効。
- 無認証のCloudflare Browser RenderingでWorker URLがAccessサインインへ遷移することを観測。許可外ログインのブラウザ実験、データ投入後の認証済みSafariテストはまだ行っていない。
- WorkerのR2対応処理はアップロード済みだが、データ有効化フラグ`DATA_READY`は未設定。したがって研究結果検索はまだ本稼働していない。

## R2へ投入した検索用分割データ（APIにより個数を実確認）
- リリースprefix: `releases/official-2022-2025-v1/query/packs/`
- 今回の転送用パック: 131バッチ×3データ = 393個。
- Cloudflare R2で確認できたパック: **390個 / 393個**、**63,342,175 bytes**。完了とは扱わない。
- 3個は転送ツールのチェックで処理がブロックされ、**R2にない**。欠けたキー:
  - `releases/official-2022-2025-v1/query/packs/races/2022-11.json`
  - `releases/official-2022-2025-v1/query/packs/days/2024-04-4.json`
  - `releases/official-2022-2025-v1/query/packs/days/2023-11-4.json`
- 非公開ChatGPT Libraryの `/競艇AI研究/航跡R2一時転送/` に `batch-0000.jsonl` ～ `batch-0130.jsonl` の一時転送元がある。公開GitHubには研究データを置いていない。
- 既存の公式2022-2025年研究DBに含まれる205,269R/1,231,614出走の全件クラウド照合は**未実施**。現在の数はパック数であってレース数ではない。
- 2026-10直前情報やモーター実履歴、AI予想LOGはこのリリースに完全接続できていない。

## 次の実装順序（安全優先）
1. 未投入3パックを、Cloudflare R2へ直接アップロードする正規の管理者経路（例：本人承認のWork環境内Wrangler CLI）で投入。公開URLや公開Gitにデータを流さない。
2. 393/393パックのR2件数・キー・サイズ・必要なハッシュを突合。
3. 現Worker側のR2検索APIは従来の `query/days/...json` 等の個別オブジェクトを想定しているため、**現在の `query/packs/days/...` / `query/packs/players/...` 形式を読むパック索引アダプタが必要**。この接続に対応する専用コードを研究ブランチでテストし、401/403等の認証保護は維持。
4. 全件検証後のみ`DATA_PREFIX`などの設定と読み取り有効化を実施。公開Gitにメール/AUD/Secretsを含めない。
5. 許可アカウント・不許可アカウント・未ログインで全画面/APIを検証し、Safariでホーム、検索、選手、万舟、風波、モーター、展示オッズを確認。欠測値は未取得のままにする。

## 重要
上記はCloudflare APIの実確認。現段階でサイトで205,269R検索が動作すると主張しない。R2に私有データを格納しても、WorkerのAccess/JWT認証・R2非公開設定を外してはならない。
