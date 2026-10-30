# 勝ちルール探索レポート

対象 5145R / 47日 / 的中率 43.8% / 回収率 73.6% / 収支 -1,592,320円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=びわこ / grade=B: 検証 31R / 的中41.9% / ROI117.9%
- venue=江戸川 / tide_phase=rising: 検証 31R / 的中54.8% / ROI105.9%

## 見送り候補

- venue=若松 / tide_phase=rising: 検証 30R / 的中30.0% / ROI27.0%
- venue=下関 / wind=0-1m: 検証 34R / 的中32.4% / ROI32.1%
- venue=丸亀 / tide_level=low: 検証 24R / 的中33.3% / ROI34.6%
- venue=戸田 / wave=0-2cm: 検証 37R / 的中27.0% / ROI35.4%
- venue=住之江 / head_gap=20pt+: 検証 25R / 的中32.0% / ROI36.1%
- venue=鳴門 / grade=B: 検証 30R / 的中36.7% / ROI37.2%
- tide_level=mid / head_gap=<5pt: 検証 26R / 的中23.1% / ROI39.0%
- venue=若松 / slit_shape=outer_pressure: 検証 28R / 的中42.9% / ROI41.0%
- venue=鳴門 / tide_phase=rising: 検証 30R / 的中36.7% / ROI41.3%
- st_spread=<5pt: 検証 49R / 的中38.8% / ROI42.7%
- venue=平和島 / head_gap=<5pt: 検証 26R / 的中30.8% / ROI43.4%
- venue=戸田: 検証 40R / 的中27.5% / ROI43.6%
- head_gap=20pt+ / slit_shape=outer_attack_5: 検証 45R / 的中53.3% / ROI48.6%
- venue=三国 / head_gap=20pt+: 検証 45R / 的中31.1% / ROI48.8%
- venue=桐生 / head_gap=20pt+: 検証 51R / 的中45.1% / ROI51.5%
- venue=鳴門: 検証 70R / 的中40.0% / ROI51.7%
- tide_phase=falling / slit_shape=outer_pressure: 検証 117R / 的中47.9% / ROI52.0%
- tide_phase=falling / wind=4m+: 検証 76R / 的中39.5% / ROI52.1%
- tide_phase=rising / slit_shape=strong_outer_attack_4: 検証 49R / 的中34.7% / ROI52.3%
- venue=平和島 / grade=C: 検証 38R / 的中31.6% / ROI52.6%
