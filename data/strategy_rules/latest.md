# 勝ちルール探索レポート

対象 4091R / 38日 / 的中率 42.9% / 回収率 73.0% / 収支 -1,299,620円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=江戸川 / tide_phase=rising: 検証 33R / 的中57.6% / ROI141.2%

## 見送り候補

- attack_gap=15pt+ / head_gap=<5pt: 検証 31R / 的中25.8% / ROI30.0%
- head_top=<25% / head_gap=<5pt: 検証 77R / 的中16.9% / ROI35.2%
- venue=平和島 / grade=C: 検証 25R / 的中24.0% / ROI37.6%
- head_top=<25%: 検証 80R / 的中18.8% / ROI41.9%
- tide_range=medium / wind=0-1m: 検証 69R / 的中36.2% / ROI43.3%
- venue=平和島: 検証 35R / 的中28.6% / ROI44.7%
- venue=鳴門: 検証 56R / 的中39.3% / ROI46.3%
- tide_level=low / head_gap=<5pt: 検証 47R / 的中27.7% / ROI46.6%
- venue=戸田 / wave=0-2cm: 検証 69R / 的中31.9% / ROI49.1%
- venue=徳山 / wind=2-3m: 検証 39R / 的中48.7% / ROI49.8%
- tide_phase=falling / wind=0-1m: 検証 90R / 的中34.4% / ROI50.2%
- venue=桐生: 検証 82R / 的中36.6% / ROI52.2%
- venue=戸田: 検証 73R / 的中31.5% / ROI52.2%
- attack_gap=10-14pt / head_gap=20pt+: 検証 91R / 的中38.5% / ROI52.8%
- venue=桐生 / wave=0-2cm: 検証 77R / 的中36.4% / ROI53.0%
- venue=三国 / head_gap=20pt+: 検証 30R / 的中40.0% / ROI55.4%
- venue=福岡: 検証 45R / 的中40.0% / ROI56.3%
- tide_range=small: 検証 201R / 的中39.3% / ROI57.3%
- venue=戸田 / grade=C: 検証 46R / 的中34.8% / ROI57.7%
- head_gap=20pt+ / slit_shape=outer_attack_5: 検証 44R / 的中43.2% / ROI58.3%
