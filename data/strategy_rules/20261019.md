# 勝ちルール探索レポート

対象 3950R / 36日 / 的中率 43.2% / 回収率 73.6% / 収支 -1,228,090円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

まだなし。サンプル不足または再現性不足。

## 見送り候補

- attack_gap=15pt+ / head_gap=<5pt: 検証 28R / 的中32.1% / ROI35.6%
- venue=平和島 / grade=C: 検証 25R / 的中24.0% / ROI37.6%
- tide_level=low / head_gap=<5pt: 検証 42R / 的中23.8% / ROI39.1%
- head_top=<25% / head_gap=<5pt: 検証 78R / 的中19.2% / ROI40.8%
- tide_range=medium / wind=0-1m: 検証 69R / 的中34.8% / ROI40.9%
- head_top=<25%: 検証 80R / 的中20.0% / ROI43.3%
- venue=平和島: 検証 35R / 的中28.6% / ROI44.7%
- venue=徳山 / wind=2-3m: 検証 33R / 的中48.5% / ROI48.3%
- selected=yes / points=11-12: 検証 24R / 的中33.3% / ROI48.4%
- venue=児島 / grade=B: 検証 30R / 的中30.0% / ROI49.0%
- venue=戸田 / wave=0-2cm: 検証 69R / 的中31.9% / ROI49.1%
- tide_phase=falling / wind=0-1m: 検証 80R / 的中33.8% / ROI51.8%
- venue=戸田: 検証 73R / 的中31.5% / ROI52.2%
- venue=福岡: 検証 45R / 的中40.0% / ROI56.3%
- venue=戸田 / grade=C: 検証 46R / 的中34.8% / ROI57.7%
- venue=戸田 / wind=0-1m: 検証 34R / 的中29.4% / ROI59.2%
- tide_range=small: 検証 172R / 的中40.7% / ROI60.4%
- attack_gap=10-14pt / head_gap=20pt+: 検証 81R / 的中43.2% / ROI60.6%
- venue=桐生: 検証 73R / 的中38.4% / ROI60.6%
- venue=丸亀 / wave=0-2cm: 検証 30R / 的中43.3% / ROI61.1%
