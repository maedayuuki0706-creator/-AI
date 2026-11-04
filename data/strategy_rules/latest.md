# 勝ちルール探索レポート

対象 5593R / 51日 / 的中率 43.7% / 回収率 73.5% / 収支 -1,732,990円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=びわこ / grade=B: 検証 31R / 的中41.9% / ROI117.9%
- venue=芦屋 / wave=0-2cm: 検証 49R / 的中61.2% / ROI105.8%

## 見送り候補

- venue=鳴門 / grade=B: 検証 35R / 的中28.6% / ROI28.4%
- venue=若松 / tide_phase=rising: 検証 24R / 的中29.2% / ROI29.7%
- venue=三国 / slit_shape=outer_pressure: 検証 26R / 的中30.8% / ROI32.9%
- venue=下関 / wind=0-1m: 検証 26R / 的中34.6% / ROI33.5%
- venue=丸亀 / tide_level=low: 検証 26R / 的中34.6% / ROI33.6%
- tide_phase=rising / slit_shape=outer_attack_4: 検証 30R / 的中26.7% / ROI34.4%
- venue=住之江 / head_gap=20pt+: 検証 25R / 的中32.0% / ROI36.1%
- venue=常滑 / grade=B: 検証 35R / 的中31.4% / ROI36.9%
- venue=平和島 / wind=2-3m: 検証 38R / 的中23.7% / ROI38.6%
- venue=常滑 / wind=4m+: 検証 25R / 的中36.0% / ROI40.7%
- venue=鳴門 / tide_phase=rising: 検証 35R / 的中34.3% / ROI41.6%
- venue=桐生 / wind=2-3m: 検証 39R / 的中30.8% / ROI43.7%
- venue=若松 / wave=3-6cm: 検証 28R / 的中35.7% / ROI44.4%
- venue=丸亀 / grade=B: 検証 33R / 的中36.4% / ROI46.4%
- score=60-74 / head_gap=5-9pt: 検証 62R / 的中29.0% / ROI46.6%
- venue=若松: 検証 43R / 的中34.9% / ROI47.0%
- venue=浜名湖 / head_gap=10-19pt: 検証 26R / 的中30.8% / ROI47.2%
- tide_phase=rising / slit_shape=strong_outer_attack_4: 検証 49R / 的中32.7% / ROI48.4%
- venue=平和島 / grade=C: 検証 47R / 的中23.4% / ROI48.9%
- venue=浜名湖 / grade=B: 検証 44R / 的中31.8% / ROI49.7%
