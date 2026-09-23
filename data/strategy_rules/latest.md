# 勝ちルール探索レポート

対象 1430R / 11日 / 的中率 39.6% / 回収率 68.9% / 収支 -548,130円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

まだなし。サンプル不足または再現性不足。

## 見送り候補

- head_top=25-34% / head_gap=<5pt: 検証 35R / 的中25.7% / ROI36.2%
- event=normal / head_gap=<5pt: 検証 36R / 的中25.0% / ROI38.9%
- head_gap=<5pt: 検証 64R / 的中28.1% / ROI44.3%
- grade=C / head_gap=<5pt: 検証 64R / 的中28.1% / ROI44.3%
- points=13-14 / head_gap=<5pt: 検証 56R / 的中25.0% / ROI44.4%
- head_top=<25%: 検証 32R / 的中28.1% / ROI48.9%
- event=normal / head_gap=5-9pt: 検証 32R / 的中25.0% / ROI49.4%
- score=<60 / head_gap=<5pt: 検証 44R / 的中29.5% / ROI51.9%
- head_top=<25% / head_gap=<5pt: 検証 29R / 的中31.0% / ROI53.8%
- points=11-12 / head_gap=10-19pt: 検証 111R / 的中45.9% / ROI63.2%
- points=11-12: 検証 147R / 的中46.9% / ROI63.4%
- selected=no / points=11-12: 検証 131R / 的中45.0% / ROI63.9%
- grade=B / head_gap=10-19pt: 検証 118R / 的中46.6% / ROI65.3%
- score=75-84: 検証 91R / 的中49.5% / ROI66.0%
- selected=yes: 検証 94R / 的中50.0% / ROI66.3%
- grade=C / head_gap=5-9pt: 検証 49R / 的中34.7% / ROI66.5%
- score=60-74 / head_gap=5-9pt: 検証 27R / 的中37.0% / ROI69.4%
- grade=B: 検証 207R / 的中44.4% / ROI72.3%
- tide_applicable=no: 検証 442R / 的中42.3% / ROI73.0%
- selected=no: 検証 348R / 的中40.2% / ROI74.4%
