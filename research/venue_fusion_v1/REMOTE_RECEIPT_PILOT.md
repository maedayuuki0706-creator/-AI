# 4場融合AI｜締切前Git遠隔受領と独立研究パイロット

**研究専用。既存メイン・PT・Discord・X・Render・Sheets・Secrets・main・既存場別AIワーカーは変更していない。**

## Work君の成果との関係

PR #46：公式1年分の番組表・潮位・前検・モーター周期の補完は利用対象だが**二重収集しない**。
PR #47：真正の締切前原文によるメイン公式core＋新ゆうき＋場別の56R事後比較を済ませた。
PR #48：本当の締切前に限ってローカルの3モデル10点を新規凍結するゲートを実装した。

**本PRはその次の段階**：実際の締切前の研究原本を保存済みの既存場別研究stateから読み、新しい融合カードを別stateへpushし、遠隔2段階受領を照合する。

## 研究ワークフロー

1. pilot_worker.py：既存の research-venue-specialists-state を**読取のみ**で参照。既存の公式原本、6艇、SHA、既存の遠隔受領、公式締切時刻と取得時刻を確認。過去レースは生成できない。
2. prospective.build_live：本当に現時刻がレース締切より3分以上前のときのみ既存メインcore＋新ゆうき＋場別の各10点を生成。5分未満の時間余裕なら開始しない。
3. remote_receipt.publish：**--publishを指定した場合のみ**別の research-venue-fusion-forward-state に元カードを新規commit/pushし、GitHubリモートからblobを読み戻す。その後、**別ファイルの受領証**もcommit/pushして読み戻す。いずれも締切3分前までに完了しない限り成績に入れない。古いカードへの上書きは禁止。
4. independent_grade.py：レース終了後に2つの遠隔Gitコミット・ハッシュ・受領時間を検証し、公式結果照合後に初めて的中/回収率/トリガミ、1着/2着/3着欠落を判定する。

## 技術と限界

- 新state作成時は0件。既存の場別研究originalと独立し、本番配送とは完全に切り離す。
- 受領時間はGitHub Actionsランナー時刻とGitコミット時刻に基づく。独立したGitHubサーバー時刻証明ではなく、厳密な第三者TSAによる証明とは区別する。
- 元のMain-coreは実際のprediction_engine.analyze_raceを使用するが、当時の全プロフィール・前日フォーム・オッズを必ずしも含まない。メイン君の本番フル再現とは言わない。
- 検証済みの場別補正がゼロなら「メインcore＋新ゆうき」と「＋場別」は同一10点。差を捏造しない。
- 外れ理由を選択ミス/候補不足などに区分しても、1マークの攻め失敗の因果は動画を確認するまで推定扱い。
- 途中のネットワーク障害、締切遅延、原本欠測、返還は除外。後から予想を生成しない。
- 既存の記事研究PR #45、データ拡張PR #46の知識は自動重み反映しない。

## 手動実行例

最初に、元研究stateを /tmp/original-state に、新研究stateを /tmp/fusion-state に、それぞれ別Gitブランチでcheckout。

下見（新stateに書かない）：

    python -m research.venue_fusion_v1.pilot_worker --source /tmp/original-state --state /tmp/fusion-state --scratch /tmp/evidence --max-races 2

研究用の遠隔保存を明示的に行う：

    python -m research.venue_fusion_v1.pilot_worker --source /tmp/original-state --state /tmp/fusion-state --scratch /tmp/evidence --max-races 2 --publish

実施するときは研究stateだけGit pushできる専用checkoutが必要。実レースがまだ0件の場合は0件のまま報告する。

## 再現テスト

    python -m unittest research.venue_fusion_v1.test_remote_receipt research.venue_fusion_v1.test_pilot_worker research.venue_fusion_v1.test_prospective -v

実際のローカルbare Gitサーバー2つを使ったユニットテストで、ソースと保存先の分離、重複・結果漏洩・古い入力・時間切れ・返還を検証する。

### 次の研究判定

最初の実レースの遠隔受領後、3枚同じ10点の採点LOGを保存。100R→300R単位の時系列外比較を行う。本番へ自動採用しない。
