# 勝ちルール探索レポート

対象 3240R / 30日 / 的中率 43.2% / 回収率 74.8% / 収支 -970,500円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- outer_fast=yes / head_gap=5-9pt: 検証 75R / 的中38.7% / ROI106.5%

## 見送り候補

- tide_level=low / head_gap=<5pt: 検証 24R / 的中25.0% / ROI39.7%
- venue=戸田 / grade=C: 検証 24R / 的中20.8% / ROI40.5%
- venue=桐生: 検証 42R / 的中38.1% / ROI42.7%
- tide_range=medium / wind=0-1m: 検証 55R / 的中36.4% / ROI43.2%
- venue=戸田: 検証 39R / 的中28.2% / ROI47.2%
- selected=yes / points=11-12: 検証 25R / 的中36.0% / ROI48.3%
- venue=浜名湖: 検証 35R / 的中40.0% / ROI50.5%
- venue=三国: 検証 34R / 的中32.4% / ROI53.8%
- head_gap=20pt+ / slit_shape=strong_outer_attack_6: 検証 25R / 的中52.0% / ROI54.0%
- tide_phase=falling / wind=0-1m: 検証 49R / 的中42.9% / ROI54.2%
- venue=福岡: 検証 45R / 的中46.7% / ROI57.0%
- attack_gap=10-14pt / head_gap=20pt+: 検証 56R / 的中51.8% / ROI61.2%
- venue=多摩川: 検証 48R / 的中45.8% / ROI62.1%
- points=11-12 / head_gap=10-19pt: 検証 159R / 的中35.2% / ROI62.5%
- head_gap=20pt+ / slit_shape=strong_outer_attack_4: 検証 46R / 的中47.8% / ROI64.2%
- score=<60 / head_gap=10-19pt: 検証 28R / 的中32.1% / ROI64.2%
- st_spread=10-14pt: 検証 156R / 的中47.4% / ROI67.1%
- tide_applicable=no: 検証 425R / 的中43.1% / ROI67.7%
- venue=常滑 / wind=2-3m: 検証 34R / 的中47.1% / ROI68.0%
- venue=常滑 / wave=0-2cm: 検証 43R / 的中48.8% / ROI69.3%
