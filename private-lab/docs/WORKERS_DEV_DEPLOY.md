# 独自ドメイン不要で「航跡 — BOAT LAB」を非公開デプロイする手順（2026-10-27）

**現在の状態:** コード完成・GitHub研究専用PR #54に保存。Cloudflareアカウントにまだ接続していないため**本番URL、Accessアプリ、private R2は未作成**。以下はデプロイ用の完成手順。既存のRender/X/Discord/本番AIは変更禁止。

Cloudflareは2026年8月から**Worker単位でAccessを掛ける機能**を提供する。Workersの`workers.dev`サブドメインを自分だけに公開でき、**ドメイン購入は必須ではない**。
- https://developers.cloudflare.com/workers/configuration/cloudflare-access/
- https://developers.cloudflare.com/workers/configuration/routing/workers-dev/
- https://developers.cloudflare.com/changelog/post/2026-08-14-workers-access/

## 第1段階：研究データなし・フェイルクローズのWorkerを作成

1. CloudflareアカウントでWorkers FreeとZero Trust Freeを利用できる状態にする。既存のアカウントの請求画面・無料枠・R2利用条件を必ず確認。支払い登録/課金変更は本人の承認が必要。
2. 作業用PC/Workのクラウドターミナルで`private-lab/`から `npx wrangler@4.153.0 login` を実行し、ブラウザOAuthログインする。パスワード・キーはチャットに貼らない。
3. `npx wrangler@4.153.0 deploy --config wrangler.bootstrap.json` を実行。これは**サイトコードのみ**で、R2も研究データもつながない。実行時の`ACCESS_TEAM` / `ACCESS_AUD` / `ALLOWED_EMAILS` が空のため全リクエスト403。
4. 生成された `https://boat-private-lab.<自分のサブドメイン>.workers.dev` を未ログインで開き、403になるのを確認。この時点で**まだAccessを設定できていない**ので、ブラウザにサイトを表示しない。

## 第2段階：Worker全体にCloudflare Accessを付ける

1. Workers & Pages → Worker `boat-private-lab` → **Access** → **Protect this Worker behind Access**。Production + Previewsの**両方**に有効化（プレビューURL自体は無効化維持）。
2. Zero Trust > Access > Applications から、個人の許可メールアドレスだけのAllowポリシー。Everyone、メールドメイン全体、Bypass、Service Auth許可は禁止。メールOTPで可。
3. AccessのアプリAudience (AUD)、Accessチームのサブドメイン名をダッシュボードから確認する。本人のメールや秘密はGitに入れない。
4. 無認証ブラウザでWorkerのURLが**Cloudflare Accessのログイン画面へ遷移**することを確認する。許可外メールは拒否、許可メールはログイン可。別タブ/プライベートウィンドウで確認する。
5. 追加確認：`node scripts/verify_remote.mjs https://boat-private-lab.<自分のサブドメイン>.workers.dev --require-access-gateway`。**単なる403や404はCloudflare Access設定完了の証拠として認めず失敗**する。
6. Workers.dev、Worker versions、プレビュー経由の全入口で、Worker Accessが有効であることをダッシュボードで確認。R2の`r2.dev`公開URLを許可しない。

## 第3段階：非公開R2バケットを作成し、本番用設定を生成

1. **R2の無料枠/課金条件を確認**してからPrivateバケット`boat-private-lab-archive`を作成。Public Development URL と Custom Domains を無効のままにする。
2. Workのローカル環境に以下の環境変数をセットする。**実際のメールアドレスやAUDを会話/公開ログに掲載しないこと。**
   - `CF_ACCESS_TEAM`: 例 `my-team` （`.cloudflareaccess.com`より前の部分）
   - `CF_ACCESS_AUD`: Zero Trust Access Application Audience
   - `CF_ALLOWED_EMAILS`: オーナーの許可メール（複数ならカンマ区切り）
3. `node scripts/configure_workersdev.mjs` を実行すると、**Git管理外**の`wrangler.local.json`を作る。これは`workers.dev`を利用し、プレビュー無効を維持する。
4. `node scripts/preflight.mjs wrangler.local.json`の全PASSを確認。公開Gitに`wrangler.local.json`をコミットしない。
5. `npx wrangler@4.153.0 deploy --config wrangler.local.json` でAccess対応後の本番Workerを再デプロイ。Accessゲートを外さない。必要ならアクセス設定画面でAUD/JWT/ログイン検証。
6. **データをアップロードする前に**、`verify_remote.mjs`を再実行し、本人/別メールでログイン許可/拒否を実際に確かめる。

## 第4段階：私有研究データをR2へ投入する

1. Workが作成した検索用R2エクスポート（`query/`約378MB、`details/`約58MB）を元の所有者Libraryの非公開データから再生成/取得。**公開GitHubに入れない。**
2. `docs/DEPLOY.md`を読み、`scripts/upload_r2.py`で新規release prefixにアップロード。最終QA前に既存prefixを切り替えない。
3. 許可アカウントで`/api/status`、選手・レース・万舟・展示・モーターの読み取り結果と元DBを照合。
4. iPhone Safari（通常/プライベート/モバイル回線）でログイン、8画面、検索速度、欠測を確認。
5. 費用・使用量を確認して完了と判断する。**Cloudflareが未接続の現段階では本番公開済みと報告しない。**

## セキュリティ

- Bootstrapは403で全拒否。**この403だけではAccessの設置を証明しない**ので、Accessのログイン画面への遷移を別途必須にする。
- Workerコードが署名付きCloudflare Access JWTを検証する。許可メール、AUD、iss、期限、JWK署名を確認する。
- 研究データはR2 Binding経由のみ、公開URLは禁止。生SQLite、公式原本、個人メールはPublic/assets・公開リポジトリへ絶対に入れない。
- Cloudflare接続・課金・メールAllow・秘密の操作は**本人のログイン画面内**で実施する。既存事業用アカウントやSecretsを書き換えない。

## 公式ドキュメント
- https://developers.cloudflare.com/workers/configuration/cloudflare-access/
- https://developers.cloudflare.com/workers/configuration/routing/workers-dev/
