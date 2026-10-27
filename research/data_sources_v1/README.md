# データ取得元の拡張と重複監査

PC不要。既存Discord・X・予想エンジン・研究worker・Secrets・Actionsを変更せず、研究ブランチ内の独立CLIで動かす。

## 今回採用するもの

|取得元・技術|用途|重複・判断|
|---|---|---|
|公式K/Bの過去365日|照合の基準。既存8876Rを読み取り専用で再利用|再ダウンロードしない。同じレースを新規実績に加算しない|
|Turnmark API v1（2026年〜）|過去の平均ST、展示進入/ST、気温水温、部品・ペラ、返還明細、過去オッズ|公式由来の非公式ミラー。既存公式値を上書きしない|
|Boatrace Open API v3 programs/previews（2025年分）|2025年の平均ST、展示ST/進入等を補完|旧APIは非推奨だが保存データを取得可能。存在・日付を各回検証|
|Boatrace Open API v1|当日情報の代替取得候補・重複照合|Turnmarkと重なるため歴史全件の二重取得はしない|
|LightGBM|公式照合済み通常6艇レースだけで時系列分割の独立診断|展示STあり/なしを比較。未検証の改善を本番へ採用しない|
|GAS|Googleサーバー上でのシート自動処理という技術知識を記録|既存Pythonのシート同期と役割が重なるので二重書き込みしない|
|Playwright|ブラウザが必要な公開データ取得の候補|現在のAPI/HTMLで足りる項目には追加しない。新規採用・稼働を装わない|
|PC-KYOTEI Database|データ仕様、SQL集計、学習データCSV出力の設計を参考にする|Windows用ソフトは導入しない。公式K/B等で取れる結果は重複|
|日和・公式の既存取得|モーター履歴・足合わせ・整備等を既存研究で取得|同一データを別AIの独立根拠として数えない|
|既存潮位処理・各場公式資料|潮汐の推算と観測・潮流を区別する|推算潮位を実測流速として代入しない|

参照した既存コード: main `hiyori_source.py`, `tide_context.py`, `sync_foot_trend_sheet.py`, `sync_st_analysis_sheet.py`, `sync_motor_data_from_results.py`。
既存研究: `research/four-venue-phase2-20261018` と `research/four-venue-source-learning-20261019`。取得処理の存在は欠測ゼロの証明ではない。

## 実行

```sh
python -m unittest discover -s research/data_sources_v1/tests -v
python -m research.data_sources_v1.collect --out data/data_sources_v1/20251018_20261019 --start 2025-10-18 --end 2026-10-19
python -m pip install -r research/data_sources_v1/requirements-research.txt
python -m research.data_sources_v1.train --out data/data_sources_v1/20251018_20261019
```

標準2ワーカー、最大4ワーカー、全体で最低1秒のリクエスト間隔、25秒タイムアウト、最大16MB/日/ソース。rawはSHA256名でgzip保存、取得時刻とURL/HTTPメタデータを別保存。同じコマンドで成功済みの日別原本を再利用。失敗の再取得は`--retry-failed`。公式基準のrefと正確なcommit・ファイルSHAをsummaryへ記録する。Turnmark取得失敗時だけOpen API v1にフォールバックし、同一原本の全件二重取得を避ける。

## データ契約

- レースID（YYYYMMDD+場2桁+R2桁）・枠・選手登録番号・モーター番号を照合。不一致は隔離し、元データの上書きをしない。
- 公式結果を正とし、ミラーの着順/ST/進入/展示タイムの相違を保存。相違レースは学習から除外する。
- 展示進入と本番進入、展示STと本番ST、展示時の気象と結果時の気象を別に保存する。
- 展示F.03は-0.03。平均STの0は欠測扱い。parts=[]/refunds=[]は確認済みのなし、nullは不明。propeller=nullは「交換なし」も含むため一律に欠測と解釈しない。
- rawと日別の研究記録は公式履歴と別管理。取得済み・公式照合済み・不足・不一致を分離して集計する。
- 同じ公式由来のAPI/CSVは独立した観測ではない。複数AI一致・標本数・確率の二重加点を禁止する。
- 歴史APIにあるオッズは取得時刻不明。締切10分前オッズや当時のEVとして利用しない。
- 全rawを保存するが学習特徴量は明示許可リストだけ。本番ST、着順、決まり手、配当、過去オッズを事前入力へ混ぜない。
- 今回取得した過去データには当時の締切前受領証がない。前向き予想・配信の成功率に含めない。
- 公式の追加照合は `gaps/race_enrichment.json.gz` に別保存。検潮所の実測潮位は場内実測や流速と区別し、当時の締切前入力へ混ぜない。モーター使用開始日の月単位・資料間の表記差を保持する。
- 当時の締切前受領証、実測流速、映像上の攻め起点、過去全開催の前検は未解決。追加取得の件数と限界は `GAPS_REPORT.md` を参照する。

## 一次資料

- https://github.com/turnmark/api/blob/gh-pages/README.md
- https://github.com/turnmark/api/blob/gh-pages/docs/v1/schema.md
- https://github.com/boatraceopenapi/api/blob/gh-pages/docs/v1/schema.md
- https://github.com/boatraceopenapi/programs/blob/gh-pages/README.md
- https://pc-kyotei.com/manual-menu/
- https://pc-kyotei.com/train-csv/
- https://developers.google.com/apps-script/overview?hl=ja
- https://lightgbm.readthedocs.io/en/stable/
- https://playwright.dev/docs/intro

自動実行・既存シートへの書込・本番採用は接続していない。今回のCLI実行実績と全件の欠測率はdata/data_sources_v1以下のREPORT.md/summary.jsonを参照する。

データ原本は別のデータ専用ZIP（競艇AI_追加研究データ_20251018-20261019.zip）として保存。コードはGitHubのこの研究ブランチを正本とし、ZIPへ重複収録しない。ZIPをリポジトリ直下に展開すると上記のdata/data_sources_v1へ復元できる。

## 公式の残不足データ

`gaps.py` は単発の取得CLI。気象庁39か月・地点ファイルと各場の公式原本を保存する。最小1秒間隔・2ワーカー・成功済み原本再利用。予想や通知に接続しない。

```sh
python -m research.data_sources_v1.gaps --data data/data_sources_v1/20251018_20261019
python -m research.data_sources_v1.gaps --offline --data data/data_sources_v1/20251018_20261019 --motor-catalog research/data_sources_v1/gap_motor_cycles.json --series-catalog research/data_sources_v1/gap_preinspection_series.json
```

月・地点・年・日・毎時の固定長を検証し、締切予定時刻以前の同一時間の潮位だけに結合する。各局の基準面cmを保持し、推算潮位との単純な差引きや標高換算はしない。毎時平滑値は事後公開なので、当時使えた特徴量として扱わない。
`--offline` はネットワークを使わず保存原本だけで照合を再現する。日付・開催の設定は今回レビューした原本SHAに固定してあり、新しい開催へ流用するには原本の再確認とカタログ更新が必要。
浜名湖の中間整備PDFから確認した10件はデータZIP内 `gaps/motor_maintenance_records.json` に構造化保存。年全体の整備網羅性や当日取得を示さず、学習へ自動投入しない。
