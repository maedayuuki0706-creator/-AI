# 航跡・融合AI v2 引き継ぎ（2026-11-02）

## 結論
研究用のデータ照合・既存展開ロジック統合・時系列再生検証・閲覧画面は動作する。**校正済み120確率モデル、高精度化、本番稼働の完成ではない。**
950Rの比較では展開連動版が単純な場別頻度モデルより悪化。採用判定は見送り。既存配信・本番モデル・Secrets・Render・Cloudflare設定は変更していない。

## 監査・再利用

|ソース|固定したコミット・実施|
|---|---|
|PR56|a9eeba6d0958e0d9c94674805510c01e716f51d7 を起点。v1 engineの予測時点より後のオリ展採用を修正|
|PR55|99596b047d5493b3a0f1bda7a9785efba36b5a24 のvenue24 engineをそのまま再利用。24場レジストリ|
|24場state|62a9f9b60277cafd65d74cf55c2c93fddf1f948d の99596b04アーカイブ実体を読取・SHA256・全6艇照合|
|4場研究ブランチ|research/four-venue-specialists-20261017 のscenario_v2 engine/adapters/run/testsを再利用。攻め起点、反応、条件付き2・3着、勝ち筋・負け筋|
|4場state|research-venue-specialists-stateの予測原本を同一レース比較用に読取。本文digest・作成時刻を確認。外部commit時刻の証明は今回未集計|
|既存融合・新ゆうき|fusion_shadow.py、yuuki_scenario_reasoning.pyを監査。未検証の既存融合重みは取り込まず変更もしない|
|Cloudflare|boat-private-lab と ARCHIVE→boat-private-lab-archive の結合を接続済みアプリで読取確認。設定・データの書込なし|

3サイトには今回アクセス・スクレイピングしていない。サイトのコード・予想・有料データの複製ではなく、既存の独立研究コードを統合した。

## 実装済みと境界

- `core.py`: 選手×枠×レースIDを一致させ、項目ごとに出典URL・取得・公開（不明はnull）・利用可能時刻・欠測・拒否理由を記録。予測時点より後のデータ、偽装ホスト、同時刻の矛盾値、モーター周期不明を拒否。
- `fit`: 対象日の前日まで、かつ結果取得時刻が対象日0時より前の正常終了レースのみ。場別120組頻度と5走以上の選手ST平均を学習。スコアに平滑化+1。これは校正済み確率ではない。
- `predict`: 既存新ゆうきv2へ接続。展示進入を仮定し、過去平均STと利用可能な足計測から戦術条件を検査。6艇それぞれの勝ち筋/負け筋、攻めの起点、反応、相手着順候補を出す。120組の研究スコアと仮想10点を返す。確率・EVは常にnull、購入判定は見送り。
- 展示STを本番ST推定に使用しない。展示進入の欠測・重複はエラー。風・波は観測表示のみ、風向/潮位等への未検証補正を付けない。
- `run.py`: 現在時刻で締切3分前・取得後180秒以内を強制するCLI。結果追記済み入力は拒否。予測原本は上書き不可、digest検査。live原本は`prospective_uncheckpointed`に保存し、Git外部保存時刻を確認するまでは前向き実績と呼ばない。**今回、新しい当日live予測は生成していない。**
- `evaluate.py`: 時間順の拡大学習・日別再生。選手ID、正常着順、別の公式払戻結果との一致を検査。950Rの明細・入力ハッシュ・欠測/除外・場別/確定払戻帯別/勝者決まり手別・取り逃し箇所を保存。
- replayの`generated_at`は再生時計（入力取得時刻）であり、当時の実行証明ではない。モード/保存先は明示して完全分離。
- `web/`: 実データ例・検証成績、1→6艇、勝ち筋/負け筋、120行・頭フィルター、保存研究JSONの読込。デスクトップで操作確認、390px iframeで表示確認。iPhone実機・Safari未確認。
- `web/fusion-api.mjs`: BOAT LAB既存認証後に組み込むためのR2読取関数。独立プレフィックスのみ。**既存Workerには未配線、R2へ未転送、公開サイトへ未デプロイ。**
- 独立workflowはread-only、Secretsなし、cronなし、成果物uploadのみ。自動本番移行はない。

## 実際のデータ

既存公式展示ログ4,046Rを読込。PR55アーカイブ3,901Rを全て6艇の登録番号・枠で照合できた。24モデル、場別選手履歴3,404件を確認。独自展示は二次資料3,692R、公式側の締切前区分25R、非公開179R、欠測5R。25Rも本融合AIの予測時点での取得証跡とは別なので今回の前向き入力に昇格させていない。詳細は`reports/20261102/venue24_audit.json`とjoin manifest。

統合APIが受け付ける全国/当地勝率・コース/決まり手率・今節ST・オリ展・モーター周期・潮位の多くは、今回の再生予測では未接続のまま。型とゲートの実装を、実データ接続済みと混同しないこと。公式オッズの新規収集・接続も未実施。

## 検証成績

2026-10-25〜10-31、正常・照合済み950R、全レース10点×100円。結果混入しない入力射影を使うが、元データは結果追記済み可変アーカイブなので**事後検証**。

|モデル|的中|的中率|回収率|
|---|---:|---:|---:|
|場別頻度baseline|369/950|38.84%|70.87%|
|新ゆうき連動を追加|324/950|34.11%|60.71%|

同一206Rでの参考比較：連動66.35%、頻度75.17%、既存4場48.58%。入力取得時点が同一ではなく、4場原本の外部保存時刻も今回未検証なので、公正な前向き優劣の証明ではない。メインAI全体・新ゆうき本番との同一条件比較は未実施。

改善策をこの950Rに合わせて調整してから同じ期間を「未見テスト」と呼ばない。次は前向きの未見期間を固定し、オリ展・進入仮説・相手選択の各追加効果を分離検証する。採用した/落とした4点とその支持条件を原本に残している。着順だけで原因を断定しない。

## 再現

```bash
python -m unittest research.ultimate_fusion_v1.test_engine research.ultimate_fusion_v2.tests.test_core research.scenario_v2.tests.test_engine -v
node --test research/ultimate_fusion_v2/tests/api.test.mjs
python -m research.ultimate_fusion_v2.evaluate --output /tmp/fusion-eval
# 4場の照合には、stateブランチを別ディレクトリへ読取展開して --baseline-root PATH を指定。
python -m research.ultimate_fusion_v2.audit_archive --archive PATH_TO_PR55_TAR_GZ --output /tmp/fusion-audit
# 現時点の正当な公式入力を取得できた場合のみ：
python -m research.ultimate_fusion_v2.run --snapshot CURRENT_PREDEADLINE_JSON --observations OPTIONAL_OBSERVATIONS_JSON --output RESEARCH_ONLY_STATE
```

52 Python tests + 1 Node API test 合格。Python compile・JS syntax 合格。replayを再実行して集計一致を確認。元コードをコピーしただけの箇所は上記監査欄に明示。

## 本番移行までに必要なもの

1. 24場公式一次資料の収集アダプター、取得原本・モーター周期・公式オッズ、欠測率監視。研究専用stateへの締切前commit確認と失敗時停止。
2. 本番進入の不確実性、ST分布、各戦術の確率、風向・潮位と足の作用を学習するモデル。現状は展示進入固定と条件分岐で、物理/確率シミュレータではない。
3. train/calibration/testの期間固定、log loss/Brier/校正曲線、場別・オッズ帯別の標本数、時間ブロック不確実性評価。校正済みモデルIDと学習期限に紐付けて初めて120確率・公式オッズEVを解放する。
4. メイン/新ゆうき/4場/24場の同じ締切・同じ購入条件での前向き比較。改善の確認までは既存を置換しない。
5. 非公開stagingへの認証付き配線とR2研究領域への転送、iPhone実機QA。本番Workerの更新は独立したレビュー対象とする。
