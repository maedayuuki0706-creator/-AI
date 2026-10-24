# 勝ちルール探索レポート

対象 4482R / 41日 / 的中率 43.3% / 回収率 72.3% / 収支 -1,460,650円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

まだなし。サンプル不足または再現性不足。

## 見送り候補

- head_top=<25% / head_gap=<5pt: 検証 88R / 的中18.2% / ROI31.5%
- head_top=<25%: 検証 90R / 的中18.9% / ROI34.9%
- attack_gap=15pt+ / head_gap=<5pt: 検証 30R / 的中33.3% / ROI36.4%
- venue=鳴門: 検証 71R / 的中32.4% / ROI38.0%
- venue=平和島 / head_gap=<5pt: 検証 26R / 的中26.9% / ROI38.1%
- venue=鳴門 / grade=B: 検証 28R / 的中35.7% / ROI38.3%
- venue=福岡 / wave=3-6cm: 検証 24R / 的中41.7% / ROI39.2%
- st_spread=<5pt: 検証 37R / 的中37.8% / ROI40.6%
- venue=丸亀: 検証 34R / 的中32.4% / ROI42.9%
- tide_level=mid / head_gap=<5pt: 検証 33R / 的中24.2% / ROI43.6%
- venue=丸亀 / wave=0-2cm: 検証 26R / 的中34.6% / ROI43.7%
- tide_range=medium / wind=0-1m: 検証 94R / 的中34.0% / ROI44.8%
- venue=三国 / head_gap=20pt+: 検証 27R / 的中37.0% / ROI44.9%
- score=<60 / head_gap=10-19pt: 検証 57R / 的中26.3% / ROI45.9%
- venue=戸田 / wave=0-2cm: 検証 56R / 的中30.4% / ROI46.1%
- venue=桐生 / head_gap=20pt+: 検証 33R / 的中42.4% / ROI48.4%
- venue=戸田: 検証 60R / 的中30.0% / ROI50.1%
- tide_phase=falling / wind=0-1m: 検証 104R / 的中38.5% / ROI51.3%
- venue=児島 / grade=B: 検証 30R / 的中46.7% / ROI51.3%
- venue=戸田 / grade=C: 検証 38R / 的中31.6% / ROI51.7%
