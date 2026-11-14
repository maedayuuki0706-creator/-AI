# 勝ちルール探索レポート

対象 6260R / 57日 / 的中率 43.6% / 回収率 73.0% / 収支 -1,976,640円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=下関 / wind=2-3m: 検証 24R / 的中45.8% / ROI109.6%
- venue=びわこ / grade=B: 検証 41R / 的中46.3% / ROI106.2%
- venue=芦屋 / wave=0-2cm: 検証 54R / 的中63.0% / ROI102.5%

## 見送り候補

- venue=常滑 / grade=B: 検証 46R / 的中28.3% / ROI31.7%
- venue=若松 / tide_phase=rising: 検証 27R / 的中33.3% / ROI32.0%
- venue=丸亀 / tide_level=low: 検証 31R / 的中32.3% / ROI32.5%
- tide_phase=rising / slit_shape=outer_attack_4: 検証 31R / 的中25.8% / ROI33.2%
- head_gap=<5pt / slit_shape=flat_or_inner: 検証 24R / 的中29.2% / ROI34.3%
- outer_fast=no / head_gap=5-9pt: 検証 27R / 的中25.9% / ROI34.5%
- venue=鳴門 / grade=B: 検証 43R / 的中32.6% / ROI37.0%
- venue=鳴門 / slit_shape=outer_pressure: 検証 27R / 的中22.2% / ROI37.1%
- venue=鳴門 / wave=3-6cm: 検証 28R / 的中28.6% / ROI37.2%
- venue=鳴門 / tide_phase=rising: 検証 45R / 的中28.9% / ROI37.3%
- venue=桐生 / grade=A: 検証 26R / 的中26.9% / ROI37.8%
- outer_fast=no / head_gap=<5pt: 検証 30R / 的中30.0% / ROI40.0%
- attack_style_prior=dominant_makurizashi: 検証 35R / 的中28.6% / ROI40.2%
- venue=桐生 / wind=2-3m: 検証 35R / 的中25.7% / ROI41.9%
- venue=丸亀 / grade=B: 検証 38R / 的中34.2% / ROI43.3%
- venue=桐生 / head_gap=20pt+: 検証 47R / 的中34.0% / ROI43.9%
- tide_phase=rising / slit_shape=strong_outer_attack_4: 検証 52R / 的中26.9% / ROI44.8%
- venue=若松 / wave=3-6cm: 検証 31R / 的中35.5% / ROI45.0%
- score=60-74 / head_gap=5-9pt: 検証 82R / 的中32.9% / ROI45.1%
- venue=福岡 / grade=C: 検証 43R / 的中37.2% / ROI46.2%
