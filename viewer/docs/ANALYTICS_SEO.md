# GA4・Search Console 導入準備

Googleアカウント・GA4プロパティ・Search Consoleの登録や変更は行っていない。
Secrets・Render環境変数も未変更。既定はGA4無効・測定ID空欄。
プレビューは常に計測無効、全ページnoindex/nofollow、robots.txtはDisallow /。

## 所有者側で必要な設定

1. 所有するGoogleアカウントでGA4プロパティとWebデータストリームを用意し、測定ID（G-...）を取得する。
2. 運営者の連絡先、プライバシー、同意方針を確認する。不要なGoogleシグナルや広告連携を有効にしない。
3. カスタムイベントで計測するため、GA4拡張計測のページビュー・サイト内検索・フォーム操作は無効にする。二重計測や検索語の自動収集を避ける。
4. 本番反映の承認後、測定IDを明示して静的ファイルを再生成する。

    python3 viewer/build_pages.py --measurement-id G-実際のID --analytics

有効なIDが必須で、previewとの同時指定はエラー。環境変数の追加は不要。
再生成時に引数を省略するとGA4は無効になる。測定IDは公開設定であり、秘密情報ではない。

5. 本番で許可・拒否・取り消しをTag AssistantとGA4 DebugViewで確認する。初期状態・拒否時はGoogleタグを読み込まず、許可前の操作も後送信しない。
6. 必要なカスタムディメンションをGA4へ登録する。
7. Search Consoleに本番URLの「URLプレフィックス」を登録する。Render共用サブドメイン全体のDNS所有権は不要。HTMLタグ方式の本人確認コードを受け取り、以下で生成して承認後の本番へ反映する。

    python3 viewer/build_pages.py --verification 実際の確認コード

GA4も利用中なら測定IDとanalytics指定も併用する。本人確認コード・測定IDは推測して入れない。

8. Search Consoleへ本番の /sitemap.xml を送信し、URL検査する。プレビューは送信しない。

## 計測イベント

| イベント | 発火する操作 | パラメータ |
|---|---|---|
| page_view | 許可後のページ表示、1ページ1回 | page_location、page_title、page_referrer |
| race_detail_view | 有効な出走表を表示できた時 | date、venue_code、race_number |
| prediction_open | 「予想を見る」を明示クリック。未公開でも関心として計測 | date、venue_code、race_number、entry_point |
| motor_search | 検索操作の完了 | venue_code、result_count |
| racer_search | 検索操作の完了 | query_length、result_count |
| x_referral | XのUTM、x.com/twitter.com/t.co参照元を確認 | source |

date・venue_code・race_number・entry_pointをイベントスコープのカスタムディメンションにするとレース別に分析しやすい。
検索語・氏名・任意クエリは送信しない。page_locationとpage_referrerもサニタイズする。
同意取り消し時は計測停止、同一ドメインで削除できるGA Cookieを削除、再読込する。
広告ストレージ・広告向けユーザーデータ・広告パーソナライズは常にdenied。
拒否した訪問者の閲覧数はGA4で把握できない。

## Xからの流入

プロフィールなどで使うURL例（既存のX自動投稿は変更していない）：

    https://boat-ai-readonly-view.onrender.com/?utm_source=x&utm_medium=social&utm_campaign=profile

許可するutm_campaignはprofile / free_prediction / race / motor / research。
参照元が欠けるアプリ内ブラウザでも、UTMが残ればX流入を識別できる。

## SEO・広告

- 6主ページ、出走表、出典、プライバシー、3研究ノートに独立した静的HTML。
- 固有title・description・canonical・OG/Twitter画像・JSON-LD・パンくず・共通リンク。
- レース詳細は動的選択のためnoindex/follow。個別レースを検索可能と偽らない。
- モーター/選手の検索クエリは基底ページをcanonicalにする。
- OGは本改修のオリジナル。公式ロゴ・写真は使用していない。
- 非表示の広告配置フックのみ用意。広告配信・課金・決済は未実装。
- 将来は公開可能な記事や個別選手ページの事前生成、専用ドメイン・恒久URLを検討。

## 公式資料

- [GA4設定](https://support.google.com/analytics/answer/14183469?hl=ja)
- [基本の同意モード](https://support.google.com/analytics/answer/14009635?hl=ja)
- [同意モード実装](https://developers.google.com/tag-platform/security/guides/consent?hl=ja)
- [Search Console所有権確認](https://support.google.com/webmasters/answer/9008080?hl=ja)

これは導入手順であり、Google側の設定・本番計測の完了を示すものではない。
