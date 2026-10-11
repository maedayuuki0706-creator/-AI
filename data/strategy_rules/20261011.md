# 勝ちルール探索レポート

対象 3146R / 29日 / 的中率 43.1% / 回収率 74.4% / 収支 -957,360円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- slit_shape=outer_attack_3: 検証 45R / 的中48.9% / ROI101.3%

## 見送り候補

- venue=浜名湖: 検証 25R / 的中32.0% / ROI37.0%
- venue=戸田 / grade=C: 検証 24R / 的中20.8% / ROI40.5%
- venue=桐生: 検証 42R / 的中38.1% / ROI42.7%
- venue=戸田: 検証 39R / 的中28.2% / ROI47.2%
- tide_range=medium / wind=0-1m: 検証 31R / 的中45.2% / ROI52.9%
- venue=三国: 検証 34R / 的中32.4% / ROI53.8%
- attack_gap=10-14pt / head_gap=20pt+: 検証 53R / 的中49.1% / ROI58.4%
- venue=福岡: 検証 37R / 的中48.6% / ROI58.7%
- head_gap=20pt+ / slit_shape=strong_outer_attack_4: 検証 44R / 的中45.5% / ROI59.6%
- points=11-12 / head_gap=10-19pt: 検証 144R / 的中34.7% / ROI59.9%
- tide_phase=falling / wind=0-1m: 検証 43R / 的中46.5% / ROI61.5%
- venue=多摩川: 検証 48R / 的中45.8% / ROI62.1%
- st_spread=10-14pt: 検証 148R / 的中45.3% / ROI62.8%
- tide_applicable=no: 検証 411R / 的中42.1% / ROI63.9%
- score=<60 / head_gap=10-19pt: 検証 27R / 的中33.3% / ROI66.2%
- venue=常滑 / wind=2-3m: 検証 34R / 的中47.1% / ROI68.0%
- venue=若松: 検証 44R / 的中43.2% / ROI68.7%
- venue=常滑 / wave=0-2cm: 検証 43R / 的中48.8% / ROI69.3%
- tide_level=mid: 検証 117R / 的中39.3% / ROI73.2%
- head_top=25-34%: 検証 223R / 的中32.7% / ROI73.9%
