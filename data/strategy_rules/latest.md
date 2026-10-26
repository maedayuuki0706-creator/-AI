# 勝ちルール探索レポート

対象 4718R / 43日 / 的中率 43.7% / 回収率 72.7% / 収支 -1,514,630円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=びわこ / wave=0-2cm: 検証 31R / 的中48.4% / ROI123.5%
- venue=びわこ / grade=B: 検証 38R / 的中42.1% / ROI104.3%

## 見送り候補

- venue=下関 / wind=0-1m: 検証 34R / 的中32.4% / ROI32.1%
- tide_level=mid / head_gap=<5pt: 検証 26R / 的中19.2% / ROI32.5%
- venue=鳴門: 検証 71R / 的中33.8% / ROI38.0%
- venue=平和島 / head_gap=<5pt: 検証 31R / 的中29.0% / ROI38.0%
- st_spread=<5pt: 検証 39R / 的中38.5% / ROI38.9%
- venue=鳴門 / grade=B: 検証 27R / 的中37.0% / ROI39.6%
- head_top=<25% / head_gap=<5pt: 検証 86R / 的中20.9% / ROI40.6%
- attack_gap=15pt+ / head_gap=<5pt: 検証 31R / 的中32.3% / ROI41.9%
- venue=三国 / head_gap=20pt+: 検証 37R / 的中35.1% / ROI43.1%
- head_top=<25%: 検証 89R / 的中21.3% / ROI43.3%
- venue=平和島 / grade=C: 検証 44R / 的中29.5% / ROI46.6%
- venue=戸田 / wave=0-2cm: 検証 46R / 的中32.6% / ROI48.5%
- venue=三国 / grade=B: 検証 28R / 的中35.7% / ROI48.9%
- score=60-74 / head_gap=5-9pt: 検証 65R / 的中32.3% / ROI49.6%
- venue=福岡 / grade=C: 検証 24R / 的中37.5% / ROI50.9%
- tide_phase=falling / wind=0-1m: 検証 112R / 的中41.1% / ROI52.5%
- venue=戸田: 検証 50R / 的中32.0% / ROI53.1%
- tide_phase=rising / wind=0-1m: 検証 111R / 的中41.4% / ROI54.0%
- tide_range=medium / wind=0-1m: 検証 82R / 的中41.5% / ROI54.0%
- venue=平和島: 検証 69R / 的中34.8% / ROI54.2%
