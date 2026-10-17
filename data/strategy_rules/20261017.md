# 勝ちルール探索レポート

対象 3711R / 34日 / 的中率 43.0% / 回収率 73.2% / 収支 -1,174,580円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- head_gap=20pt+ / slit_shape=outer_attack_3: 検証 41R / 的中61.0% / ROI126.4%

## 見送り候補

- venue=桐生: 検証 61R / 的中32.8% / ROI36.6%
- tide_range=medium / wind=0-1m: 検証 69R / 的中33.3% / ROI38.5%
- venue=平和島: 検証 29R / 的中27.6% / ROI39.5%
- tide_level=low / head_gap=<5pt: 検証 45R / 的中26.7% / ROI43.2%
- venue=三国: 検証 57R / 的中33.3% / ROI46.6%
- selected=yes / points=11-12: 検証 29R / 的中34.5% / ROI49.6%
- head_top=<25% / head_gap=<5pt: 検証 79R / 的中21.5% / ROI51.8%
- tide_phase=falling / wind=0-1m: 検証 81R / 的中37.0% / ROI52.8%
- venue=戸田 / wave=0-2cm: 検証 55R / 的中32.7% / ROI53.2%
- venue=福岡: 検証 53R / 的中39.6% / ROI54.4%
- head_top=<25%: 検証 80R / 的中22.5% / ROI54.6%
- venue=戸田: 検証 59R / 的中32.2% / ROI56.8%
- attack_gap=10-14pt / head_gap=20pt+: 検証 87R / 的中44.8% / ROI58.0%
- tide_range=small: 検証 127R / 的中38.6% / ROI60.1%
- outer_fast=no / head_gap=20pt+: 検証 76R / 的中44.7% / ROI61.0%
- venue=丸亀 / wave=0-2cm: 検証 30R / 的中43.3% / ROI61.1%
- venue=浜名湖: 検証 45R / 的中40.0% / ROI62.4%
- head_gap=20pt+ / slit_shape=strong_outer_attack_6: 検証 39R / 的中51.3% / ROI62.4%
- venue=多摩川: 検証 37R / 的中43.2% / ROI63.5%
- venue=戸田 / grade=C: 検証 34R / 的中32.4% / ROI63.8%
