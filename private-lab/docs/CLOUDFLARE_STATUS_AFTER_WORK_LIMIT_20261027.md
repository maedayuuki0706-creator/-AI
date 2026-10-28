# 航跡 BOAT LAB｜Cloudflare接続・デプロイ引継ぎ（2026-10-27）

## 現在の稼働状況（実行結果と未検証を分ける）
- GitHub: `research/private-cloudflare-20261027` / draft PR #54。main等へマージなし。
- Cloudflare: 既存Worker `boat-private-lab` を再利用。Worker API PUTのHTTP 200と、2026-10-27T11:30:52Zの最新デプロイ記録を確認した。
- URL: `https://boat-private-lab.maedayuuki0706.workers.dev`
- Access: CloudflareのWorkerを宛先とするAccessアプリ `航跡 BOAT LAB Owner Only` が存在。Allowポリシーは本人の単独メールのみ。preview URLはオフ。所有者は今回以前にAccessログイン→Hello World到達を実際に報告済み。**新デプロイ後のiPhone表示、第三者のログイン拒否テストは未実施**。
- Cloudflareへ適用したコード: `src/staging-bridge.mjs` の内容（UI準備版）。研究R2はバインドせず、2026-10-27時点のコミット `94819d00d01dcb24ce30fec0776df353052ddfda` にある公開可能な `private-lab/public/` のHTML/JS/CSSだけをGitHub raw経由で取得する。
- 防御: Worker自身でもAccess JWTの署名・issuer・AUD・期限・許可メールの一致を検証。不一致は403。失敗時に私有データが出る経路なし。全画面/APIは取得した認証情報がないと応答しない想定。
- API: R2未接続のため検索画面では「未取得」と表示。公式レース件数・AI的中率や回収率を表示していない。**これは完成版ではない**。
- Cloudflare APIからWorker更新日時、最新デプロイ1件、Accessアプリ、Workerに設定された認証3変数（値は非記録）を再確認。
- GitHub Actionsの独立CIは、初回ステージ用コード保存後のジョブ `40496917889` がsuccess。続けてステージ用JSも構文検査対象へ追加。

## 未解決の実作業ブロッカー
1. R2 API `GET /accounts/.../r2/buckets` は2026-10-27時点でHTTP 403 / 10042 `Please enable R2 through the Cloudflare Dashboard`。プラグインにはR2のread/write権限があり、単純なコネクタ再接続では解決しない。**Cloudflareダッシュボードで所有者によるR2の有効化が必要**。支払い登録、課金変更は明示承認なしで進めない。
2. R2を有効化しても、即座に研究データをアップロードしない。まず未ログインの全ページ/APIがAccessログインへリダイレクトされるか、別アカウントが拒否されるか、オーナーが入れるか、プレビュー/r2.dev/カスタムドメインに別入口がないか検証する。
3. 既存の研究用非公開ZIP `航跡_BOAT_LAB_R2非公開データ投入用_20261027.zip` を安全なローカル環境で検証する。対象は `query/` 4,819オブジェクトと `details/` 3,876オブジェクト、合計8,695件/約436.7MB。研究データ/公開されない元DBは公開GitHubにコミットしない。
4. AccessとR2 privateを確認した後、研究用 `src/worker.mjs` と `wrangler.local.json` を使ってデータ接続Workerへ切替え、新しい非公開release prefixへアップロードしてAPIの実数を照合する。
5. iPhone Safariの実機表示、3連単結果、選手、万舟、水面、モーター、展示・オッズ、速度、コスト、未取得表示、未認証遮断を再確認する。

## 安全条件
- Discord、X、自動予想、本番研究ワーカー、Google Sheets/GAS、Render本番、main、既存Secretsは変更しない。
- 公開GitHubへ研究DB・個人メール・Access AUD・秘密鍵を置かない。R2の公開URLを有効化しない。
- PR #54は引き続きdraftのまま。承認なきマージなし。

## 注意
この文書はCloudflare API経由のデプロイ確認を記録したもの。新UIのSafari実表示、R2データ投入、ブラウザ経由の他ユーザー認証チェックが完了したという意味ではない。
