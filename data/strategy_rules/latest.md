# 勝ちルール探索レポート

対象 5480R / 50日 / 的中率 43.8% / 回収率 73.5% / 収支 -1,698,310円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=びわこ / grade=B: 検証 31R / 的中41.9% / ROI117.9%
- venue=芦屋 / wave=0-2cm: 検証 44R / 的中61.4% / ROI109.9%

## 見送り候補

- venue=鳴門 / grade=B: 検証 35R / 的中28.6% / ROI28.4%
- venue=若松 / tide_phase=rising: 検証 24R / 的中29.2% / ROI29.7%
- venue=下関 / wind=0-1m: 検証 24R / 的中33.3% / ROI31.8%
- venue=丸亀 / tide_level=low: 検証 26R / 的中34.6% / ROI33.6%
- tide_phase=rising / slit_shape=outer_attack_4: 検証 25R / 的中28.0% / ROI34.2%
- venue=三国 / slit_shape=outer_pressure: 検証 24R / 的中33.3% / ROI35.2%
- venue=住之江 / head_gap=20pt+: 検証 25R / 的中32.0% / ROI36.1%
- venue=丸亀 / grade=B: 検証 29R / 的中37.9% / ROI37.4%
- venue=常滑 / grade=B: 検証 32R / 的中34.4% / ROI40.3%
- venue=平和島 / wind=2-3m: 検証 33R / 的中24.2% / ROI40.6%
- venue=常滑 / wind=4m+: 検証 25R / 的中36.0% / ROI40.7%
- venue=鳴門 / tide_phase=rising: 検証 35R / 的中34.3% / ROI41.6%
- venue=桐生 / wind=2-3m: 検証 36R / 的中30.6% / ROI43.6%
- venue=若松 / wave=3-6cm: 検証 28R / 的中35.7% / ROI44.4%
- score=60-74 / head_gap=5-9pt: 検証 59R / 的中28.8% / ROI45.2%
- venue=浜名湖 / head_gap=10-19pt: 検証 24R / 的中29.2% / ROI46.0%
- venue=若松: 検証 43R / 的中34.9% / ROI47.0%
- venue=福岡 / grade=C: 検証 29R / 的中41.4% / ROI49.2%
- venue=常滑: 検証 75R / 的中42.7% / ROI49.4%
- venue=戸田: 検証 35R / 的中37.1% / ROI50.0%
