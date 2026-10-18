"""Assemble Japanese workbook inputs and a reviewable research report."""
import argparse,json,csv,collections
from pathlib import Path
from .study import loadcsv
from .acquire import put

def main():
    p=argparse.ArgumentParser();p.add_argument('--study',required=True);p.add_argument('--out',required=True);a=p.parse_args();root=Path(a.study);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    read=lambda name:json.loads((root/(name+'.json')).read_text())
    summary=read('summary');tables=read('analysis_tables');records=read('audited_races');validation=read('validation_summary')
    pairs=loadcsv(root/'paired_comparison.csv');hist=loadcsv(root/'historical_validation.csv');diffs=loadcsv(root/'differences.csv');gaps=loadcsv(root/'missing.csv')
    sheets=[]
    def sheet(name,rows,description='',formulas=None):
        sheets.append({'name':name,'rows':rows,'description':description,'formulas':formulas or {}})
    overview=[{'項目':'元CSVレース数','値':summary['source_rows'],'判定':'原本変更なし'},
        {'項目':'公式追加レース','値':summary['official_extra_races'],'判定':'元CSVに含まれなかった28Rを独立補完'},
        {'項目':'統合・公式照合済み','値':summary['canonical_rows'],'判定':'174開催日の公式K原本に照合'},
        {'項目':'正常全着順の有効標本','値':summary['normal_eligible'],'判定':'事故・非通常着順を除外'},
        {'項目':'異常着順を含むレース','値':summary['abnormal_confirmed'],'判定':'事故等を通常順位で補完しない'},
        {'項目':'元212Rの理由未解決','値':summary['unresolved_original_incomplete'],'判定':'212Rとも公式の異常着順を伴う'},
        {'項目':'学習R','値':summary['split_counts']['学習'],'判定':'2025/10/18〜2026/6/30'},
        {'項目':'検証R','値':summary['split_counts']['検証'],'判定':'2026/7/1〜9/30'},
        {'項目':'最終評価R','値':summary['split_counts']['最終評価'],'判定':'2026/10/1〜17'},
        {'項目':'既存原本との同入力比較R','値':18,'判定':'改良版は後付け再計算。前向き実績ではない'},
        {'項目':'既存の的中','値':0,'判定':'18R・2開催日'},
        {'項目':'改良Aの的中','値':3,'判定':'18R・少数標本で改善確定不可'},
        {'項目':'改良Bの的中','値':2,'判定':'18R・少数標本で改善確定不可'},
        {'項目':'新研究版の締切前保存実測','値':0,'判定':'100R初期診断・300R中間評価は未到達'},
        {'項目':'C版の係数','値':'未採用','判定':'水面・選手の時系列検証不足'},
        {'項目':'Phase 1','値':'未完了','判定':'新ゆうき完全保存・浜名湖・7日95%を独立管理'},
        {'項目':'ROI・トリガミ率','値':'判定不能','判定':'過去オッズ原本なし。架空値を算出しない'},
        {'項目':'365日の開催網羅性','値':'未確定','判定':'元データの非開催191日は今回公式再確認していない'}]
    sheet('概要',overview,'対象2025/10/18〜2026/10/17。既存版の置換・mainマージなし。')
    sheet('コース別',tables['course'],'公式・通常全着順レース。進入変更の該当0Rも明示。',{'1着率':'=IF(C{r}=0,"判定不能",D{r}/C{r})','2着率':'=IF(C{r}=0,"判定不能",E{r}/C{r})','3着率':'=IF(C{r}=0,"判定不能",F{r}/C{r})'})
    sheet('決まり手連動',tables['conditional'],'決まり手は事後ラベル。実戦では事前特徴から予測し、実際の決まり手を入力しない。')
    sheet('水面分析',tables['environment'],'公式の本番水面条件による記述集計。展示時点との差・選手構成・開催節の交絡が残る。')
    sheet('交絡確認',tables['confounding'],'同選手・同コース・同月の弱風と強風を比較。因果効果ではなく感度確認。')
    sheet('選手適性',tables['racers'],'江戸川のみ。全国比較・道中順位・モーター使用期間が未取得のため係数不採用。')
    st=collections.defaultdict(lambda:collections.Counter())
    for row in tables['actual_st']:st[row['ST順位同値同順位']][row['着順']]+=1
    sheet('ST順位と着順',[{'本番ST順位':rank,'標本数':sum(c.values()),**{f'{i}着数':c[i] for i in range(1,7)},'本番STは事後情報':'事前入力禁止・同値は同順位'} for rank,c in sorted(st.items())])
    sheet('時系列評価',validation['historical'],'Aのみ枠なり仮定の後付け研究。既存版/B/Cの歴史再現に必要な事前特徴は未取得。')
    sheet('同入力比較',pairs,'既存は締切前原本、改良版は同じ事前データの後付け再計算。金額・ROIは不足を明示。')
    tactical=[]
    for path in sorted((root/'replays').glob('*.json')):
        log=json.loads(path.read_text());pred=log['research_replay']
        for boat in pred['lanes']:
            for h in boat['hypotheses']:
                tactical.append({'race_id':pred['meta']['race_id'],'版':pred['variant'],'艇番':boat['lane'],'選手名':boat.get('name'),'勝ち筋':h['win_path'],'負け筋':h['loss_path'],'攻め起点艇':h['attack_origin_lane'],'想定決まり手':h['tactic'],'事前根拠数':h['supported_observations'],'ほか5艇の反応':' / '.join(f"{r['lane']}号艇：{r['hypothesis']}" for r in h['reactions']),'候補3連単':','.join(f['combination'] for f in h['formations']),'実出目':log['actual_trifecta'],'実際の攻め方':'映像未確認・判定不能','ユーザー考察':''})
    sheet('展開レビュー',tactical,'全6艇の仮説と他5艇の反応。ユーザー考察欄は入力用。')
    flat=[]
    for r in records:
        flat.append({'レースID':r['race_id'],'日付':r['date'],'R':r['race_no'],'区分':r['split'],'正常有効':r['normal_eligible'],'異常確認':r['abnormal_confirmed'],'1着艇':r['first'],'2着艇':r['second'],'3着艇':r['third'],'4着艇':r['fourth'],'5着艇':r['fifth'],'6着艇':r['sixth'],'決まり手':r['method'],'風向':r['wind_dir'],'風速m':r['wind_m'],'風速区分':r['wind_bucket'],'波高cm':r['wave_cm'],'天候':r['weather'],'公式払戻100円':r.get('payout_per_100'),'艇番とコース':','.join(f"{b['lane']}:{b.get('course')}" for b in r['boats']),'異常コード':','.join(f"{b['lane']}:{b['status']}" for b in r['boats'] if b['status'] not in ['01','02','03','04','05','06']),'元取得元':r['original_source'],'公式URL':r['source_url'],'公式取得UTC':r.get('observed_at'),'公式SHA256':r['sha256'],'元取得日時':'不明','返還詳細':'未取得','潮位潮流':'不明'})
    sheet('全レース監査',flat,'公式原本・取得日時・ハッシュにより照合可能。元のCSVは変更していない。')
    sheet('差分監査',diffs,'風向・天候の数値コードは意味未解決のため公式文字表記を優先。差分数を誤り件数と同一視しない。')
    gc=collections.Counter(x['field'] for x in gaps)
    sheet('不足一覧',[{'項目':k,'該当R':v,'扱い':'不明・推測補完なし。詳細はmissing.csv','追加作業':'公式事前データ・全国成績・潮位観測・映像の時点整合を確認'} for k,v in sorted(gc.items())], '212Rの通常全着順欠落は事故等の構造的欠落。年全体の191非開催日は別途確認が必要。')
    # Official source evidence is adjacent to raw input, not duplicated on output tabs.
    original=loadcsv('data/research_edogawa_history/20251018_20261017/races.csv')
    rename={'race_id':'レースID','date':'日付','race_no':'R','method':'決まり手','first':'1着艇','second':'2着艇','third':'3着艇','fourth':'4着艇','fifth':'5着艇','sixth':'6着艇','wind_dir':'風向元値','wind_m':'風速m元値','wave_cm':'波高cm元値','weather':'天候元値','invalid_or_abnormal':'元フラグ','data_source':'取得元','source_url':'元URL','sha256':'元SHA256'}
    sheet('元CSV',[{rename.get(k,k):v for k,v in r.items()} for r in original],'元データの値を保持。数値コードの風向・天候は公式文字と混同しない。')
    sheet('月別有効数',tables['monthly'])
    body=json.dumps({'summary':summary,'sheets':sheets},ensure_ascii=False,indent=2);(out/'workbook_data.json').write_text(body)
    report=f'''# 江戸川 Phase 2 研究報告（2026-10-18）

## Phase 2-A 品質監査
元2,041R・174開催日を公式K原本で再照合した。元データにない28Rを追加し、統合2,069R、通常全着順1,850R、異常を含む219R。元の全着順不足212Rは公式上も通常6順位がそろわない異常レースであり、通常順位を補ってはいない。理由未解決は0R。原CSVの削除・上書きなし。

元データとのフィールド差分4,559件。風向1,945件・天候1,945件は数値コードと文字表記の違いを含む。コード対応が未検証のため公式優先。風速515件、波高100件、コースST54件の差も全件追跡する。着順の差分は0件。非公式データの係数をそのまま採用しない。

174開催日の公式原本・取得UTC・SHA256と差分を保存。元データの非開催191日は公式再監査しておらず、「365日完全網羅」とは断定しない。公式追加28Rのうち正常21R、異常7R。通常成績は1,850R、全件の事故含み資料は2,069Rとして別に保つ。

## Phase 2-B 場・展開・水面・選手
1〜6コースの1〜3着率、勝者決まり手×2着×3着の720条件セル、風速・風向・波高、月別、選手別コース成績・ST安定性を集計。Wilson 95%区間と分母を併記。正常1,850Rでは進入変更0R。実進入を艇番と勝手に置き換えず、公式対応で判定した。

8m以上の1コース1着率は39/102=38.24%。4〜5mは300/599=50.08%。本番水面条件の記述相関で、展示からの変化・季節・選手構成・モーター・開催節などの交絡が残る。同選手・同コース・同月の弱風/強風比較も保存したが、因果や予想係数としては未採用。潮位・潮流は観測点/日時/単位の整合データがなく不明。

全国同期間比較、モーター使用期間、道中の逆転・旋回経路、攻め起点の正解ラベルは不足。勝者の決まり手だけから、負けた3号艇が攻めて流れた等とは断定しない。

## Phase 2-C/D 独立A/Bと評価
既存v2の艇別仮説生成と既存江戸川エンジンをSHA固定・無変更で再利用。Aは公式学習期間のコース出目統計、Bは想定勝者/決まり手と条件付きの連動分布を使い、事前根拠がある展開仮説を優先する。勝者と攻め起点を分離して全6艇の勝ち筋/負け筋と他5艇の反応を残す。未検証の水面・選手係数を入れるCは停止。

学習1,322R（〜6/30）、検証429R（7〜9月）、最終評価99R（10/1〜17）。Aの後付け研究では149/429=34.73%、38/99=38.38%。事前スナップショット不足のため過去は枠なり仮定。実進入・本番ST・確定決まり手を予想入力に使用していない。これは既存AIとの同条件比較ではなく、B/Cの歴史成績も捏造していない。最初の監査計算はF単独表記と公式追加28Rを反映して再計算した。予想規則の最終評価への最適化は行っていない。今後の変更は新しい未来評価で判定する。

10/17〜18の既存締切前原本18R・2開催日と同じ事前入力で再計算した比較では既存0/18、A3/18、B2/18。ただし改良版は後付け再計算であり、前向き実績0R。開催日クラスタのブートストラップも保存し、18Rでは改善・悪化を確定しない。過去オッズ原本がないため、依頼条件に従いROIとトリガミ率は判定不能。

## Phase 2-E/F 並行保存・レビュー基盤
独立保存先 research-edogawa-phase2-state / data/edogawa_phase2_shadow。既存の公式事前スナップショットを読み取る方式で、新たな公式取得・Discord・X送信は行わない。同一入力でA/Bを一つの原本に保存し、Git pushとリモート原本読戻し後に締切前受領を別記録。遅延受領は成功から除外。結果と分析は別保存し、ユーザー考察欄を用意。失敗記録・3回の限定push再試行・原本からのresumeがある。実Git bare remoteの結合試験を含む26件のテストが成功。

新しい手動専用workflowを研究ブランチに用意した。スケジュールは追加せず、現在未稼働。GitHubは新規workflowの手動実行にもdefault branchへの登録が必要で、main無断変更禁止のため登録・自動起動は実行していない。既存登録済みworkflowの変更もしていない。100R/300Rの前向き評価とリソース競合の実測は未完了。短時間1R/回・独立concurrency・3分上限の設計で、稼働後に起動/待機/所要時間を監視する。

## Phase 1の未達項目
Phase 1は未完了。新ゆうき完全LOGの締切前保存実証、浜名湖開催確認、95%以上の7日実測は独立管理する。Phase 2の開始や後付け評価を達成実測へ転用しない。

## Phase 3へ進む前の作業
1. 独立実行環境で締切前受領を実証し、まず100R・次に300Rを蓄積する。
2. 全国同期間の選手成績、時点付き事前特徴、モーター使用期間、過去オッズを取得監査する。
3. 攻め起点と連動失敗は映像による人手ラベルを作成し、ユーザー考察と公式事実を別列で保持する。
4. 風・波は開催節/選手/季節の交絡と期間外評価を追加し、Cの投入可否を決める。
5. 初期18Rの差だけで既存版を置き換えない。main・配信・Secrets・既存環境変数の変更なし。
'''
    (out/'REPORT.md').write_text(report)
    print(json.dumps({'sheets':len(sheets),'rows':{s['name']:len(s['rows']) for s in sheets}},ensure_ascii=False))

if __name__=='__main__':main()
