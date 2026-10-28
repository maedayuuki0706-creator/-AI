# 勝ちルール探索レポート

対象 4946R / 45日 / 的中率 43.6% / 回収率 72.7% / 収支 -1,586,770円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

- venue=びわこ / grade=B: 検証 34R / 的中44.1% / ROI113.2%
- attack_gap=5-9pt / head_gap=5-9pt: 検証 41R / 的中39.0% / ROI103.5%

## 見送り候補

- venue=若松 / tide_phase=rising: 検証 36R / 的中36.1% / ROI30.1%
- venue=下関 / wind=0-1m: 検証 34R / 的中32.4% / ROI32.1%
- venue=丸亀 / tide_level=low: 検証 24R / 的中33.3% / ROI34.2%
- tide_level=mid / head_gap=<5pt: 検証 26R / 的中19.2% / ROI35.4%
- venue=平和島 / head_gap=<5pt: 検証 30R / 的中26.7% / ROI37.7%
- venue=鳴門 / tide_phase=falling: 検証 29R / 的中37.9% / ROI38.0%
- venue=若松 / slit_shape=outer_pressure: 検証 30R / 的中40.0% / ROI38.2%
- venue=鳴門 / tide_phase=rising: 検証 28R / 的中35.7% / ROI40.4%
- venue=鳴門: 検証 63R / 的中38.1% / ROI42.7%
- venue=鳴門 / grade=B: 検証 24R / 的中41.7% / ROI44.5%
- st_spread=<5pt: 検証 48R / 的中39.6% / ROI44.8%
- tide_phase=rising / slit_shape=strong_outer_attack_4: 検証 47R / 的中31.9% / ROI45.7%
- venue=平和島 / grade=C: 検証 43R / 的中27.9% / ROI46.5%
- score=60-74 / head_gap=5-9pt: 検証 64R / 的中31.2% / ROI47.9%
- venue=戸田 / wave=0-2cm: 検証 46R / 的中32.6% / ROI48.5%
- venue=三国 / head_gap=20pt+: 検証 49R / 的中32.7% / ROI48.9%
- head_gap=<5pt / slit_shape=outer_pressure: 検証 87R / 的中28.7% / ROI50.2%
- venue=福岡 / grade=C: 検証 24R / 的中37.5% / ROI50.9%
- attack_gap=15pt+ / head_gap=<5pt: 検証 32R / 的中34.4% / ROI51.0%
- tide_phase=falling / slit_shape=outer_pressure: 検証 114R / 的中47.4% / ROI52.3%
