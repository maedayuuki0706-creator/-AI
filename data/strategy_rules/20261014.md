# 勝ちルール探索レポート

対象 3354R / 31日 / 的中率 43.3% / 回収率 74.5% / 収支 -1,011,060円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

まだなし。サンプル不足または再現性不足。

## 見送り候補

- tide_level=low / head_gap=<5pt: 検証 28R / 的中21.4% / ROI34.1%
- venue=戸田 / grade=C: 検証 24R / 的中20.8% / ROI40.5%
- tide_range=medium / wind=0-1m: 検証 58R / 的中36.2% / ROI41.8%
- venue=桐生: 検証 42R / 的中38.1% / ROI42.7%
- selected=yes / points=11-12: 検証 26R / 的中34.6% / ROI46.5%
- venue=戸田: 検証 39R / 的中28.2% / ROI47.2%
- head_gap=20pt+ / slit_shape=strong_outer_attack_6: 検証 28R / 的中46.4% / ROI47.7%
- tide_phase=falling / wind=0-1m: 検証 50R / 的中42.0% / ROI52.8%
- venue=三国: 検証 34R / 的中32.4% / ROI53.8%
- venue=福岡: 検証 53R / 的中47.2% / ROI54.5%
- venue=浜名湖: 検証 40R / 的中40.0% / ROI54.6%
- venue=多摩川: 検証 48R / 的中45.8% / ROI62.1%
- points=11-12 / head_gap=10-19pt: 検証 175R / 的中37.7% / ROI66.9%
- attack_gap=10-14pt / head_gap=20pt+: 検証 64R / 的中50.0% / ROI67.6%
- venue=常滑 / wind=2-3m: 検証 34R / 的中47.1% / ROI68.0%
- venue=常滑 / wave=0-2cm: 検証 43R / 的中48.8% / ROI69.3%
- attack_gap=5-9pt / head_gap=<5pt: 検証 28R / 的中28.6% / ROI69.6%
- st_spread=10-14pt: 検証 178R / 的中48.3% / ROI69.9%
- outer_fast=no: 検証 122R / 的中42.6% / ROI70.0%
- tide_applicable=no: 検証 466R / 的中43.1% / ROI70.3%
