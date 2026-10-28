# 航跡 — BOAT LAB｜Cloudflare 実接続状況（2026-10-28）

> 本書は2026-10-27付の引継書より新しい、**実環境を読み出して確認した状態**を記録する。GitHub研究ブランチと非公開R2の状態を区別し、未検証を完了扱いしない。

## 確認した環境
- 研究用GitHubリポジトリ: `maedayuuki0706-creator/-AI`
- ブランチ: `research/private-cloudflare-20261027` / ドラフトPR #54（mainへ未マージ）
- Worker: `boat-private-lab`、URL: `https://boat-private-lab.maedayuuki0706.workers.dev/`
- 非公開R2バケット: `boat-private-lab-archive`（APAC / Standard）
- 研究データprefix: `releases/official-2022-2025-v1/query`
- Worker設定: `ARCHIVE` R2バインディング、`DATA_BACKEND=r2`、`R2_PACKED=1`、`DATA_READY=1` に設定。Access認証3バインディングは維持。

## R2保存・データ整合性
R2の実一覧で **398オブジェクト、63,690,946 bytes** を確認（公式2022〜2025年分の圧縮パック）。内訳:
- `packs/days/`: 237
- `packs/races/`: 48
- `packs/players/`: 104
- `packs/maps/`: 5
- `packs/meta.json`、`packs/summaries.json`、`packs/motors.json`、`packs/previews.json`: 各1

検索マップ5個の参照を検証し、**1,461日分 + 1,794選手分のマップエントリの参照先パック欠落は0件**。保存オブジェクトのサイズ0件は0。R2から圧縮データを展開し、日別データと選手別データ、レース一覧を実検証。

R2の公式レース日別パック48個（各月）を展開して全年のレース数を再集計:
- 2022: 51,264件 / 365日
- 2023: 51,246件 / 365日
- 2024: 51,392件 / 366日
- 2025: 51,367件 / 365日
- **合計205,269レース / 1,461日。R2要約manifestと一致、解凍エラー0件。**

manifest: 公式結果205,269レース / 6艇出走1,231,614件 / 選手1,794人 / 期間2022-01-01〜2025-12-31 / 採用除外16,245レース。2025-12-31の実レース詳細（175レース）を読み、各レース6艇分の記録を確認。ある選手の個別データ797レコードも読み出し確認済み。

**注意**: このバージョンは公式2022〜2025年の研究用抽出であり、2026年の直前展示・オッズ・モーター詳細やAI予想LOGを含まない。未取得は未取得と表示。実績数字を創作しない。

## アクセス保護
- Worker対象のCloudflare Accessアプリは本人メール1件だけのAllowポリシーであることをAPI確認。
- 未認証のブラウザでサイトルートがCloudflare Accessのログイン画面になることを確認。
- Worker自身がCloudflare Access JWTの署名・audience・issuer・期限・許可メールを検証する設計。
- R2の `r2.dev` 公開ドメインは無効、カスタム公開ドメイン0件、Workers preview URL無効。
- **残る確認**: 新バージョンで本人iPhone Safariからホーム・APIが正しく読み込めること、許可外アカウント拒否、Cloudflareリクエスト負荷・CPU・速度の実測。追加のブラウザ無認証試験はCloudflare Browser Renderingの429制限で途中まで。

## UIとWorker
現地Workerに `entry.mjs` と `embedded-assets.mjs`、`src/worker.mjs`、`src/auth.mjs`、`src/r2-api.mjs`、`src/packed-r2.mjs` の6モジュールが含まれることを確認。通常の静的アセットバインディングがなくても、entryが埋め込みUIアセットを供給する仕組み。画面8種のUIソースは既存の `private-lab/public/` から構成。

## 次の優先事項
1. 本人がiPhoneでログインし、ホーム、レース検索（例: 2025-12-31）、選手検索、万舟・水面研究の実表示を確認する。ネットワークや5xx/503を調査。
2. 別アカウント・未認証のAPI/JS/CSSなどを遮断することを確認。これは研究データがprivate R2にあり、WorkerでJWTを検証していることとは別の確認。
3. 追加の2026年研究データを安全な別リリースとして取り込み、表示段階で出所・時点・欠測を区別。
4. 速度・CPU・無料枠消費量を計測。制限に掛かったら安易に課金せず、読み込み最適化。
5. データ移行結果をバックアップし、`DATA_READY=0` で直ちにAPIをフェイルクローズできることを保持。

## 厳守事項
既存Discord/X、Render公開サイト、本番予想AI、他の研究ワーカー、GAS/Sheets、Secrets、mainは停止・変更しない。新たな公開R2 URLを有効化しない。許可メール・JWT AUD・秘密鍵・私有研究データ本文は公開GitHubへ載せない。研究専用PR #54は本人承認なしにマージしない。
