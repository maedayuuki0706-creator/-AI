# 航跡 BOAT LAB：Work上限停止後の引継ぎ・2026-10-27

## 何が実装済みか
- リポジトリ `maedayuuki0706-creator/-AI`、独立ブランチ `research/private-cloudflare-20261027` の `private-lab/`。
- 研究用ドラフトPR **#54**：https://github.com/maedayuuki0706-creator/-AI/pull/54 （基点：`feature/boaters-data-research-20261025`）。
- Cloudflare Workers + Zero Trust Access + private R2 を想定したWebアプリ・8画面・R2索引API・JWT署名/発行者/AUD/許可メールの検証を実装済み。
- Work引継ぎ時のローカルデータ実績：公式Kの2022〜2025年 **205,269R / 1,231,614出走 / 1,794登録番号**、2026-10直前データ等。ソース研究DB・原本はリポジトリにコミットしていない。
- Workのレポート：`docs/VALIDATION.md`、詳細運用手順：`docs/DEPLOY.md`。

## この引継ぎで実施した内容
1. `scripts/verify_remote.mjs` を修正。未認証アクセスで**404を保護の証拠として受け入れない**。403/401または正しいcloudflareaccess.comへのログインリダイレクトだけを認証ゲートの候補とする。URL形式・TLSエラーも失敗扱い。データ投入後の確認にも利用。
2. 他の業務・本番系とは独立した `.github/workflows/private-cloudflare-lab-isolated-checks.yml` を追加。Node 22 JS構文、認証テスト、未設定時preflightがデプロイを拒否すること、公開GitにDB/鍵が含まれないことをチェックする。
3. CI https://github.com/maedayuuki0706-creator/-AI/actions/runs/40458297496 が**success**。全13項目中 **6件実行成功 / 0件失敗 / 7件スキップ**。スキップは実データSQLite/R2オフライン索引がGitに存在しないため。Work側のローカル本番相当データ検証と、GitHub上CIの範囲を混同しない。
4. GitHub **ドラフトPR #54を作成、未マージ**。既存main、Render、Discord、X、予想エンジン、Google Sheets、Secretsを変更していない。

## 未完了・ブロッカー（現時点ではデプロイ済みと報告しない）
- 現在のチャットにはCloudflareダッシュボード操作用の直接接続がない。Cloudflare上にURL・Accessアプリ・R2バケットを作成したとは主張しない。
- 所有者のCloudflareログイン（OAuth等、秘密をチャットで共有しないこと）、Zero Trust Access、利用するcustom domain、許可するメール、private R2確認が必要。
- **機密研究データのR2アップロードは禁止**：未認証・許可外ユーザー拒否およびworkers.dev/preview/r2.dev無効化が実サイト上で検証されるまで保留。
- iPhone実機のSafari/通信回線、Cloudflare上のCPU/Requests/R2使用量は未検証。
- AI予想LOGの回収率と事前EV、潮位/モーター正式履歴、日次自動更新、2022〜2025データ以外の歴史DB統合は別タスク。

## 安全な再開順序
1. 所有者がWorkのCloud Browser等を使いCloudflareアカウントにログイン・接続する。パスワード/鍵を会話に貼らない。
2. `docs/DEPLOY.md` の順でCloudflare Zero Trust Accessの自己メール単独許可、private R2設定、非公開カスタムドメインを作る。無料枠と利用料を確認。
3. **データなし**のWorkerだけをデプロイ。デフォルト `wrangler.json` は認証vars未設定のためデプロイ不許可。`wrangler.local.json` はGitにコミットしない。
4. 未ログイン/別アカウントでHTML・API・静的資産がすべて拒否されることを確認。`node scripts/verify_remote.mjs https://<new-host>` は404もFAIL。許可アカウントログインも別途チェック。
5. ここまで合格してから、既存所有者のライブラリで保存された非公開検索用R2ファイルを `scripts/upload_r2.py` で安全にアップロード。公開Git/公開URLに研究原本を出さない。
6. ログイン済みiPhone Safariで8画面と205,269R検索・更新状態・欠測・応答速度を検証。コスト警告とパフォーマンスを見て公開前承認。

## 警告
- GitHubの `-AI` リポジトリは公開されている。**コード用のPRは公開されるが、公式原本・検索用私有DB・許可アカウント・APIキーは公開しない。**
- PR #54のマージ、既存RenderやDiscord/X本番環境の変更は所有者による別途承認が必要。


## 2026-10-27 午後 — サイト配備セット完成（Cloudflareアカウント接続は残り）

- 公式ドキュメントにより、独自ドメインを買わなくても `workers.dev` に **Worker単位のAccess（Production+Preview）** を掛けられることを再確認。新しい `docs/WORKERS_DEV_DEPLOY.md` が簡易ルートの優先引継ぎ。別途ドメイン購入は必要ない。
- `wrangler.bootstrap.json` を新設（`workers_dev:true`、`preview_urls:false`、Access vars空、R2バインディングなし）。まだ設定していないサイトのHTML/API/静的資産を**すべて403で拒否**。データを置かずに空のWorkerだけ安全に初回デプロイできる。
- `scripts/configure_workersdev.mjs` によりCloudflareアカウントから取得したチーム名/AUDとオーナーメールを、Git管理対象外 `wrangler.local.json` にだけ保存。 `scripts/preflight.mjs` を強化し、署名検証vars・private R2 binding・Workers.devかcustom domainのいずれかが有効かなどを検証する。
- `scripts/verify_remote.mjs --require-access-gateway` で、ただの403や404ではなく、**Cloudflare Accessログインへのリダイレクト**が全入口であることをチェックする。さらに別アカウント拒否と本人通過をブラウザ実機で確認してからprivate R2をアップロード。
- Workの水面研究UIでローカル変数 `detail` がダイアログ関数 `detail()` と衝突していた不具合を修正（`breakdown`に改名）。
- GitHub Actions `private-cloudflare-lab-isolated-checks.yml` が **Nodeテスト7件実行成功/0失敗/7件実データ不足でスキップ**。ユーザー会話内のローカル実データ確認では **公式205,269レース＋直前3,876レースをSQLiteへ実インポートし、14/14テスト合格・スキップ0・PRAGMA integrity_check=ok**。
- ローカル実データからR2用の **4,819個の検索索引（378,482,198 bytes）＋3,876個の直前詳細（58,179,413 bytes）** を作成し、監査・CRC正常。会話内非公開ZIP `航跡_BOAT_LAB_R2非公開データ投入用_20261027.zip`（約55MB）に保持。**GitHub/公開Cloudflareには投入していない。**
- 公式全4年の出目・払戻205,269Rを内蔵した、iPhoneで操作できる**通信不要の単一HTMLオフライン確認版** `航跡_BOAT_LAB_研究サイト_オフライン確認版.html`（約8MB）も作成。5,000Rの最新明細のみ内蔵、それ以前の明細は未収録。Cloudflareの認証サイトではない点を明示。
- Playwright Chromium 390x844でオフライン版のホーム、結果一覧30件、レース明細、選手「毒島」検索、水面検索を実際に操作して**JSエラー0・横スクロール0**。iPhone Safari実機では未検証。
- Cloudflareへは**アカウント接続未実施・URL未発行・Accessアプリ/R2作成未実施**。Cloudflareログイン/権限付与のないチャットからデプロイ成功を主張しない。本番Renderや既存予想配信には影響ゼロ。
