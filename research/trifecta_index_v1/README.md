# 3連単120通り・的中指数LOG（独立研究版）

新ゆうきと江戸川・児島・唐津・浜名湖の場別研究AIに、120通りの順位と事後検証の記録を追加する、**研究専用・独立サイドカー**。

## 指数の読み方

- 3連単120通りに rank 1〜120 を付与。index_0_100 は同じレース内の相対強度であり、実測的中確率、%表示、期待値、舟券の推奨ではない。
- 同点内は出目文字列の順番に便宜的に採番する。tied_rank_start / tied_count を必ず併記する。
- 新ゆうき（yuuki_v2）：事前の展開仮説の支持観測に基づく未校正の構造順位。形成根拠を持たない出目には unscored_fallback=true を記録する。
- 場別v1（venue_v1）：各場の共通v2展開＋事前に検証されたコース調整（未検証ならゼロ）の独立順位。
- 場別Phase2（venue_phase2）：各場専用A/Bモデルが既に出した全120順位をそのまま残す。historical_score は学習からの強度で、確率校正済みではない。Bモデルでは支持根拠優先のため点数の単純降順と異なることがある。
- 全120順位を付けても下位の的中指数が実際に予測力を持つとは限らない。まずLOGから検証する。

## 入力とコマンド

入力は締切前の研究用予想原本JSON。出走表・結果のスクレイピング、Discord/X投稿、既存状態ブランチへの書込みはこのモジュールにはない。

    python -m research.trifecta_index_v1.index --kind yuuki_v2 --record /path/to/frozen_yuuki.json --out-dir /tmp/index-state
    python -m research.trifecta_index_v1.index --kind venue_v1 --record /path/to/frozen_venue.json --out-dir /tmp/index-state
    python -m research.trifecta_index_v1.index --kind venue_phase2 --record /path/to/frozen_venue_phase2_B.json --out-dir /tmp/index-state

保存：forecasts/<model_slug>/<YYYYMMDD_jcd_rr>.json。レースID・モデル版・入力ダイジェスト・締切・生成時刻・全120通りの順位・研究指数・同点・展開根拠を固定。既存ファイルへの上書きを拒否。

公式結果による事後検証は必ず別実行：

    python -m research.trifecta_index_v1.index --record /tmp/index-state/forecasts/yuuki-v2/20261021_06_03.json --official-result /path/to/result.json --out-dir /tmp/index-state

結果ファイルには race_id / observed_at（締切後）/ trifecta / normal_verified / refund_lanes が必要。正常・返還なしを確認できるときだけ、実際の出目が何位かと上位1・3・5・10・20・30・60位内判定を reviews 配下に固定保存。事故・返還・結果欠測は非対象扱いでLOGは残す。

## 誤認防止と制約

- 予想順位の生成では一切公式結果を読み込まない。予想と結果のハッシュは別。
- 予想後に作成したsidecarは締切前に存在した証明にならない。remote_predeadline_receipt_verified=false / count_as_prospective=false を固定する。
- 新ゆうき・場別の動いている研究Jobへの呼出し、自動スケジュール、専用stateへのpushと遠隔受領確認は未実装。PRだけでは毎レース自動更新されない。
- 既存Discord・X配信・本番予想・既存研究ジョブ・Secrets・設定・ワークフローは無変更。
- 検証完了後に、既存と独立した研究専用Jobで締切前に各モデルの出力を取得し、この処理を呼ぶ。未来レース実績として採用するには締切前の遠隔受領書が別途必要。

## テスト

    python -m unittest research.trifecta_index_v1.test_index -v

網羅120通り、各場の名称、Phase2のネイティブ順位保持、重複拒否、正常結果の順位評価、事故除外、早すぎる結果の拒否、改ざん・二重上書きの拒否をチェックする。
