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
