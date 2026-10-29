# 勝ちルール探索レポート

対象 5037R / 46日 / 的中率 43.6% / 回収率 72.8% / 収支 -1,604,410円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=びわこ / grade=B: 検証 31R / 的中41.9% / ROI117.9%
- attack_gap=5-9pt / head_gap=5-9pt: 検証 39R / 的中38.5% / ROI102.2%

## 見送り候補

- venue=若松 / tide_phase=rising: 検証 30R / 的中30.0% / ROI27.0%
- venue=下関 / wind=0-1m: 検証 34R / 的中32.4% / ROI32.1%
- venue=戸田 / wave=0-2cm: 検証 37R / 的中27.0% / ROI35.4%
- venue=鳴門 / grade=B: 検証 27R / 的中33.3% / ROI35.6%
- venue=住之江 / head_gap=20pt+: 検証 25R / 的中32.0% / ROI36.1%
- st_spread=<5pt: 検証 44R / 的中36.4% / ROI38.6%
- venue=鳴門 / tide_phase=rising: 検証 28R / 的中35.7% / ROI40.4%
- venue=若松 / slit_shape=outer_pressure: 検証 28R / 的中42.9% / ROI41.0%
- tide_level=mid / head_gap=<5pt: 検証 24R / 的中25.0% / ROI42.4%
- venue=平和島 / head_gap=<5pt: 検証 26R / 的中30.8% / ROI43.4%
- venue=戸田: 検証 40R / 的中27.5% / ROI43.6%
- head_gap=20pt+ / slit_shape=outer_attack_5: 検証 42R / 的中52.4% / ROI48.0%
- venue=三国 / head_gap=20pt+: 検証 45R / 的中31.1% / ROI48.8%
- head_gap=<5pt / slit_shape=outer_pressure: 検証 88R / 的中28.4% / ROI50.1%
- tide_phase=rising / slit_shape=strong_outer_attack_4: 検証 47R / 的中34.0% / ROI51.2%
- outer_fast=no: 検証 213R / 的中41.3% / ROI51.7%
- tide_phase=falling / wind=4m+: 検証 73R / 的中38.4% / ROI52.2%
- venue=平和島 / grade=C: 検証 38R / 的中31.6% / ROI52.6%
- slit_shape=flat_or_inner: 検証 170R / 的中41.2% / ROI52.7%
- venue=鳴門: 検証 62R / 的中40.3% / ROI52.7%
