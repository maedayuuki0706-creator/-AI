# 新ゆうき 展開予想研究 v1（配信完全分離）

目的：Kindle『生成AIで究める競艇予測』第3〜5章を参考に、事前データの構造化→6艇の勝ち筋/負け筋→他艇の反応→3連単候補→事後照合を研究専用で試す。書籍のサンプル確率・収益は実証値として扱わない。

## 安全境界

- 研究用の純粋関数とローカルJSON出力のみ。既存のDiscord/X配信、本番予想、データ取得、Secrets、Actions、スプレッドシートは変更しない。
- ワークフローへの自動接続なし。自動取り込み・自動投稿・自動学習なし。
- 締切3分以上前・日本時間の事前スナップショットが必須。結果や本番STは予測側に入れない。
- 全6艇の1着筋（各艇1〜3戦術）、他5艇の反応、成功/失敗条件、着順候補を記録。
- 着順候補は進入位置・旋回戦術による仮説例。統計校正前のため確率・EV・買い目・金額は出さない。
- 展示STは観測値で、本番STの予測値にはしない。モーター2連率から出足/伸び/回り足を断定しない。
- 事故/F/L/返還/未確定は普通の展開ミスとして数えない。
- 結果照合は別レコードに保存し、事前予想は書き換えない。現版では着順候補のカバー率しか評価しない。

## 実行

リポジトリのルートから実行する。自動取得・外部送信はない。

    python -m unittest discover -s research/scenario_v1/tests -v
    python -m research.scenario_v1.run forecast --input /tmp/pre_race.json --out /tmp/yuuki_scenario_frozen.json
    python -m research.scenario_v1.run review --input /tmp/post_race.json --out /tmp/yuuki_scenario_review.json

### 事前入力例（架空データ。実レース予想ではない）

    {
      "meta": {
        "day": "20261016", "jcd": "06", "rno": 7,
        "deadline": "19:00", "captured_at": "2026-10-16T18:50:00+09:00"
      },
      "analysis": {
        "inputs": [
          {"lane": 1, "racer_id": "4001", "predicted_course": 1, "avg_st": 0.14, "motor_top2_rate": 40},
          {"lane": 2, "racer_id": "4002", "predicted_course": 2},
          {"lane": 3, "racer_id": "4003", "predicted_course": 3},
          {"lane": 4, "racer_id": "4004", "predicted_course": 4},
          {"lane": 5, "racer_id": "4005", "predicted_course": 5},
          {"lane": 6, "racer_id": "4006", "predicted_course": 6}
        ],
        "preview": {"wind_speed": 5, "wave_cm": 10}
      }
    }

コース入替があれば枠番とは別に predicted_course を1〜6で指定する。取得できない要素は欠損のまま保持する。

### 事後入力例

    {
      "frozen": {"...": "forecast出力JSONを完全に埋め込む"},
      "result": {"race_id": "20261016_06_07", "status": "settled", "trifecta": "3-1-4"}
    }

結果の status は settled または unsettled / pending / refund / cancelled / accident / f / l。
出力の formation_match は「その着順が候補に存在したか」であり、攻め方が再現した証拠ではない。

## 次段階（まだ実装していない）

1. 展示進入・確定進入差、今節足、出足/伸び/回り足を信頼できるデータへ連結。
2. 1Mの隊形と実際の攻めの成否を別途ラベル化。映像などで裏づけが必要。
3. 事前固定レースだけで現行モデルと並行比較し、場・風・進入条件の標本数と校正精度を確認。
4. 配信や買い目への反映は結果検証後に別途承認を得る。
