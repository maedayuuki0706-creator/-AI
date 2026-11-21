# 勝ちルール探索レポート

対象 6502R / 59日 / 的中率 43.7% / 回収率 73.3% / 収支 -2,029,730円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=びわこ / wind=0-1m: 検証 25R / 的中48.0% / ROI163.5%
- venue=下関 / wind=2-3m: 検証 24R / 的中45.8% / ROI109.6%

## 見送り候補

- tide_phase=rising / slit_shape=outer_attack_4: 検証 29R / 的中24.1% / ROI28.5%
- outer_fast=no / head_gap=5-9pt: 検証 28R / 的中21.4% / ROI32.5%
- venue=丸亀 / tide_level=low: 検証 33R / 的中33.3% / ROI32.6%
- venue=福岡 / tide_level=mid: 検証 32R / 的中25.0% / ROI33.9%
- head_gap=<5pt / slit_shape=flat_or_inner: 検証 24R / 的中25.0% / ROI34.6%
- venue=浜名湖 / grade=B: 検証 27R / 的中29.6% / ROI36.8%
- venue=多摩川 / attack_lane=none: 検証 32R / 的中37.5% / ROI36.9%
- venue=多摩川 / slit_shape=outer_pressure: 検証 24R / 的中37.5% / ROI37.0%
- attack_style_prior=dominant_makurizashi: 検証 35R / 的中25.7% / ROI38.2%
- venue=福岡 / tide_phase=falling: 検証 58R / 的中31.0% / ROI39.9%
- outer_fast=no / head_gap=<5pt: 検証 30R / 的中26.7% / ROI40.3%
- venue=鳴門 / grade=B: 検証 34R / 的中32.4% / ROI40.4%
- venue=丸亀 / grade=B: 検証 38R / 的中34.2% / ROI43.3%
- venue=福岡 / grade=C: 検証 42R / 的中33.3% / ROI44.2%
- venue=福岡 / wave=3-6cm: 検証 70R / 的中40.0% / ROI44.5%
- venue=津 / grade=A: 検証 28R / 的中50.0% / ROI44.7%
- venue=福岡 / attack_lane=none: 検証 41R / 的中34.1% / ROI45.3%
- venue=桐生 / wind=2-3m: 検証 37R / 的中27.0% / ROI45.4%
- venue=常滑 / grade=B: 検証 51R / 的中31.4% / ROI46.1%
- venue=常滑 / wind=4m+: 検証 37R / 的中35.1% / ROI46.2%
