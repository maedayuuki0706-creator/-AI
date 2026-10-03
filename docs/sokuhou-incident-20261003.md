# 速報くん：2026-10-03 障害修正と運用

## 確認できた原因

- Actions run `37094000166` / job `111120359859` と run `37098358294` / job `111132945376` で、通知送信後の `git pull --rebase` が `data/x_post_delivery/20261003.json` の競合により失敗していた。同じ的中が両方の実行ログに存在する。
- 通知・予想・速報の記録を一括保存していたため、X記録との競合で速報の送信済み記録までmainに残らず、次のcheckoutで再送された。
- `b62cd0b` のconcurrency編集で実際の改行が文字列 `\n` になり、設定全体がコメント化された。2026-10-03 14:51 JST以降はジョブを作成する前に失敗している。
- 取得時のmainには当日10:29 JSTまでしかメイン予想・速報の記録がない。未保存期間について、記録がないことを「未送信」の証拠としては扱わない。

## 修正内容

1. concurrencyを有効なYAMLへ戻し、実行中のwatcherを新しいcronでキャンセルしない。
2. `persist_runtime_data.py` は最新のremote mainから一時indexでコミットを作る。JSONLの追記とX送信済み集合を統合し、fast-forwardだけを許可する。稼働中checkoutのrebase、reset、force pushは行わない。X以外の記録を各周回で保存し、Xの記録は別段階で保存する。
3. `sokuhou-delivery-state` ブランチにAI・日付・場・レース番号で一意なレコードを作成してからDiscordへ送信する。送信後は `wait=true` のメッセージIDを保存する。mainの保存失敗や再起動で同じレースを再送しない。
4. タイムアウト・5xx・応答欠落は `uncertain`、送信途中の中断は `sending` のまま保留する。自動再送しない。明確な429拒否のみ待機付きで最大3回まで試す。4xx拒否は `failed` にする。
5. 再開時刻より前に締め切ったレースは通知しない。メイン・中穴・穴の的中結果は `suppressed` として成績集計に含める。ゆうきも古い的中を再送しない。
6. 保存障害や保留をActions失敗として表示する。Discordの応答取得後、保存だけ失敗した場合は `data/sokuhou_recovery/` に応答IDを残す。メインworkflow失敗時は復旧用artifactを7日間保持する。

## 運用

- 一時停止：`sokuhou_policy.json` の `enabled` を `false` にする。`SOKUHOU_PAUSED=1` も停止を優先する。予想配信自体は継続する。
- 再開：両配信workflowのWebhook参照を有効にし、`resume_after` に明示的なJST日時を設定、テスト通過後 `enabled=true` にする。古いレースの一括再送は行わない。
- 健康確認：`python sokuhou_health.py`。Actionsサマリーに送信済み件数と保留キーを出す。状態ブランチへの接続障害も失敗扱い。
- `sending` / `uncertain`：Discordの該当AI・場・レースを確認する。配信を確認できたものだけメッセージID付きで `sent` に修復する。未配信が確認できるまでclaimを削除しない。
- `failed`：HTTPコードとWebhook設定を確認する。秘密URL・tokenはログに出さない。
- `data/sokuhou_recovery/` にIDがある場合は、そのIDでDiscordメッセージの存在を確認してから状態ブランチを修復する。

DiscordとGitHubの間には単一トランザクションがないため、送信完了と記録の間の通信切断を完全なexactly-onceとして保証することはできない。判断不能時は連投を避けて保留し、明示的に検出する設計。

## 検証

`python -m unittest tests.test_sokuhou_delivery tests.test_sokuhou_workflows tests.test_hit_alerts_fast tests.test_hit_alerts tests.test_persist_runtime_data tests.test_discord_notification_policy tests.test_interim_report test_yuuki_hit_alerts -v`

同一レースの並列実行、プロセス中断、ローカル記録喪失、Discord成功後の保存障害、429、タイムアウト、別AI・別場・別日の独立性、X記録と速報記録の同時更新を検証する。

全体テストも修正前後で比較した。修正前は216件中20件失敗（14 failure / 6 error）、修正後の初回は239件中18件失敗（12 failure / 6 error）。残る18件はすべて修正前にも存在し、X配信・旧通知仕様などのテストで、新規失敗はない。今回の速報修正を全体システムの全テスト成功とは扱わない。
