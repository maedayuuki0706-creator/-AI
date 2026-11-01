# 勝ちルール探索レポート

対象 5365R / 49日 / 的中率 43.7% / 回収率 73.6% / 収支 -1,662,000円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=びわこ / grade=B: 検証 31R / 的中41.9% / ROI117.9%

## 見送り候補

- venue=鳴門 / grade=B: 検証 35R / 的中28.6% / ROI28.4%
- venue=若松 / tide_phase=rising: 検証 24R / 的中29.2% / ROI29.7%
- venue=丸亀 / tide_level=low: 検証 26R / 的中34.6% / ROI33.6%
- venue=住之江 / head_gap=20pt+: 検証 25R / 的中32.0% / ROI36.1%
- venue=若松 / grade=B: 検証 28R / 的中35.7% / ROI39.4%
- venue=丸亀 / grade=B: 検証 26R / 的中42.3% / ROI41.5%
- venue=鳴門 / tide_phase=rising: 検証 35R / 的中34.3% / ROI41.6%
- venue=戸田: 検証 37R / 的中32.4% / ROI47.4%
- venue=戸田 / wave=0-2cm: 検証 37R / 的中32.4% / ROI47.4%
- venue=戸田 / grade=C: 検証 25R / 的中36.0% / ROI48.6%
- head_gap=20pt+ / slit_shape=outer_attack_5: 検証 43R / 的中53.5% / ROI50.0%
- head_gap=<5pt / slit_shape=outer_pressure: 検証 85R / 的中28.2% / ROI50.2%
- venue=常滑: 検証 87R / 的中43.7% / ROI50.5%
- venue=鳴門: 検証 75R / 的中37.3% / ROI51.9%
- st_spread=<5pt: 検証 49R / 的中44.9% / ROI52.0%
- venue=平和島 / head_gap=<5pt: 検証 26R / 的中26.9% / ROI52.2%
- venue=鳴門 / slit_shape=outer_pressure: 検証 27R / 的中33.3% / ROI52.4%
- score=60-74 / head_gap=5-9pt: 検証 63R / 的中30.2% / ROI52.6%
- venue=丸亀 / head_gap=20pt+: 検証 30R / 的中43.3% / ROI52.8%
- venue=常滑 / wave=0-2cm: 検証 77R / 的中44.2% / ROI53.0%
