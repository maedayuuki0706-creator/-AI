# 勝ちルール探索レポート

対象 3473R / 32日 / 的中率 43.4% / 回収率 74.4% / 収支 -1,052,400円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- head_gap=20pt+ / slit_shape=outer_attack_3: 検証 40R / 的中62.5% / ROI129.6%

## 見送り候補

- tide_level=low / head_gap=<5pt: 検証 32R / 的中18.8% / ROI29.9%
- tide_range=medium / wind=0-1m: 検証 63R / 的中34.9% / ROI41.8%
- venue=桐生: 検証 42R / 的中38.1% / ROI42.7%
- venue=戸田 / grade=C: 検証 29R / 的中24.1% / ROI49.5%
- tide_phase=falling / wind=0-1m: 検証 64R / 的中37.5% / ROI50.0%
- selected=yes / points=11-12: 検証 26R / 的中34.6% / ROI52.2%
- venue=福岡: 検証 60R / 的中43.3% / ROI56.7%
- venue=三国: 検証 43R / 的中37.2% / ROI57.2%
- venue=戸田: 検証 48R / 的中33.3% / ROI57.3%
- venue=丸亀 / wave=0-2cm: 検証 30R / 的中43.3% / ROI61.1%
- venue=多摩川: 検証 45R / 的中46.7% / ROI61.6%
- venue=浜名湖: 検証 45R / 的中40.0% / ROI62.4%
- attack_gap=10-14pt / head_gap=20pt+: 検証 70R / 的中47.1% / ROI63.5%
- head_top=<25% / head_gap=<5pt: 検証 62R / 的中22.6% / ROI64.0%
- venue=丸亀: 検証 42R / 的中40.5% / ROI64.9%
- attack_gap=5-9pt / head_gap=<5pt: 検証 31R / 的中25.8% / ROI65.4%
- head_gap=20pt+ / slit_shape=strong_outer_attack_6: 検証 35R / 的中51.4% / ROI66.7%
- score=60-74 / head_gap=<5pt: 検証 52R / 的中36.5% / ROI67.0%
- head_top=<25%: 検証 63R / 的中23.8% / ROI67.4%
- venue=常滑 / wind=2-3m: 検証 34R / 的中47.1% / ROI68.0%
