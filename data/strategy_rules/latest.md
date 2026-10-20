# 勝ちルール探索レポート

対象 3983R / 37日 / 的中率 43.1% / 回収率 73.3% / 収支 -1,253,740円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

まだなし。サンプル不足または再現性不足。

## 見送り候補

- venue=平和島 / grade=C: 検証 25R / 的中24.0% / ROI37.6%
- attack_gap=15pt+ / head_gap=<5pt: 検証 30R / 的中33.3% / ROI39.1%
- tide_range=medium / wind=0-1m: 検証 71R / 的中33.8% / ROI39.7%
- head_top=<25% / head_gap=<5pt: 検証 79R / 的中19.0% / ROI40.3%
- tide_level=low / head_gap=<5pt: 検証 44R / 的中25.0% / ROI41.3%
- head_top=<25%: 検証 81R / 的中19.8% / ROI42.8%
- venue=平和島: 検証 35R / 的中28.6% / ROI44.7%
- tide_phase=falling / wind=0-1m: 検証 91R / 的中33.0% / ROI48.3%
- selected=yes / points=11-12: 検証 24R / 的中33.3% / ROI48.4%
- venue=児島 / grade=B: 検証 30R / 的中30.0% / ROI49.0%
- venue=戸田 / wave=0-2cm: 検証 69R / 的中31.9% / ROI49.1%
- venue=戸田: 検証 73R / 的中31.5% / ROI52.2%
- venue=徳山 / wind=2-3m: 検証 34R / 的中50.0% / ROI53.6%
- venue=福岡: 検証 45R / 的中40.0% / ROI56.3%
- attack_gap=10-14pt / head_gap=20pt+: 検証 86R / 的中40.7% / ROI57.3%
- tide_range=small: 検証 185R / 的中39.5% / ROI57.6%
- venue=戸田 / grade=C: 検証 46R / 的中34.8% / ROI57.7%
- venue=桐生: 検証 77R / 的中37.7% / ROI58.6%
- venue=戸田 / wind=0-1m: 検証 34R / 的中29.4% / ROI59.2%
- head_top=25-34% / head_gap=10-19pt: 検証 118R / 的中34.7% / ROI60.8%
