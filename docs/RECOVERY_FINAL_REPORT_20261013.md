# 競艇AIシステム 作業結果

確認時点: 2026年10月13日13:40 JST。研究データは13:37完了分、シートは最終確認時の29レースを集計。定期処理が続くため件数は以後増える。

結論: Xの連続失敗を解消し、不明投稿は再送禁止のまま隔離した。新ゆうき研究の事前保存・公式結果照合・シート連携は復旧した。Discord配信は継続し、保護対象を変更していない。ただし鳴門8Rの未送信1件と、それに伴うV2のdegradedは未解消。全完了とはしない。

## 1. 不具合と原因

- X: `result:20261012:23:9` はMissingAcknowledgement、結果投稿IDなし。12日12:45:22–25 JSTの送信と、RenderのX HTTP503 / `/api/x-result` HTTP502が一致する。投稿済みかは確定できない。この古いuncertainが全後続実行をdegradedにしていた。
- Discord: `yuuki:20261013:14:8:final`、鳴門8R・締切11:49。公式結果は3号艇欠場、保存した展示情報は5艇。既存build_recordは展示6艇を必須とするため予想ができず、締切後にmissedとなる。同じ未送信記録が後続実行をdegradedにする。締切前に欠場を認識していたことは証明できない。
- 研究: 元の定期起動には大きな空白があり、過去の取得は55秒予算の超過で保存できていなかった。6艇の個別展開、根拠・欠損、研究専用シート書き込みも不足していた。

## 2. ファイル・コミット・反映範囲

本番反映はXのみ。PR #28、squash commit `c53f622092cc372c255ee1d625ec93b6c6f1e32e`。最終mainコミットに `[skip render]` を保持した。

Xの変更5ファイル:

- `x_delivery_v2/dispatcher.py`
- `x_delivery_v2/quarantine.py`
- `tests/test_x_delivery_v2_quarantine.py`
- `docs/X_UNCERTAIN_20261013.json`
- `.github/workflows/x-uncertain-no-send.yml`（投稿しないテスト専用）

研究コードは `work/x-fusion-recovery-20261013` / PR #27で独立稼働。コードの確認済み先頭コミットは `4aa5cce436fdde5f273e3cea82f6f0d4c0809db6`。mainへ研究機能をマージしていない。

- `fusion_shadow.py`, `fusion_shadow_runner.py`, `fusion_shadow_scenarios.py`, `fusion_shadow_wakeup.py`
- `sync_fusion_shadow_sheet.py`, `audit_fusion_recovery.py`
- `tests/test_fusion_shadow.py`, `tests/test_fusion_shadow_scenarios.py`, `tests/test_fusion_shadow_sheet.py`, `tests/test_fusion_shadow_wakeup.py`
- `.github/workflows/all-ai-fusion-shadow.yml`（研究ブランチの版のみ）
- `.github/workflows/x-fusion-recovery-validation.yml`, `docs/NEW_YUUKI_RECOVERY_20261013.md`

Discord欠場レビューはPR #29、commit `7eede5333e7fbe51edd8f35b7af9383b984696ab`。ドラフトのまま、本番未反映。既存コードは変更せず、独立関数・テスト・証拠・説明・投稿しない検証workflowだけを追加した。

- `delivery_v2/withdrawal_review.py`
- `tests/test_delivery_v2_withdrawal_review.py`
- `docs/DISCORD_WITHDRAWAL_REVIEW_20261013.json`, `.md`
- `.github/workflows/discord-withdrawal-no-send.yml`

## 3. GitHub Actions・テスト

| 対象 | 作業前 | 作業後の確認 |
|---|---|---|
| X V2 | 38334745961等でdegraded/exit1 | 38346488959は反映後success。直近38346928040・38347262521・38347579097もsuccess |
| 融合研究 | 38294026557は03:54 JST waiting_for_race_hours・保存0 | 38337996300で初回2件保存。38346918562・38347257256はsuccess、約4分間隔で継続。38347590268は確認時実行中 |
| Discord V2 | 開始時送信70・active_missedなし | 38341778146はsent139/missed1/catch_up9でfailure。直近も同じ未送信によるfailure、配信自体は継続 |

研究33テスト、X60テスト、Discordレビューを含む50テストが成功。X/Discordの検証では外部通信を遮断。PR #28の2検証ジョブとPR #29の50件検証もクラウドで成功。本番投稿を伴うテスト・既存ジョブの再実行・停止・無効化・再起動は行っていない。X反映後は通常のpush・継続実行で確認した。

## 4. Discordへの影響

13:40保存記録: sent193 / missed1 / catch_up6。開始時の確認済み70件のmessage_idは全件不変。X反映直前の181件も反映後に全件保持を確認した。未送信は鳴門8Rゆうきの1件。

以下3ファイルのSHA256は開始前・最終mainで一致:

| ファイル | SHA256 |
|---|---|
| discord-delivery-v2-production.yml | a333ca8c7b5a3e2844e96d5be54272999755d8f21024471495dc8845c11205c1 |
| discord_notify.yml | 111fa57067c3b5dc7b445fe9837ea263b98c4e8528cb90ea979d2b8788637031 |
| prototype3-delivery.yml | e01766449365b402224da70cd6390ac7f0004479bbb753ce4a58126c7d36d64a |

Webhook・Secrets・配信スケジュール・予想計算・締切・送信先は変更していない。共有のdirect_discord_notify、prototype3_delivery、x_post_delivery、api_serverも本修正では変更なし。

RenderのXサーバーとDiscord質問ボットはmainを参照する。反映前後でlive deploy IDは不変、新規デプロイ・再起動なし。commit_ignoredイベント自体は取得できておらず、デプロイ履歴・イベントの確認範囲で新規起動がないことを確認した。

## 5. Xの重複・未送信・費用監視

13:37のreportは `checked_with_quarantine`。12日は予想30・結果29、13日は予想12・結果10。確認済み81件の再起動後重複ガードを検証。反映直後の79件は投稿ID79件がすべて一意だった。

唐津9R結果の原本statusはuncertainのまま、owner・content hashも不変、結果投稿IDなし。レビュー済みの同一claimのみを隔離する。消失・改変は送信を禁止し、新規・未レビューの不明投稿はdegradedを維持する。送信済み扱いへの変更、削除、再投稿はしていない。

13日の確認済み投稿費用見積もりは $0.33。API請求額ではなく、確認済み作成件数×$0.015の既存監視値。12日の不明API試行と日次上限30件の監視も残っている。13日の結果未確定2件は監視上pendingであり、配信漏れと断定しない。

## 6. 新ゆうき予想の保存・公式照合

研究データ固定参照: `663a55e93c`（research-fusion-shadow-stateの13:40取得時参照）。エンジン `new-yuuki-fusion-shadow-v2`。

- 予想29レース。29件すべて生成時刻≤GitHub保存時刻<締切を検証。
- checkpoint29件がeligible、原本29件のSHA256を再計算して一致を確認。
- 初回平和島4R・浜名湖3Rの原本digestは後続処理でも不変。
- 公式結果照合22件。後から取得した公式詳細は別ファイル18件に追記し、予想・最初の評価を上書きしない。
- 締切前に収集できなかった29レースはmissingとして明示。過去予想を生成して穴埋めしていない。
- 1〜6艇の頭確率、勝ち筋・条件・負け筋、採用/不採用理由、本線/抑え、ST・展示・モーター・選手・場況の取得根拠と欠損を保存。通常展開の学習と事故を区別し、事故不明なら不明とする。
- 比較AIは事前入力から再計算した研究比較であり、実際のDiscord配信買い目と同一だとは扱わない。
- 頭確率・展開補正は未校正の研究値。22件の仮想成績は的中6件（27.3%）、投資22,000円、払戻7,670円、回収率34.9%。本番配信へ昇格できる精度とは判断していない。

Discord/Xへの研究通知は無効。独立した研究ブランチで約4分間隔の継続実行を確認した。夜間も次の研究実行を継続予約する設計だが、翌朝の実稼働までの観測はまだ行っていない。main側の元scheduleを修正したという意味ではない。

## 7. スプレッドシート

https://docs.google.com/spreadsheets/d/1dbUPyfxjIRaT-G8F_LlGMX7Ld_ZB951UmF4HpW_PYJo/edit

- 新レース29件、艇別174件（各レース6艇）、公式結果22件を表示。
- 旧18レースは開始前バックアップと全19列で一致。旧艇別108件も18レース×6艇のIDを保持。
- 新ログIDは `racekey:engine_version`、29件すべて一意。
- B3の日付・E3の場ドロップダウン、A8の既存FILTER式、非表示候補タブを保持。
- 2026-10-13 / すべてで29件表示。以前の浜名湖選択テストも一致。最後は上記選択に復元している。
- 買い目・6艇の勝ち筋/負け筋・根拠・情報不足・公式結果・振り返り・原本URLを閲覧可能。
- 研究ログ保存はシート書き込みやDiscordの成否から独立。シート失敗で原本が失われない。

## 8. 保留・次の課題

1. Discord鳴門8R未送信は解消していない。欠場は事後確認であり、正常扱いにする根拠が不足するためdegradedを解除しない。PR #29はドラフトで保留。5艇予想対応は計算に影響するので別検証が必要。
2. X唐津9R結果の実投稿有無は未確定。新規投稿機能は復旧しているが、該当投稿は無条件に再送しない。
3. 翌朝までの研究継続の観測、未取得の本番ST・決まり手等の追加検証、予想精度の改善が必要。原本の事後変更は禁止。
4. PR #27全体はマージしない。研究は隔離運用のまま。mainへ既に入ったX修正を重ねて反映しない。

## 完了条件の判定

| 条件 | 判定 |
|---|---|
| Discord停止・設定変更なし | 確認済み |
| Discord配信漏れなし | 未達: 鳴門8Rゆうき1件 |
| X uncertainの解決または安全隔離 | 安全隔離済み |
| X二重投稿 | 保存履歴に重複なし、ガード継続。不明1件の実投稿有無は断定しない |
| 研究の継続実行 | 当日日中の継続実行を確認、翌朝の観測は未実施 |
| 新ロジック保存 | 29件、全件締切前保存 |
| 公式照合 | 22件 |
| シート・プルダウン | 動作と表示を確認 |
| 旧ログ保持 | 18レース・艇別108件を保持 |

今回の3段階の作業はここで終了。保留事項を成功扱いにして隠さず、既存配信を優先する。
