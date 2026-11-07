# 勝ちルール探索レポート

対象 5776R / 53日 / 的中率 43.6% / 回収率 73.3% / 収支 -1,801,080円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=芦屋 / wave=0-2cm: 検証 49R / 的中61.2% / ROI105.8%
- venue=びわこ / grade=B: 検証 39R / 的中43.6% / ROI101.2%

## 見送り候補

- venue=鳴門 / grade=B: 検証 41R / 的中26.8% / ROI28.0%
- venue=若松 / tide_phase=rising: 検証 24R / 的中29.2% / ROI29.7%
- venue=常滑 / grade=B: 検証 36R / 的中27.8% / ROI30.2%
- venue=丸亀 / tide_level=low: 検証 31R / 的中32.3% / ROI32.5%
- tide_phase=rising / slit_shape=outer_attack_4: 検証 30R / 的中26.7% / ROI34.6%
- venue=鳴門 / wave=3-6cm: 検証 26R / 的中34.6% / ROI35.3%
- venue=三国 / slit_shape=outer_pressure: 検証 26R / 的中34.6% / ROI36.4%
- venue=鳴門 / tide_phase=rising: 検証 43R / 的中30.2% / ROI37.2%
- venue=平和島 / wind=2-3m: 検証 38R / 的中23.7% / ROI38.6%
- venue=丸亀 / grade=B: 検証 38R / 的中34.2% / ROI43.3%
- venue=若松 / wave=3-6cm: 検証 28R / 的中35.7% / ROI44.4%
- venue=鳴門 / slit_shape=outer_pressure: 検証 32R / 的中28.1% / ROI45.0%
- venue=三国 / attack_lane=none: 検証 24R / 的中41.7% / ROI45.7%
- venue=常滑 / wind=4m+: 検証 35R / 的中34.3% / ROI45.8%
- tide_level=low / head_gap=10-19pt: 検証 64R / 的中40.6% / ROI46.6%
- venue=若松: 検証 43R / 的中34.9% / ROI47.0%
- venue=浜名湖 / head_gap=10-19pt: 検証 26R / 的中30.8% / ROI47.2%
- tide_phase=rising / slit_shape=strong_outer_attack_4: 検証 49R / 的中30.6% / ROI47.4%
- outer_fast=no / head_gap=10-19pt: 検証 55R / 的中30.9% / ROI47.8%
- venue=桐生 / head_gap=20pt+: 検証 45R / 的中42.2% / ROI48.2%
