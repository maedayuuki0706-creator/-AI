# Work引継書｜航跡 BOAT LAB 非公開Cloudflareサイト｜2026-10-27

## 最終目標
既存の競艇AI本番システムに影響を与えず、所有者のみログインできるCloudflare研究サイト「航跡 — BOAT LAB」を **実際に使用できる状態まで** 完成させてください。計画書だけではなく、Cloudflareへの設置、非公開認証、研究データ投入、ブラウザ検証を優先します。ユーザーはiPhone中心で、英語Cloudflare管理画面の手動操作が負担なため、WorkのCloud Browserで可能な操作を肩代わりし、ユーザーへの操作依頼は本人のログイン/外部承認/決済承認に限定してください。

## 直近の事実
- GitHub repo: https://github.com/maedayuuki0706-creator/-AI （**公開リポジトリ**）
- 作業ブランチ: `research/private-cloudflare-20261027`
- 最新ドラフトPR #54: https://github.com/maedayuuki0706-creator/-AI/pull/54
- コード: `private-lab/` （全8画面、Workers + Access + private R2、JWT署名/AUD/iss/期限/メール検証、検索API、モバイルUI）
- 出発点の研究PR #52: https://github.com/maedayuuki0706-creator/-AI/pull/52
- Cloudflare上に**標準Hello World Workerのみ作成済み**。URL: https://boat-private-lab.maedayuuki0706.workers.dev 。**サイトの実コード未デプロイ、研究データ未アップロード**。
- ユーザーはCloudflare Zero Trust **Free ($0)** を選択済み。Worker Access画面で **All traffic** を選んだが、所有者限定Allow Policyを新規保存していない。**Apply Access完了は未確認**。現在サイトが非公開だと決めつけない。
- 独自ドメイン購入は不要。既存workers.devのWorker Accessで保護する案を優先。
- 既存公開Render https://boat-ai-readonly-view.onrender.com/ は一切変更しない。

## 読むべき資料（最初に読む）
1. `private-lab/docs/CONTINUATION_20261027.md`
2. `private-lab/docs/WORKERS_DEV_DEPLOY.md`
3. `private-lab/docs/DEPLOY.md`
4. `private-lab/docs/VALIDATION.md`
5. `private-lab/README.md`
6. `private-lab/wrangler.bootstrap.json`, `wrangler.json`, `src/auth.mjs`, `src/worker.mjs`, `src/r2-api.mjs`, `scripts/verify_remote.mjs`, `scripts/upload_r2.py`, `scripts/smoke_private_release.mjs`

## 実装と検証の到達点
- 2022-01-01〜2025-12-31の公式 **205,269レース、1,231,614選手出走、1,794登録番号、全国24場**を研究用DB化。除外16,245Rは理由つき記録。公式原本や私有DBは公開GitHubに含まない。
- 第三者由来の2026年10月の事前風波3,876R、モーター期別日次14,688行、展示・オッズ詳細3,876オブジェクト。公式照合済みと偽らない。
- 私有R2検索データ：`query/`4,819オブジェクト / 378,482,198バイト、`details/`3,876オブジェクト / 58,179,413バイト（合計8,695、約436.7MB）。会話添付 `航跡_BOAT_LAB_R2非公開データ投入用_20261027.zip` に再現物あり。ChatGPT Library `/競艇AI研究/` の元DB/原本も利用候補。公開GitHubにはアップロードしない。
- モバイル8画面の基本動作・横はみ出しゼロ、Chrome/Chromiumのスマホ表示は過去確認済み。**iPhone Safari実機・Cloudflare経由の速度は未確認**。
- 2026-10-27夕方に `src/r2-api.mjs` のAI未取得503、モーター番号の数値/文字列問題、検索継続カーソルによる重複R2読込を修正済み。
- 研究データを必要としない自動テスト19件中12成功・0失敗・データ依存7スキップ。最新GitHub Actions https://github.com/maedayuuki0706-creator/-AI/actions/runs/40478404906 は成功。
- 追加のローカル私有R2実データAPI検証11経路（ステータス、結果、選手、場別、万舟、モーター、風波、展示・オッズ、AI未取得）は成功。作成済み `scripts/smoke_private_release.mjs` で引継ぎ先でも再検証できる。

## 実施する順序：ここから再開
1. **GitHubからPR #54のHEADを読み込んで現状を再検証。** 自動テスト `npm test`、Wranglerの構文・dry-run、必要時に私有研究ファイルとの突合。過去のコードを再作成しない。
2. **CloudflareアカウントへWork Cloud Browserでユーザー本人の許可を得てログイン。** 既存Worker `boat-private-lab` を使用し、重複作成しない。Secrets・パスワード・APIキー・許可メールなどはチャット/公開GitHub/共有ログに貼らない。支払い登録や有料契約を勝手に進めない。
3. **非公開認証を先に完成。** Worker → Access → All traffic → 所有者メールアドレスのみをInclude EmailsでAllowするPolicy作成（Everyone/Bypass/全メールドメインは禁止）→ Apply Access。本人ログイン成功、未認証ブラウザ・不許可アカウント拒否を確認。workers.dev / preview / APIなど意図せぬ別URLの公開がないことも確認。
4. **データなしで安全なコードをデプロイ。** `wrangler.bootstrap.json` は認証変数空・R2なしで全403、既存標準Hello World Workerを置換できる。認証が実際に通る前は私有データのリモート投入禁止。Worker AccessアプリAUD/Teamをユーザーの非公開ローカル設定に入力し、`scripts/configure_workersdev.mjs` → `scripts/preflight.mjs wrangler.local.json` で全PASSを確認。Accessの認証を壊さず本番コードをデプロイ。
5. **Cloudflare R2をprivate設定で作成。** バケット名 `boat-private-lab-archive` を第一候補。r2.dev公開URL・custom domain公開URLを無効にし、Worker Bindingのみ許可。R2有効化に請求情報が必要なら必ず本人の承認を受ける。
6. **機密データのアップロード前に全入口の認証検証。** `node scripts/verify_remote.mjs https://boat-private-lab.maedayuuki0706.workers.dev --require-access-gateway` に合格し、所有者だけログイン成功、別メール不可、API/資産/生データURLの未認証閲覧不可を確認。404単独は保護成功扱いにしない。
7. **元研究DB・私有R2 ZIPを取得して手元で整合性検査。** `LAB_PRIVATE_R2=/absolute/private/release node scripts/smoke_private_release.mjs` を実行。エラーがあれば修正、別の非公開release prefixで `scripts/upload_r2.py` により投入。成功前に稼働中のprefixを切り替えない。公式原本を公開assetsに置かない。
8. **iPhone表示の最終確認。** 実ブラウザのモバイル幅390px、可能なら所有者自身のSafari/モバイル回線。8ページ、結果検索、選手全国/当地/枠/進入、万舟、風波、モーター、展示/オッズ、空欄、30件ページ分割、未認証遮断、Cloudflare使用量・無料枠・CPU実測。
9. ここまで完了したら **実際にログインできるURLと、検証済み/未完了を区別した報告**。デプロイ不可ならコード・CI・QAまで実行し、ブロッカーを一つずつ明示。

## 最重要禁止事項
- **絶対に停止・変更しない**：既存Discord配信、X自動投稿、既存AIの予想・配信処理、研究ワーカー、Google Sheets/GAS、Secrets、Render本番設定、main。
- 作業は研究専用PR #54の分離ブランチ。所有者の承認なしにPR #52/54をマージしない。
- 研究DB・公式原本・R2検索索引・メール・鍵などを公開GitHubや公開サイトに含めない。
- 未認証のAccessとR2公開設定が検証できる前に**私有データをアップロードしない**。
- データが存在しないAI的中率/回収率・潮位・歴史追加年分は「未取得」。事後情報を事前予想に混ぜない。見せかけの的中率や回収率を生成しない。

## 最終納品
非公開URL、Access本人許可と未認証遮断の証拠、R2投入オブジェクト数と容量、20.5万R実検索、画面8種とiPhoneの検証、料金/無料枠の実測、PR #54のリンク、未完了項目、ユーザーが操作する必要のある箇所。英語画面の手動案内をなるべく減らして、Workが実操作を行うこと。
