# 勝ちルール探索レポート

対象 5258R / 48日 / 的中率 43.7% / 回収率 73.4% / 収支 -1,636,440円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=びわこ / grade=B: 検証 31R / 的中41.9% / ROI117.9%
- venue=江戸川 / tide_phase=rising: 検証 30R / 的中46.7% / ROI102.1%

## 見送り候補

- venue=鳴門 / grade=B: 検証 30R / 的中26.7% / ROI25.0%
- venue=若松 / tide_phase=rising: 検証 26R / 的中30.8% / ROI29.0%
- venue=丸亀 / tide_level=low: 検証 26R / 的中34.6% / ROI33.6%
- venue=下関 / wind=0-1m: 検証 30R / 的中33.3% / ROI35.9%
- venue=住之江 / head_gap=20pt+: 検証 25R / 的中32.0% / ROI36.1%
- tide_level=mid / head_gap=<5pt: 検証 25R / 的中24.0% / ROI40.5%
- venue=丸亀 / grade=B: 検証 26R / 的中42.3% / ROI41.5%
- venue=平和島 / head_gap=<5pt: 検証 25R / 的中28.0% / ROI42.3%
- venue=鳴門 / tide_phase=rising: 検証 31R / 的中38.7% / ROI43.4%
- venue=若松 / slit_shape=outer_pressure: 検証 26R / 的中46.2% / ROI44.9%
- st_spread=<5pt: 検証 48R / 的中41.7% / ROI45.3%
- head_gap=20pt+ / slit_shape=outer_attack_5: 検証 44R / 的中50.0% / ROI47.2%
- venue=常滑 / grade=B: 検証 41R / 的中39.0% / ROI47.2%
- venue=戸田 / wave=0-2cm: 検証 40R / 的中30.0% / ROI47.3%
- venue=平和島 / grade=C: 検証 42R / 的中28.6% / ROI47.7%
- head_gap=<5pt / slit_shape=outer_pressure: 検証 90R / 的中25.6% / ROI48.1%
- venue=鳴門: 検証 69R / 的中37.7% / ROI49.8%
- tide_phase=falling / slit_shape=outer_pressure: 検証 120R / 的中46.7% / ROI50.1%
- venue=鳴門 / slit_shape=outer_pressure: 検証 25R / 的中32.0% / ROI50.7%
- venue=鳴門 / tide_phase=falling: 検証 32R / 的中34.4% / ROI51.4%
