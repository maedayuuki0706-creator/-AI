# 勝ちルール探索レポート

対象 4220R / 39日 / 的中率 43.0% / 回収率 72.6% / 収支 -1,362,920円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=江戸川 / tide_phase=rising: 検証 27R / 的中55.6% / ROI151.0%

## 見送り候補

- head_top=<25% / head_gap=<5pt: 検証 78R / 的中17.9% / ROI32.6%
- attack_gap=15pt+ / head_gap=<5pt: 検証 31R / 的中29.0% / ROI33.2%
- venue=平和島 / grade=C: 検証 30R / 的中23.3% / ROI35.8%
- tide_range=medium / wind=0-1m: 検証 63R / 的中31.7% / ROI36.0%
- venue=三国 / head_gap=20pt+: 検証 24R / 的中33.3% / ROI38.6%
- head_top=<25%: 検証 81R / 的中19.8% / ROI39.4%
- venue=鳴門: 検証 53R / 的中34.0% / ROI39.6%
- tide_level=low / head_gap=<5pt: 検証 43R / 的中25.6% / ROI40.3%
- venue=平和島: 検証 44R / 的中27.3% / ROI41.9%
- tide_level=mid / head_gap=<5pt: 検証 28R / 的中21.4% / ROI42.5%
- tide_phase=falling / wind=0-1m: 検証 84R / 的中32.1% / ROI45.1%
- venue=戸田 / wave=0-2cm: 検証 62R / 的中30.6% / ROI46.4%
- venue=戸田: 検証 66R / 的中30.3% / ROI50.0%
- venue=戸田 / grade=C: 検証 42R / 的中33.3% / ROI53.4%
- venue=戸田 / wind=0-1m: 検証 29R / 的中27.6% / ROI54.1%
- venue=桐生: 検証 73R / 的中37.0% / ROI54.7%
- attack_gap=10-14pt / head_gap=20pt+: 検証 94R / 的中40.4% / ROI55.2%
- venue=児島 / grade=B: 検証 34R / 的中47.1% / ROI55.5%
- venue=戸田 / head_gap=<5pt: 検証 24R / 的中33.3% / ROI55.6%
- venue=浜名湖: 検証 63R / 的中36.5% / ROI55.8%
