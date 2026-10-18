# 新ゆうき 展開予想研究 v2

PR31を基点にした手動・オフラインの研究版。全6艇の勝ち筋・負け筋、攻めの起点と連動、他5艇の反応、2/3着の候補理由を保存する。既存配信・本番予想・設定・データ取得への接続は追加していない。

`engine.py` は標準ライブラリのみ。`adapters.py` は締切前の研究原本を検証して読み、`batch.py` は全予想の保存完了後に別工程で結果を開く。ネットワーク、自動起動、Discord、X、Sheets書込、投票の処理は持たない。

入力は艇ごとの `lane / course / racer_id / avg_st / motor_top2_rate` と、任意の `straight_time / turn_time / lap_time / exhibition_time / course_top2_rate / observations`。欠測はnull、率は0〜100、時間は秒。`meta` は `day / jcd / rno / deadline / captured_at`、任意の `db_snapshot_at / source_observed_at`。`engine.generate()` が検証する。完全に同じ6艇のタイムや6艇揃わない計測に優劣順位を付けない。

履歴の平均ST差0.03秒、計測順位2位まで、各分岐3組というルールは研究用の固定仮説。校正済み確率ではない。モーター2連率を伸び・出足の証拠に置き換えない。実測の測定区間は場ごとに違い得るため、同じレース内でのみ比較する。風・波・潮は保存・層別比較だけに使い、未検証の補正を加えない。

`live` は実際の生成時刻が締切3分以上前のときだけ許可し、保存チェックポイントが未確認の状態を `prospective_uncheckpointed` と明記する。過去の時刻を入力しても過去の事前予想にはならない。`replay` は常に `retrospective_replay`。原本と出力はSHAで結び、完全なJSONを排他的に保存して上書きしない。

任意の10点カードを比べる場合は、元の10点と120通り全ての固定順位を一緒に渡す。主力6点を保持し、観測が支持する展開候補から順位順に残り4点を埋める。不足分は元のカードで補う。これは仮想比較であり、買い目の推奨ではない。

## 実行

```bash
python3 -m unittest discover -s research/scenario_v2/tests -v
python3 -m unittest discover -s research/scenario_v1/tests -v
python3 -m research.scenario_v2.run forecast --mode live --input /path/pre_race.json --out /path/new_forecast.json
python3 -m research.scenario_v2.run forecast --mode replay --input /path/past_pre_race.json --out /path/new_replay.json
python3 -m research.scenario_v2.run review --input /path/frozen_and_result.json --out /path/new_review.json
```

reviewの入力は `{"frozen": <forecast>, "result": <result>}`。resultは `race_id / status / observed_at / trifecta / payout_per_100`、任意の `winning_method / source_url / refund_lanes / boats`。boatsを渡すなら6艇全ての `lane / racer_id / actual_course / actual_st / finish` が必要。事故・返還・不完全着順は通常展開の成績から除外。結果の着順だけでは負けた艇の戦法や進路を断定しない。

## 固定原本の比較

研究ステートを別のローカルディレクトリに読み出す。稼働中の保存先を出力先にしない。検証元のGitオブジェクトを含むローカルrepositoryを指定する。

```bash
python3 -m research.scenario_v2.batch build --source-root /path/fusion_shadow --repository /path/repository --out /path/new_replay_directory
python3 -m research.scenario_v2.batch evaluate --source-root /path/fusion_shadow --exhibition-root /path/post_race_exhibition_log --out /path/new_replay_directory
```

buildは `predictions / checkpoints` だけを読み、Gitオブジェクトの内容・日時・SHAまで検証する。evaluateは `evaluations` と事後に更新された展示結果を別に読む。後から結果が追加された展示ログを事前入力に使わない。選手、レース、進入、払戻の整合性を検査し、原本が固定された時点より新しいDBを結合しない。

出力は `protocol.json / build_receipt.json / forecasts / reviews / race_log.csv / boat_log.csv / summary.json`。出力先は新規にし、既存のファイルは上書きしない。protocolのコードハッシュが変われば同じ実験の続きとして評価できない。

## 今回の結果と資料

[結果](RESULTS.md)、[書籍手法との対応](BOOK_METHODS.md)、[PDF監査](source_audit.json)、[集計JSON](results_20261016.json)、[原本照合記録](replay_manifest_20261016.json)、[詳細診断](diagnostics_20261016.json)。サンプル原本・事後照合は examples/ にある。全文・画像・OCRなど書籍の複製は含めない。

新規35テストとPR31の回帰4テストが成功。v2の本当の事前運用実績は0件、映像での展開確認も0件。全艇の頭を仮説に含めることや、全ての決まり手を列挙することを的中率に数えない。公式の決まり手と着順が整合しても、他艇の攻めの起点・抵抗が正しかった証明にはならない。
