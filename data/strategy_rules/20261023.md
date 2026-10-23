# 勝ちルール探索レポート

対象 4355R / 40日 / 的中率 43.1% / 回収率 72.6% / 収支 -1,404,230円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

まだなし。サンプル不足または再現性不足。

## 見送り候補

- st_spread=<5pt: 検証 33R / 的中33.3% / ROI34.1%
- head_top=<25% / head_gap=<5pt: 検証 79R / 的中20.3% / ROI35.1%
- attack_gap=15pt+ / head_gap=<5pt: 検証 29R / 的中31.0% / ROI35.6%
- venue=三国 / head_gap=20pt+: 検証 24R / 的中33.3% / ROI38.6%
- head_top=<25%: 検証 81R / 的中21.0% / ROI38.8%
- venue=鳴門: 検証 62R / 的中30.6% / ROI38.9%
- tide_level=mid / head_gap=<5pt: 検証 30R / 的中23.3% / ROI42.2%
- venue=丸亀: 検証 34R / 的中32.4% / ROI42.9%
- tide_range=medium / wind=0-1m: 検証 82R / 的中32.9% / ROI43.2%
- venue=丸亀 / wave=0-2cm: 検証 26R / 的中34.6% / ROI43.7%
- venue=戸田 / wave=0-2cm: 検証 56R / 的中30.4% / ROI46.1%
- tide_phase=falling / wind=0-1m: 検証 91R / 的中35.2% / ROI47.6%
- venue=桐生 / head_gap=20pt+: 検証 33R / 的中42.4% / ROI48.4%
- score=<60 / head_gap=10-19pt: 検証 53R / 的中28.3% / ROI49.3%
- venue=戸田: 検証 60R / 的中30.0% / ROI50.1%
- venue=平和島 / grade=C: 検証 33R / 的中27.3% / ROI51.0%
- head_top=25-34% / head_gap=10-19pt: 検証 131R / 的中31.3% / ROI51.3%
- venue=児島 / grade=B: 検証 30R / 的中46.7% / ROI51.3%
- venue=戸田 / grade=C: 検証 38R / 的中31.6% / ROI51.7%
- attack_gap=15pt+ / head_gap=10-19pt: 検証 54R / 的中44.4% / ROI53.1%
