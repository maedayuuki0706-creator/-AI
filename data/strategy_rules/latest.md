# 勝ちルール探索レポート

対象 3844R / 35日 / 的中率 43.2% / 回収率 73.9% / 収支 -1,185,530円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- head_gap=20pt+ / slit_shape=outer_attack_3: 検証 40R / 的中57.5% / ROI104.5%

## 見送り候補

- attack_gap=15pt+ / head_gap=<5pt: 検証 30R / 的中30.0% / ROI33.8%
- venue=平和島 / grade=C: 検証 25R / 的中24.0% / ROI37.6%
- tide_range=medium / wind=0-1m: 検証 65R / 的中33.8% / ROI40.9%
- tide_level=low / head_gap=<5pt: 検証 45R / 的中24.4% / ROI42.5%
- venue=平和島: 検証 35R / 的中28.6% / ROI44.7%
- selected=yes / points=11-12: 検証 29R / 的中31.0% / ROI47.7%
- venue=多摩川: 検証 26R / 的中42.3% / ROI49.1%
- tide_phase=falling / wind=0-1m: 検証 79R / 的中35.4% / ROI52.8%
- head_top=<25% / head_gap=<5pt: 検証 77R / 的中20.8% / ROI53.2%
- venue=戸田 / wave=0-2cm: 検証 59R / 的中32.2% / ROI53.2%
- head_top=<25%: 検証 79R / 的中21.5% / ROI55.4%
- venue=桐生: 検証 72R / 的中37.5% / ROI55.7%
- venue=福岡: 検証 45R / 的中40.0% / ROI56.3%
- venue=戸田: 検証 63R / 的中31.7% / ROI56.5%
- tide_range=small: 検証 154R / 的中40.3% / ROI60.1%
- attack_gap=10-14pt / head_gap=20pt+: 検証 83R / 的中42.2% / ROI61.0%
- venue=丸亀 / wave=0-2cm: 検証 30R / 的中43.3% / ROI61.1%
- venue=浜名湖: 検証 45R / 的中40.0% / ROI62.4%
- venue=戸田 / grade=C: 検証 38R / 的中34.2% / ROI63.1%
- venue=戸田 / wind=0-1m: 検証 32R / 的中31.2% / ROI63.2%
