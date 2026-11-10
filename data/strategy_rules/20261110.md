# 勝ちルール探索レポート

対象 5873R / 55日 / 的中率 43.6% / 回収率 73.2% / 収支 -1,837,810円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=びわこ / wave=0-2cm: 検証 35R / 的中48.6% / ROI123.4%
- venue=芦屋 / wave=0-2cm: 検証 54R / 的中63.0% / ROI102.5%

## 見送り候補

- venue=丸亀 / tide_level=low: 検証 31R / 的中32.3% / ROI32.5%
- venue=常滑 / grade=B: 検証 39R / 的中30.8% / ROI34.4%
- tide_phase=rising / slit_shape=outer_attack_4: 検証 28R / 的中25.0% / ROI34.9%
- venue=鳴門 / grade=B: 検証 41R / 的中31.7% / ROI36.2%
- venue=三国 / slit_shape=outer_pressure: 検証 26R / 的中34.6% / ROI36.4%
- venue=桐生 / grade=A: 検証 26R / 的中26.9% / ROI37.8%
- venue=平和島 / wind=2-3m: 検証 38R / 的中23.7% / ROI38.6%
- attack_style_prior=dominant_makurizashi: 検証 34R / 的中29.4% / ROI41.2%
- venue=桐生 / wind=2-3m: 検証 35R / 的中25.7% / ROI41.9%
- venue=鳴門 / tide_phase=rising: 検証 40R / 的中32.5% / ROI42.1%
- outer_fast=no / head_gap=10-19pt: 検証 53R / 的中30.2% / ROI43.0%
- venue=丸亀 / grade=B: 検証 38R / 的中34.2% / ROI43.3%
- venue=桐生 / head_gap=20pt+: 検証 47R / 的中34.0% / ROI43.9%
- venue=若松 / wave=3-6cm: 検証 28R / 的中35.7% / ROI44.4%
- venue=浜名湖 / grade=B: 検証 40R / 的中30.0% / ROI45.6%
- venue=鳴門 / wave=3-6cm: 検証 26R / 的中38.5% / ROI45.6%
- venue=三国 / attack_lane=none: 検証 24R / 的中41.7% / ROI45.7%
- venue=常滑 / wind=4m+: 検証 35R / 的中34.3% / ROI45.8%
- head_gap=10-19pt / slit_shape=flat_or_inner: 検証 43R / 的中32.6% / ROI47.0%
- venue=鳴門 / slit_shape=outer_pressure: 検証 31R / 的中29.0% / ROI47.1%
