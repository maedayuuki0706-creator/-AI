# 航跡 BOAT LAB 再検証・引継ぎ（2026-10-28 JST）

## 最優先の現在状態

- 既存 `boat-private-lab` Workerへ正規ソースを再デプロイ済み。新規Workerは作成していない。
- **DATA_READY=0**。現在、認証済みでも研究APIは503「研究データは検証中」を返す。
- 前回の実環境は、引継書と違ってDATA_READY=1だった。利用者指定の有効化前検証が未完了だったため0に戻した。
- 別アカウントの拒否、今回の正規JWT実装での本人ログイン、実環境の検索/CPU時間を完了扱いにしてはいけない。
- `main`、PR #52、既存配信・AI・研究ワーカー・Sheets/GAS・Render・既存Secrets・料金プランは変更していない。PR #54はマージしない。

## R2：転送は既に完了していた

`releases/official-2022-2025-v1/query/packs/` の最新一覧を全件取得。

|項目|検証値|
|---|---:|
|研究パック|393個 / 63,535,700 bytes|
|日付・選手マップ|5個 / 155,246 bytes|
|合計|398個 / 63,690,946 bytes|
|Library全131バッチとの不足・サイズ/MD5不一致|0 / 0|
|今回の追加データアップロード|0個|
|展開可能な論理JSON|4,819個|
|公式レース（重複なし）|205,269|
|出走記録|1,231,614|
|選手|1,794|
|日付|1,461日（2022-01-01〜2025-12-31）|

全レース詳細と全出走記録を既存研究SQLiteへ照合して一致。レース検索索引・水面/万舟集計も既存DB出力と一致。5個のリモートlookupマップは全キー・参照先が復元したマップと一致。

選手パックは既存エクスポートと出走配列の順番が逆で、player.avg_stがnull。出走の値・件数は同一。表示する枠別/進入別平均STは出走から再集計し、SQLite結果と小数9桁で一致。未取得の平均値を推測で埋めていない。

現在のパックの2026年展示・オッズ・モーター統計は空。AI予想LOGも未接続。モーターとAI画面が表示できることを、研究データ接続済みと取り違えない。

## コード変更

- 稼働環境だけのインライン実装を廃止し、`worker.mjs` / `auth.mjs` / `r2-api.mjs` / `packed-r2.mjs`をそのまま使用。
- `node scripts/package_worker.mjs` が `.deploy/modules.json` を生成。UIの3ファイルも同梱し、画面表示時の公開GitHub依存を除去。DB・認証情報はパッケージに含まれない。
- WorkerはJWT検証後にDATA_READYを検査。未設定/0ではR2を読まない。
- 同一API要求中の同じパックの重複取得を抑制。要求をまたぐデータキャッシュなし。
- 未収録の日付詳細は「未取得」。実在する索引の破損はエラーとして区別。
- 欠落している展示/モーターの収録値をUIで「未取得」と表示。
- 署名改ざんテストが偶然同じ文字を置換してしまう不安定性を修正。

コネクタのmultipart uploadでは、6つのモジュールに加えて既存のAccess/R2バインディングを保持する。DATA_BACKEND=r2、R2_PACKED=1、DATA_READY=0。認証値を公開設定ファイルへ書かない。デプロイ後にGETした6モジュール全文とローカル出力の一致を確認。

## 検証済み

- 自動テスト35件成功、スキップ0（元DB・個別R2・今回のパックを使用）。
- レースページ切替の60件重複なし、万舟条件、場/期間検索、毒島選手検索、全国/当地・枠別/進入別、風速2m/s、万舟集計をSQLiteと照合。
- ローカルChromiumで全8画面を操作。390×844で各画面の文書幅390、375幅ホームの文書幅375、JSエラー0。レース詳細6艇・2ページ目、選手検索・成績モーダルを操作。
- 実環境の未認証10経路（HTML/JS/CSS/API/想定データURL/不存在URL）は全て302 Accessログインへ。研究内容は返らない。
- Accessは既存Workerタグ全体に適用され、本人メール完全一致のAllowポリシー1つ。Everyone/Bypass/ドメイン包括許可なし。
- R2の公開URL disabled、カスタムドメイン0。WorkerのPreview URLs disabled。既存の本人Allowログも取得できた。
- JWT単体テスト：正規所有者のみ許可、別メール・期限切れ・改ざん・誤aud/issuer・未来nbf/iat・欠落設定を拒否。

ローカル20回測定（ディスクR2、HTTP/Cloudflare待ち時間を含まない。無料枠CPU時間の証明ではない）：

|検索|p50 / p95 ms|R2オブジェクト最大取得数|
|---|---:|---:|
|万舟レース一覧|10.9 / 29.3|2|
|選手名|15.2 / 26.2|1|
|選手当地成績|6.8 / 11.4|2|
|風速別|1.9 / 4.2|1|
|万舟集計|1.7 / 3.3|1|

## 未検証・次の本人操作

Cloud Browserの本人ログインはCloudflareのログインAPIが403を返して停止。原因は断定不可。プラグイン接続は正常なので設定とデプロイは実行できた。

1. iPhone Safariで `https://boat-private-lab.maedayuuki0706.workers.dev/` を開く。本人で画面が開き「研究データは検証中」と出るか確認する。これはDATA_READY=0の正常動作。
2. 別の本人管理メールでプライベートブラウズから試し、許可されないことを確認する。本人所有ではない他者アカウントを使わない。パスワード・OTP・Cookieをチャットへ送らない。
3. 上記実結果を受けてからDATA_READYを1へ変更。本人セッションで20万レース検索・各画面とWorker CPU/エラー率を確認。問題時は直ちに0へ戻す。
4. iPhone Safariの実際の操作、長時間の認証保持、期限切れ時の再認証は別途確認。

## 費用

データ量は約0.064GB（Standard R2無料10GB-monthの約0.64%相当、当該バケットの容量比較）。アカウント全体の月間請求額・他リソース消費は未確認。billing APIは権限不足403で取得できず、追加課金ゼロと断定していない。有料化・支払情報変更なし。

- R2 Standard無料：10GB-month、Class A 100万/月、Class B 1,000万/月。https://developers.cloudflare.com/r2/pricing/
- Workers Free：10万要求/日、CPU 10ms/要求。https://developers.cloudflare.com/workers/platform/limits/
- 本方式では画面資産も認証Workerを通るため、Worker要求数に含めて見積もる。

## ローカル再検証

```sh
LAB_DB=/private/search.sqlite LAB_R2=/private/individual-release LAB_PACKED=/private/packed-release npm test
node scripts/package_worker.mjs
node scripts/verify_remote.mjs https://boat-private-lab.maedayuuki0706.workers.dev --require-access-gateway
```

packed-releaseは `query/packs/` と5つの `query/packs/maps/*.json` を持つ。JSONLのbodyはそのままR2 object内容であり、個別JSONファイル形式としてアップロードしない。研究内容、認証情報、スクリーンショットは公開GitHubへ追加しない。
