# 勝ちルール探索レポート

対象 872R / 6日 / 的中率 39.1% / 回収率 65.7% / 収支 -372,700円

## 運用ルール

- 1日だけの好成績は採用しない
- 古い70%で発見し、新しい30%で再現した条件だけ候補にする
- 最低サンプル: 学習40R / 検証24R / 検証2日
- マーチン・負け追いは勝ちルールとして扱わない

## 検証済みプラス候補

まだなし。サンプル不足または再現性不足。

## 見送り候補

- score=60-74: 検証 193R / 的中34.7% / ROI46.9%
- head_gap=10-19pt: 検証 43R / 的中44.2% / ROI47.4%
- event=normal / head_gap=10-19pt: 検証 43R / 的中44.2% / ROI47.4%
- score=60-74 / head_gap=<5pt: 検証 85R / 的中29.4% / ROI49.2%
- head_top=25-34% / head_gap=10-19pt: 検証 35R / 的中42.9% / ROI49.5%
- grade=C / head_gap=5-9pt: 検証 75R / 的中36.0% / ROI53.7%
- head_top=<25%: 検証 156R / 的中30.1% / ROI58.2%
- head_top=<25% / head_gap=<5pt: 検証 137R / 的中30.7% / ROI58.7%
- grade=C: 検証 251R / 的中34.3% / ROI58.8%
- selected=no / points=13-14: 検証 253R / 的中34.8% / ROI58.9%
- points=13-14: 検証 255R / 的中34.9% / ROI59.0%
- selected=no: 検証 282R / 的中37.2% / ROI61.4%
- event=normal: 検証 303R / 的中39.3% / ROI61.9%
- head_top=25-34%: 検証 118R / 的中44.9% / ROI62.4%
- grade=B / head_gap=10-19pt: 検証 27R / 的中55.6% / ROI64.5%
- head_gap=<5pt: 検証 161R / 的中34.8% / ROI64.6%
- points=13-14 / head_gap=<5pt: 検証 161R / 的中34.8% / ROI64.6%
- event=normal / head_gap=<5pt: 検証 161R / 的中34.8% / ROI64.6%
- grade=C / head_gap=<5pt: 検証 160R / 的中34.4% / ROI64.8%
- points=11-12: 検証 27R / 的中59.3% / ROI66.0%
