# 4場・過去1年の公式研究データ

期間: 2025-10-18〜2026-10-17。
公式K原本365日を確認し、江戸川2069R・児島2292R・唐津2046R・浜名湖2469R、計8876R。
通常6艇8192R・事故等682R・同着2Rを区別する。欠測を推測で補完しない。

- 既存原本174日: `data/research_edogawa_phase2/20261018/official_raw_archives.zip` を再利用。
- 新規K原本191日: `official_K_new_raw.zip`。メンバー名はSHA256。重複取得なし。
- 取得・解析記録: `acquisition/a3057119a0ad51bdc46fd4b390233fa70ebd9a4023bfd15633c11891c11ab110.json.gz`。
- `K_audit_summary.json` はB番組表結合前のK監査チェックポイント。
- B番組表365日も取得・解析済み。`programs/official_B_raw_6e1649027a18_1.zip` と `_2.zip` に原本を保存。
- 最新の監査・分析・4場別DBは `CURRENT.json` の研究ID `eed2cf3775203abb` を参照。
- 予定9012Rは結果8876R＋公式中止136R（江戸川127・唐津6・浜名湖3）。未解明の予定Rは0。
- 級別は全8876Rの6艇を同一選手IDで照合。平均STの歴史事前原本、潮、返還明細等は未取得。
- 実ST・決まり手・実進入・K展示値は事後に取得した記録。締切前の実予想原本ではない。
- 予想原本の保存先は別ブランチ `research-four-venue-phase2-state`。

圧縮された証拠を復元する場合:

```bash
python3 -m research.four_venue_phase2.restore_evidence \
 --root data/research_four_venue_phase2/20251018_20261017 \
 --original data/research_edogawa_phase2/20261018
```

既存ファイルと内容が異なる場合は停止する。既存予想LOGには書き込まない。

各 `studies/eed2cf3775203abb/venue_XX_database_analysis.zip` に場別CSV/JSON/`history.sqlite.gz` を同梱。
SQLiteはgzipを展開して利用する。生の状態コードは保持し、転覆や実際の攻め方を着順から推測しない。
原票ID `YYYYMMDDJJRR` と予想LOG ID `YYYYMMDD_JJ_RR` の対応は `race_id_mapping.csv.gz`（復元後.csv）を参照。

成果の予想比較は後付け研究。改良版の締切前実測は0Rで、Phase1・Phase2とも未完了。
