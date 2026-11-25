# 勝ちルール探索レポート

対象 6662R / 62日 / 的中率 43.8% / 回収率 73.2% / 収支 -2,085,690円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=下関 / wind=2-3m: 検証 24R / 的中45.8% / ROI109.6%

## 見送り候補

- venue=桐生 / wind=2-3m: 検証 27R / 的中14.8% / ROI18.4%
- venue=鳴門 / slit_shape=outer_pressure: 検証 27R / 的中14.8% / ROI21.5%
- venue=丸亀 / tide_level=low: 検証 26R / 的中34.6% / ROI23.7%
- tide_phase=rising / slit_shape=outer_attack_4: 検証 28R / 的中25.0% / ROI29.4%
- venue=福岡 / tide_level=mid: 検証 32R / 的中28.1% / ROI33.0%
- head_gap=<5pt / slit_shape=flat_or_inner: 検証 25R / 的中28.0% / ROI38.1%
- attack_style_prior=dominant_makurizashi: 検証 34R / 的中26.5% / ROI38.6%
- venue=福岡 / tide_phase=falling: 検証 54R / 的中33.3% / ROI38.7%
- venue=鳴門 / grade=B: 検証 35R / 的中31.4% / ROI39.0%
- venue=福岡 / grade=C: 検証 34R / 的中29.4% / ROI39.4%
- venue=浜名湖: 検証 41R / 的中29.3% / ROI40.1%
- venue=福岡 / slit_shape=outer_pressure: 検証 38R / 的中39.5% / ROI40.5%
- venue=桐生 / grade=A: 検証 31R / 的中35.5% / ROI41.9%
- venue=津 / grade=A: 検証 32R / 的中46.9% / ROI42.1%
- outer_fast=no / head_gap=<5pt: 検証 29R / 的中27.6% / ROI43.9%
- venue=常滑 / grade=B: 検証 44R / 的中27.3% / ROI44.3%
- venue=鳴門 / wave=3-6cm: 検証 41R / 的中31.7% / ROI44.6%
- venue=平和島 / grade=C: 検証 53R / 的中22.6% / ROI44.7%
- score=60-74 / head_gap=5-9pt: 検証 79R / 的中34.2% / ROI44.9%
- venue=丸亀 / grade=B: 検証 36R / 的中36.1% / ROI45.9%
