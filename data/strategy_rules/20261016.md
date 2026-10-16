# 勝ちルール探索レポート

対象 3586R / 33日 / 的中率 43.3% / 回収率 74.0% / 収支 -1,101,740円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- head_gap=20pt+ / slit_shape=outer_attack_3: 検証 39R / 的中59.0% / ROI129.2%

## 見送り候補

- tide_range=medium / wind=0-1m: 検証 69R / 的中33.3% / ROI38.5%
- tide_level=low / head_gap=<5pt: 検証 39R / 的中23.1% / ROI39.0%
- venue=桐生: 検証 52R / 的中34.6% / ROI40.5%
- selected=yes / points=11-12: 検証 26R / 的中34.6% / ROI52.2%
- venue=三国: 検証 50R / 的中36.0% / ROI53.0%
- venue=福岡: 検証 53R / 的中39.6% / ROI54.4%
- venue=戸田: 検証 47R / 的中34.0% / ROI54.8%
- tide_phase=falling / wind=0-1m: 検証 71R / 的中36.6% / ROI55.5%
- venue=戸田 / wave=0-2cm: 検証 46R / 的中34.8% / ROI56.3%
- head_top=<25% / head_gap=<5pt: 検証 68R / 的中22.1% / ROI56.5%
- venue=戸田 / grade=C: 検証 28R / 的中32.1% / ROI56.9%
- head_top=<25%: 検証 69R / 的中23.2% / ROI59.7%
- attack_gap=10-14pt / head_gap=20pt+: 検証 77R / 的中45.5% / ROI61.0%
- venue=丸亀 / wave=0-2cm: 検証 30R / 的中43.3% / ROI61.1%
- venue=浜名湖: 検証 45R / 的中40.0% / ROI62.4%
- score=60-74 / head_gap=<5pt: 検証 53R / 的中34.0% / ROI62.7%
- tide_range=small: 検証 93R / 的中39.8% / ROI62.8%
- venue=多摩川: 検証 37R / 的中43.2% / ROI63.5%
- outer_fast=no / head_gap=20pt+: 検証 71R / 的中46.5% / ROI63.7%
- venue=戸田 / wind=0-1m: 検証 30R / 的中33.3% / ROI64.0%
