# 勝ちルール探索レポート

対象 5681R / 52日 / 的中率 43.6% / 回収率 73.3% / 収支 -1,777,760円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=江戸川 / tide_phase=rising: 検証 29R / 的中44.8% / ROI106.0%
- venue=芦屋 / wave=0-2cm: 検証 49R / 的中61.2% / ROI105.8%
- venue=びわこ / grade=B: 検証 37R / 的中43.2% / ROI104.3%

## 見送り候補

- venue=住之江 / head_gap=20pt+: 検証 26R / 的中23.1% / ROI25.7%
- venue=鳴門 / grade=B: 検証 39R / 的中28.2% / ROI29.2%
- venue=若松 / tide_phase=rising: 検証 24R / 的中29.2% / ROI29.7%
- venue=丸亀 / tide_level=low: 検証 31R / 的中32.3% / ROI32.5%
- venue=常滑 / grade=B: 検証 32R / 的中31.2% / ROI34.2%
- venue=三国 / slit_shape=outer_pressure: 検証 25R / 的中32.0% / ROI35.4%
- tide_phase=rising / slit_shape=outer_attack_4: 検証 29R / 的中27.6% / ROI35.9%
- venue=平和島 / wind=2-3m: 検証 38R / 的中23.7% / ROI38.6%
- venue=鳴門 / tide_phase=rising: 検証 40R / 的中32.5% / ROI39.8%
- venue=常滑 / wind=4m+: 検証 25R / 的中36.0% / ROI40.7%
- venue=丸亀 / grade=B: 検証 38R / 的中34.2% / ROI43.3%
- venue=若松 / wave=3-6cm: 検証 28R / 的中35.7% / ROI44.4%
- outer_fast=no / head_gap=10-19pt: 検証 52R / 的中30.8% / ROI46.7%
- venue=若松: 検証 43R / 的中34.9% / ROI47.0%
- venue=浜名湖 / head_gap=10-19pt: 検証 26R / 的中30.8% / ROI47.2%
- score=60-74 / head_gap=5-9pt: 検証 63R / 的中31.7% / ROI47.6%
- venue=桐生 / head_gap=20pt+: 検証 44R / 的中43.2% / ROI48.5%
- venue=桐生 / wind=2-3m: 検証 31R / 的中32.3% / ROI48.7%
- venue=平和島 / grade=C: 検証 47R / 的中23.4% / ROI48.9%
- venue=鳴門 / slit_shape=outer_pressure: 検証 29R / 的中31.0% / ROI49.1%
