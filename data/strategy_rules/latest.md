# 勝ちルール探索レポート

対象 6663R / 63日 / 的中率 43.8% / 回収率 73.3% / 収支 -2,078,330円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=下関 / wind=2-3m: 検証 24R / 的中45.8% / ROI109.6%
- tide_phase=rising / slit_shape=outer_attack_3: 検証 28R / 的中57.1% / ROI102.1%

## 見送り候補

- venue=桐生 / wind=2-3m: 検証 24R / 的中16.7% / ROI21.2%
- venue=鳴門 / slit_shape=outer_pressure: 検証 27R / 的中14.8% / ROI21.5%
- tide_phase=rising / slit_shape=outer_attack_4: 検証 26R / 的中23.1% / ROI30.0%
- venue=福岡 / tide_level=mid: 検証 29R / 的中27.6% / ROI33.2%
- venue=鳴門 / grade=B: 検証 35R / 的中31.4% / ROI39.0%
- venue=福岡 / tide_phase=falling: 検証 46R / 的中32.6% / ROI39.5%
- attack_style_prior=dominant_makurizashi: 検証 32R / 的中25.0% / ROI39.5%
- venue=浜名湖: 検証 41R / 的中29.3% / ROI40.1%
- venue=福岡 / slit_shape=outer_pressure: 検証 35R / 的中40.0% / ROI40.2%
- venue=津 / grade=A: 検証 28R / 的中42.9% / ROI40.6%
- venue=常滑 / grade=B: 検証 39R / 的中23.1% / ROI41.1%
- outer_fast=no / head_gap=<5pt: 検証 25R / 的中24.0% / ROI41.6%
- venue=桐生 / wave=0-2cm: 検証 41R / 的中29.3% / ROI41.8%
- venue=福岡 / grade=C: 検証 32R / 的中31.2% / ROI41.8%
- venue=三国 / wave=0-2cm: 検証 31R / 的中38.7% / ROI41.9%
- venue=児島 / grade=B: 検証 31R / 的中25.8% / ROI43.2%
- venue=鳴門 / wave=3-6cm: 検証 41R / 的中31.7% / ROI44.6%
- venue=桐生 / grade=A: 検証 28R / 的中35.7% / ROI44.7%
- slit_shape=outer_attack_4: 検証 91R / 的中37.4% / ROI45.7%
- venue=鳴門 / tide_phase=rising: 検証 44R / 的中34.1% / ROI46.0%
