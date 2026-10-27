# 勝ちルール探索レポート

対象 4854R / 44日 / 的中率 43.6% / 回収率 72.5% / 収支 -1,568,990円

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
- tide_level=mid / head_gap=<5pt: 検証 28R / 的中21.4% / ROI34.6%
- venue=平和島 / head_gap=<5pt: 検証 32R / 的中28.1% / ROI36.8%
- venue=鳴門: 検証 71R / 的中33.8% / ROI38.0%
- venue=鳴門 / grade=B: 検証 27R / 的中37.0% / ROI39.6%
- st_spread=<5pt: 検証 45R / 的中37.8% / ROI40.4%
- venue=福岡 / wave=3-6cm: 検証 24R / 的中45.8% / ROI41.7%
- venue=丸亀 / tide_phase=falling: 検証 25R / 的中32.0% / ROI44.2%
- venue=平和島 / grade=C: 検証 46R / 的中28.3% / ROI44.6%
- head_top=<25% / head_gap=<5pt: 検証 96R / 的中21.9% / ROI46.1%
- score=60-74 / head_gap=5-9pt: 検証 69R / 的中30.4% / ROI46.7%
- venue=福岡 / grade=C: 検証 26R / 的中34.6% / ROI47.1%
- head_top=<25%: 検証 100R / 的中22.0% / ROI48.0%
- attack_gap=15pt+ / head_gap=<5pt: 検証 34R / 的中32.4% / ROI48.1%
- venue=戸田 / wave=0-2cm: 検証 46R / 的中32.6% / ROI48.5%
- tide_phase=rising / slit_shape=strong_outer_attack_4: 検証 50R / 的中38.0% / ROI51.2%
- venue=丸亀: 検証 35R / 的中34.3% / ROI51.4%
- venue=三国 / head_gap=20pt+: 検証 44R / 的中34.1% / ROI52.1%
- venue=平和島: 検証 73R / 的中34.2% / ROI52.4%
- venue=平和島 / wave=3-6cm: 検証 73R / 的中34.2% / ROI52.4%
