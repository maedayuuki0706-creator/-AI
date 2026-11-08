# 勝ちルール探索レポート

対象 5872R / 54日 / 的中率 43.6% / 回収率 73.2% / 収支 -1,837,800円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=芦屋 / wave=0-2cm: 検証 54R / 的中63.0% / ROI102.5%

## 見送り候補

- venue=若松 / tide_phase=rising: 検証 24R / 的中29.2% / ROI29.7%
- venue=丸亀 / tide_level=low: 検証 31R / 的中32.3% / ROI32.5%
- tide_phase=rising / slit_shape=outer_attack_4: 検証 31R / 的中25.8% / ROI33.8%
- venue=常滑 / grade=B: 検証 39R / 的中30.8% / ROI34.4%
- venue=鳴門 / grade=B: 検証 45R / 的中31.1% / ROI34.8%
- venue=三国 / slit_shape=outer_pressure: 検証 26R / 的中34.6% / ROI36.4%
- venue=平和島 / wind=2-3m: 検証 38R / 的中23.7% / ROI38.6%
- venue=鳴門 / tide_phase=rising: 検証 48R / 的中33.3% / ROI41.9%
- venue=桐生 / wind=2-3m: 検証 37R / 的中27.0% / ROI42.6%
- venue=丸亀 / grade=B: 検証 38R / 的中34.2% / ROI43.3%
- venue=若松 / wave=3-6cm: 検証 28R / 的中35.7% / ROI44.4%
- venue=鳴門 / wave=3-6cm: 検証 28R / 的中39.3% / ROI44.5%
- venue=桐生 / head_gap=20pt+: 検証 54R / 的中37.0% / ROI44.7%
- venue=鳴門 / slit_shape=outer_pressure: 検証 34R / 的中29.4% / ROI45.0%
- venue=三国 / attack_lane=none: 検証 24R / 的中41.7% / ROI45.7%
- venue=常滑 / wind=4m+: 検証 35R / 的中34.3% / ROI45.8%
- tide_level=low / head_gap=10-19pt: 検証 64R / 的中40.6% / ROI46.6%
- venue=若松: 検証 43R / 的中34.9% / ROI47.0%
- venue=浜名湖 / head_gap=10-19pt: 検証 26R / 的中30.8% / ROI47.2%
- score=60-74 / head_gap=5-9pt: 検証 69R / 的中31.9% / ROI47.8%
