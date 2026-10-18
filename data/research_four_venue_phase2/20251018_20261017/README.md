# 4場・過去1年の公式研究データ

期間: 2025-10-18〜2026-10-17。
公式K原本365日を確認し、江戸川2069R・児島2292R・唐津2046R・浜名湖2469R、計8876R。
通常6艇8192R・事故等682R・同着2Rを区別する。欠測を推測で補完しない。

- 既存原本174日: `data/research_edogawa_phase2/20261018/official_raw_archives.zip` を再利用。
- 新規K原本191日: `official_K_new_raw.zip`。メンバー名はSHA256。重複取得なし。
- 取得・解析記録: `acquisition/a3057119a0ad51bdc46fd4b390233fa70ebd9a4023bfd15633c11891c11ab110.json.gz`。
- `K_audit_summary.json` はB番組表結合前のK監査チェックポイント。
- B番組表は別原本で収集中。取得失敗や選手ID不一致を欠測として残す。
- 実ST・決まり手・実進入・K展示値は事後に取得した記録。締切前の実予想原本ではない。
- 予想原本の保存先は別ブランチ `research-four-venue-phase2-state`。

圧縮された証拠を復元する場合:

```bash
python3 -m research.four_venue_phase2.restore_evidence \
 --root data/research_four_venue_phase2/20251018_20261017 \
 --original data/research_edogawa_phase2/20261018
```

既存ファイルと内容が異なる場合は停止する。既存予想LOGには書き込まない。
