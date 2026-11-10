# 勝ちルール探索レポート

対象 5994R / 55日 / 的中率 43.5% / 回収率 73.4% / 収支 -1,860,480円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=びわこ / wave=0-2cm: 検証 35R / 的中48.6% / ROI123.4%
- venue=下関 / wind=2-3m: 検証 24R / 的中45.8% / ROI109.6%
- venue=芦屋 / wave=0-2cm: 検証 54R / 的中63.0% / ROI102.5%

## 見送り候補

- venue=丸亀 / tide_level=low: 検証 31R / 的中32.3% / ROI32.5%
- venue=常滑 / grade=B: 検証 42R / 的中31.0% / ROI34.7%
- tide_phase=rising / slit_shape=outer_attack_4: 検証 28R / 的中25.0% / ROI34.9%
- venue=鳴門 / grade=B: 検証 45R / 的中31.1% / ROI35.3%
- venue=鳴門 / wave=3-6cm: 検証 32R / 的中31.2% / ROI36.9%
- venue=鳴門 / tide_phase=rising: 検証 45R / 的中28.9% / ROI37.3%
- venue=桐生 / grade=A: 検証 26R / 的中26.9% / ROI37.8%
- attack_style_prior=dominant_makurizashi: 検証 36R / 的中27.8% / ROI38.9%
- venue=平和島 / wind=2-3m: 検証 47R / 的中25.5% / ROI40.5%
- venue=桐生 / wind=2-3m: 検証 35R / 的中25.7% / ROI41.9%
- venue=丸亀 / grade=B: 検証 38R / 的中34.2% / ROI43.3%
- venue=桐生 / head_gap=20pt+: 検証 47R / 的中34.0% / ROI43.9%
- venue=若松 / wave=3-6cm: 検証 28R / 的中35.7% / ROI44.4%
- outer_fast=no / head_gap=10-19pt: 検証 54R / 的中31.5% / ROI44.6%
- venue=鳴門 / slit_shape=outer_pressure: 検証 32R / 的中28.1% / ROI45.4%
- venue=浜名湖 / grade=B: 検証 40R / 的中30.0% / ROI45.6%
- venue=常滑 / wind=4m+: 検証 37R / 的中35.1% / ROI46.2%
- tide_phase=rising / slit_shape=strong_outer_attack_4: 検証 51R / 的中29.4% / ROI47.0%
- score=60-74 / head_gap=5-9pt: 検証 67R / 的中32.8% / ROI48.0%
- venue=鳴門: 検証 87R / 的中34.5% / ROI48.5%
