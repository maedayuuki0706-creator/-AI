# 全24場専門AI・オリジナル展示データ保管庫（研究版v1）

独立した新規研究コードです。既存の江戸川・浜名湖・児島・唐津4場専門AI、既存の本番予想、Discord、X、Cloudflare、Render、Secrets、定期運用を変更しません。各場専用の実績・選手別履歴を24モデル分作成し、公式展示と独自展示を選手登録番号・進入・モーターで厳密照合します。

## 実際に利用できるもの

- 24場の公式展示: 既存mainの data/exhibition_log/YYYYMMDD/CC_RR.json に保存済みの展示タイム、展示ST、進入、チルトと結果を読み取る。未保存レースは補完しない。
- 独自展示: 独立した research-materials-state-v1 ブランチの original_foot/*.json を読み取り、当該6艇の登録番号・モーター番号・枠、競走番号、取得時刻を照合。原本のSHA256・公式URL・取得時刻を保持。
- 各選手の会場別履歴: players/CC/登録番号.json にレース別の公式展示、独自展示、着順を保持。各AIの racer_observations はその場の過去日だけで集計。
- 場別AI 24体: models/基準日/01.json〜24.json。会場ごとの進入コース別・選手別の実測集計を持つ。少数標本なら値をnullにする。研究指数は未校正であり、予測確率・買い目・期待値の主張は禁止。
- 時系列分離: モデル学習に基準日当日の結果は含めない。
- 不変保存: 同名ファイルの内容が異なればエラー。既存原本を上書きしない。

## 重要な限界

2026年11月1日時点で、各場公式サイトの一次資料として検証済みの自動取得先は唐津だけです。一方、新たに公開データ BoatraceCSV の日次CSVを使い、江戸川以外の23場について二次資料のオリジナル展示を一括取り込みする研究用mirror.pyを追加しました。各場の公式サイトから直接取得した証拠とは区別し、retrospective_secondary_source と明記します。江戸川は独自展示の公開が確認できず非公開扱いとします。桐生は1周ではなく半周、住之江・尼崎・徳山は直線の欠測を前提とします。異なる場の秒数をそのまま比較しません。

24場の公式展示は全国共通の既存保管庫を利用しますが、その他の場の独自展示を自動取得するには、各公式ページのURL・列定義・測定区間・公開時刻と個別収集アダプターの検証が必要です。存在しないデータは推測で作りません。

## CLI

Python標準ライブラリのみ。--through はこの日の前日までを学習する厳格な境界です。

~~~sh
python -m unittest research.venue24_v1.test_engine -v

python -m research.venue24_v1.engine \
  --official-dir data/exhibition_log \
  --original-dir /absolute/path/to/research-materials-state-v1/original_foot \
  --out /absolute/path/to/dedicated-venue24-state/data/venue24_v1 \
  --through 20261101
~~~

出力: races/日付/、players/会場番号/登録番号.json、models/学習基準日/会場番号.json、reports/基準日/build.json。すべて不変で、同じ日付に原本を変更して再実行すると競合を検出します。

## 運用ガード

1. メイン・新ゆうき・4場専門AIの係数や買い目へ自動昇格しない。
2. 事後結果を締切前入力へ混ぜない。唐津の独自展示も予想指数にはまだ加算しない。
3. 欠測を0秒・最下位・平均値に置き換えない。
4. 新しく自動収集する場合は別の取得先・リクエスト間隔・日次チェックポイントを先に監査し、既存ワーカーの負荷に影響させない。
5. 新モデルの実戦採用には独立した前向き検証と別の承認が必要。現時点は研究モデル作成段階。

## 対象

01桐生、02戸田、03江戸川、04平和島、05多摩川、06浜名湖、07蒲郡、08常滑、09津、10三国、11びわこ、12住之江、13尼崎、14鳴門、15丸亀、16児島、17宮島、18徳山、19下関、20若松、21芦屋、22福岡、23唐津、24大村。


## 23場のオリジナル展示二次アーカイブ取込

BoatraceCSV（公開GitHub Pages、MIT表記）の original_exhibition 日付別CSVを、HTTP GETで日別最大1回（1日2MB上限）取得。source_csv と manifests に原CSV・SHA256・ダウンロード時刻を保存する。正規化前に「レースコード」「計測項目」「公式展示原本の6選手名」を厳密照合する。選手登録番号・モーター番号は、公式原本で名前一致を確認した艇についてのみ紐づける。場別の半周・一周・回り足・直線を混同しない。

公開CSVの取得日時は第三者の記録であり、当AIが締切前に受領した証拠ではない。後から取得したCSVの測定値は事後研究専用で、本番予想や前向き回収率には使用しない。一次資料の唐津データと同じレースなら公式一次資料を優先する。

~~~sh
python -m unittest discover -s research/venue24_v1 -p 'test_*.py' -v

python -m research.venue24_v1.mirror \
  --official-dir data/exhibition_log \
  --out /tmp/venue24-mirror \
  --start 20261004 --end 20261031
~~~

生成した /tmp/venue24-mirror/normalized のJSONと一次資料側 original_foot/*.json を一つの読み取り専用ディレクトリに集約して、engine.py の --original-dir に指定する。独立workflowはこの手順を実行し、初回の公式のみのv1スナップショットを維持したままv2として別保管する。研究ブランチのpushではpilotを実行できるが、mainにマージされるまでは日次scheduled workflowは有効にならない。

CSV提供元: https://boatracecsv.github.io/docs/data/previews.html
保存元リポジトリ: https://github.com/BoatraceCSV/boatracecsv.github.io
