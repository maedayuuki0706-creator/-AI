# Cloudflareへの残作業（未実施）

ユーザーの指示により、外部ログイン・権限付与・支払い登録はその操作前に確認が必要。この作業ではログインしていない。パスワード/APIキーをチャットへ貼らない。

## 1. 所有者が接続する

- Cloudflareアカウントへブラウザでログイン。Workers FreeとZero Trust Freeを選択。
- 利用するCloudflare管理ドメインと許可するメールアドレスを所有者が指定する。ドメインを持っていない場合は別途選択が必要（購入は勝手に実行しない）。この実装はworkers.devを無効化しcustom domainを利用。
- R2有効化時に支払い情報登録などを要求されたら、所有者に確認。無料枠超過が自動的に課金され得るため、R2利用量通知を設定し、Paid Workersへ自動で切り替えない。
- ローカルCLIは `npx wrangler@4.153.0 login` のOAuthを利用。既存リポジトリのSecretsは使わない・変更しない。

## 2. 空の保護環境を作る（研究データはまだアップロードしない）

1. 新規R2バケット `boat-private-lab-archive` を作成。Public Development URL (r2.dev)とCustom Domainsは無効。公開リンク・公開CORSを設定しない。
2. Zero Trust > Access > ApplicationsでSelf-hostedアプリを作成。対象を新しいホスト全体（例として `lab.<所有ドメイン>`、パス制限なし）にする。
3. PolicyのAllowは**所有者が指定したメールアドレスだけ**。Everyone/Bypass/全メールドメイン/Service Authは設定しない。メールOTPまたは既存IdPを使い、セッション期間は短くする。
4. アプリAudience (AUD)、チーム名、許可メールアドレスを、Git管理外の `wrangler.local.json` のvarsに設定。`wrangler.json`をコピーし、account_id、routesのcustom_domainとバケット名を設定する。デフォルトURL・プレビューURLはfalseのまま。
5. `DATA_PREFIX=releases/<新しいrelease名>/query`, `DETAIL_PREFIX=releases/<同release名>/details` を設定。これは機密値ではないが接続設定はコミットしない。
6. `node scripts/preflight.mjs wrangler.local.json` が全PASSであることを確認。
7. `npx wrangler@4.153.0 deploy --config wrangler.local.json` で**コードと静的画面のみ**デプロイ。assetsはpublic/の3ファイルだけ。データ不在時のAPIは未取得/503でよい。

構成例（ローカル設定だけに追加）：

```json
{"routes":[{"pattern":"lab.YOUR_DOMAIN","custom_domain":true}]}
```

## 3. データ投入前の必須確認

- `node scripts/verify_remote.mjs https://<新ホスト>` を実行。HTML・JS・CSS・API・想定データファイルが未認証で拒否、またはAccessログインへリダイレクトされること。
- 許可アカウントでログインすると画面に入れること。別アカウントは拒否されること。
- `workers.dev` URL、バージョンプレビューURLが無効であること。R2のr2.devとバケットcustom domainも無効であることをダッシュボードで確認。
- Accessの除外パスがないこと、Workerのrun_worker_first=true、Worker自身のJWT署名・iss・aud・exp・メールallowlist検証が有効なことを確認。
- これらを確認できなければ**研究データをアップロードしない**。

## 4. 認証確認後に非公開データ投入

ローカル検証済みの `query/` と `details/` だけを、新しいrelease prefixへアップロードする。公式原本は別保管のまま。UploaderはWrangler OAuthを使用し、4並列、失敗を記録、同release内の再開が可能。

```bash
python3 scripts/upload_r2.py --bucket boat-private-lab-archive --release initial-20261027 --query /private/release/query --details /private/release/details --wrangler /absolute/path/to/wrangler --verified-access-and-private-bucket
```

上の確認フラグは確認を代行するものではない。人が手順3を完了してから使う。

Uploadが全件成功する前にprefixを利用中の版へ切り替えない。初回はログイン画面で未取得になるが機密漏洩はない。成功後に認証済みで `/api/status` の実件数、任意結果・選手・展示・モーターを照合。
その後、未認証遮断テストを再実行し、iPhone Safari実機とモバイル回線で確認。

## 5. 更新・巻き戻し

現時点は手動更新。元データは読み取り専用で取り込み、原子置換でローカルDBを完成させる。新規日別データの公式検証→重複除外→R2索引生成→別releaseへアップロード→認証済みQA→prefix切替の順。
旧releaseは保持し、問題があれば旧prefixへ戻す。不要なreleaseを削除する前に所有者と保持期間を決める。既存ワーカー・本番GitHub Actionsへの追加負荷やスケジュール変更はしない。

## 無料枠と費用（2026-10-27公式資料確認）

| 項目 | 無料枠 | 今回の想定 |
|---|---|---|
| Workers | 100,000リクエスト/日、Free CPU 10ms/呼出 | 認証のため静的ファイルもWorkerを実行。実測は未デプロイのため未取得 |
| R2 Standard | 10GB-month、Class A 100万/月、Class B 1000万/月 | 初回約0.437GB・8,695オブジェクト。1日1,000 API・平均10 GETでも月30万 GET程度。再試行・QAは別 |
| D1（任意、初期構成では未使用） | 500MB/DB、合計5GB、読込500万行/日、書込10万行/日 | ローカルDB 189,722,624 bytes。初回全件投入は日次制限のため不採用 |
| Access | Zero Trust Freeのユーザー上限内で利用 | 個人1アカウント。契約画面の現在の条件を確認 |

この作業でCloudflareへのデプロイ・ストレージ投入は0件。既存アカウント全体の消費量は未確認。上記範囲に収まるなら新規利用料は$0想定だが、ドメイン代、R2有効化条件、超過課金、その他既存利用は含まない。Free WorkerのCPUが10msを超える場合は、まずオブジェクト分割・集計を改善し、有料化は承認後のみ。

一次資料：
- https://developers.cloudflare.com/workers/platform/pricing/
- https://developers.cloudflare.com/workers/platform/limits/
- https://developers.cloudflare.com/workers/static-assets/routing/worker-script/
- https://developers.cloudflare.com/r2/pricing/
- https://developers.cloudflare.com/d1/platform/pricing/
- https://developers.cloudflare.com/d1/platform/limits/
- https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/
