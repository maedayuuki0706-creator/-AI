# 勝ちルール探索レポート

対象 6373R / 58日 / 的中率 43.7% / 回収率 73.0% / 収支 -2,006,770円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=びわこ / wind=0-1m: 検証 25R / 的中48.0% / ROI163.5%
- venue=下関 / wind=2-3m: 検証 24R / 的中45.8% / ROI109.6%
- venue=芦屋 / wave=0-2cm: 検証 54R / 的中63.0% / ROI102.5%

## 見送り候補

- venue=鳴門 / tide_level=low: 検証 26R / 的中26.9% / ROI16.9%
- head_gap=<5pt / slit_shape=flat_or_inner: 検証 26R / 的中23.1% / ROI28.9%
- venue=丸亀 / tide_level=low: 検証 33R / 的中33.3% / ROI32.6%
- tide_phase=rising / slit_shape=outer_attack_4: 検証 31R / 的中25.8% / ROI33.4%
- outer_fast=no / head_gap=<5pt: 検証 32R / 的中25.0% / ROI35.2%
- venue=鳴門 / tide_phase=rising: 検証 38R / 的中31.6% / ROI35.7%
- venue=鳴門 / wave=3-6cm: 検証 28R / 的中28.6% / ROI37.2%
- venue=鳴門 / grade=B: 検証 42R / 的中33.3% / ROI37.7%
- venue=若松 / wave=3-6cm: 検証 28R / 的中39.3% / ROI37.8%
- venue=桐生 / grade=A: 検証 26R / 的中26.9% / ROI37.8%
- outer_fast=no / head_gap=5-9pt: 検証 30R / 的中26.7% / ROI38.0%
- attack_style_prior=dominant_makurizashi: 検証 35R / 的中28.6% / ROI40.2%
- venue=福岡 / tide_level=mid: 検証 35R / 的中25.7% / ROI41.0%
- venue=桐生 / wind=2-3m: 検証 35R / 的中25.7% / ROI41.9%
- venue=浜名湖 / grade=B: 検証 33R / 的中33.3% / ROI42.5%
- venue=丸亀 / grade=B: 検証 38R / 的中34.2% / ROI43.3%
- venue=桐生 / head_gap=20pt+: 検証 47R / 的中34.0% / ROI43.9%
- tide_phase=rising / slit_shape=strong_outer_attack_4: 検証 54R / 的中27.8% / ROI44.6%
- venue=常滑 / grade=B: 検証 51R / 的中31.4% / ROI46.1%
- venue=常滑 / wind=4m+: 検証 37R / 的中35.1% / ROI46.2%
