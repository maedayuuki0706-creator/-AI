# 新ゆうき融合：期間外検証の準備と収集監査（2026-10-15）
## 完了
- no_alt_head_v1の候補ルールと選択関数のハッシュを固定。既存の研究候補JSONは変更していない。
- 期間外検証ツール research_no_alt_head_holdout.py を追加。10/16〜22を対象に、候補確定前の予想・10/13〜14の探索データを除外する。
- 欠測・保存確認待ちを外れに数えず、データなしは WAITING_FOR_ELIGIBLE_FUTURE_DATA と表示。0%や検証済みと誤表示しない。
- ソースコード・選択ルールが異なるデータは互換性不一致として除外。保存予想の完全再現と元の払戻評価の一致が必要。
- research_fusion_collection_audit.py を追加。Actionsの成功ではなく、取得成否とheartbeat鮮度を別に判定する。
- 研究テスト21件成功。既存データ258件は全件期間外のため、新しい期間の実績は0件。探索結果77.62%を期間外成績に流用しない。

## 固定した評価方針
候補は本線rank_score上位6点＋本線を除くcover_score上位4点。別頭優先のみ除去し、確率補正や各100円は維持。
対象期間は10/16〜22。返還のない確定レースを同一予算で比較し、日別結果も表示する。
200レース・3開催日を運用上の最低目安とするが、統計的保証ではない。目安に達しても自動採用しない。
元コードSHAはf4b1f11a7a7fd542ec49ee475900a7396f2a727e、元選択ルールはnew-yuuki-six-boat-v2に限定。別版への一般化は別の検証が必要。

## 収集の問題：未修復
確認した研究stateのtreeは e362f9cf3546cce77ef12c426fe79e4c8a7598f7。
予想は10/13=103件、10/14=155件、10/15は0件。
最新heartbeatは10/15 19:28:06 JST。収集対象3件が全てbudget_exceeded。
当該heartbeat時点の未収集記録は146件。これは19:28時点の記録であり、その日の最終未収集数ではない。
該当Actions run 38720313542 / job 116372965486 はsuccess。しかし新規予想保存の確認は0件。
研究runnerは全体85秒、レースごとの子プロセスは最大55秒。時間切れ時に取得のどの段階で止まったかは現在のログでは特定できない。
したがって「重い関数を特定・修理した」とは言わない。

また、確認したmainのfusion_shadow_runner.pyはcore.build_prediction()を呼ぶが、研究ブランチの基礎コードと保存済みV2のソースは異なる。未来データが別版なら本評価には入れない。

## 次に必要な実装（未実施）
1. 固定ソースを使う研究専用の収集処理で、公式取得・日和取得・DB補正・モデル構築などの所要時間を記録し、時間切れの段階を特定する。
2. 投稿・本番設定・既存Actionsに接続しない独立環境で修正を検証する。
3. 締切前に保存された追加データを確保し、この固定プランで評価する。
これらの収集復旧・定期起動は今回有効化していない。評価ツールを保存しただけで、明日から自動検証が動くわけではない。

## 実行方法
```bash
python -m unittest discover -s tests -p 'test_research*.py' -v
python research_no_alt_head_holdout.py --state-root /path/to/data/fusion_shadow
python research_fusion_collection_audit.py --state-root /path/to/data/fusion_shadow
```

変更は研究ブランチ内の追加ファイルだけ。main・既存配信・既存Actions・Secrets・Sheets・研究stateを変更していない。
