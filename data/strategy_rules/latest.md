# 勝ちルール探索レポート

対象 4610R / 42日 / 的中率 43.5% / 回収率 72.4% / 収支 -1,497,440円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=びわこ / wave=0-2cm: 検証 33R / 的中45.5% / ROI112.8%

## 見送り候補

- tide_level=mid / head_gap=<5pt: 検証 28R / 的中21.4% / ROI30.4%
- venue=平和島 / head_gap=<5pt: 検証 29R / 的中27.6% / ROI36.0%
- venue=鳴門: 検証 79R / 的中35.4% / ROI38.8%
- venue=鳴門 / grade=B: 検証 31R / 的中35.5% / ROI39.1%
- venue=三国 / head_gap=20pt+: 検証 33R / 的中33.3% / ROI39.7%
- head_top=<25% / head_gap=<5pt: 検証 87R / 的中20.7% / ROI40.1%
- st_spread=<5pt: 検証 37R / 的中37.8% / ROI40.4%
- head_top=<25%: 検証 89R / 的中21.3% / ROI43.3%
- attack_gap=15pt+ / head_gap=<5pt: 検証 30R / 的中36.7% / ROI44.5%
- venue=三国 / grade=B: 検証 25R / 的中36.0% / ROI45.3%
- tide_range=medium / wind=0-1m: 検証 101R / 的中37.6% / ROI48.4%
- venue=戸田 / wave=0-2cm: 検証 46R / 的中32.6% / ROI48.5%
- tide_phase=falling / wind=0-1m: 検証 114R / 的中40.4% / ROI49.1%
- venue=平和島 / grade=C: 検証 42R / 的中28.6% / ROI49.5%
- venue=丸亀: 検証 25R / 的中36.0% / ROI49.6%
- venue=桐生 / head_gap=20pt+: 検証 31R / 的中45.2% / ROI52.9%
- grade=C / head_gap=5-9pt: 検証 133R / 的中33.1% / ROI53.1%
- venue=戸田: 検証 50R / 的中32.0% / ROI53.1%
- venue=三国: 検証 67R / 的中34.3% / ROI53.5%
- tide_phase=rising / slit_shape=strong_outer_attack_4: 検証 51R / 的中39.2% / ROI54.3%
