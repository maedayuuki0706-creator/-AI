# 航跡 — 自分専用 BOAT LAB

**Cloudflare未接続でもサイトと検索エンジンは完成・ローカル実データ検証済み。** デプロイ前の全拒否Bootstrap、独自ドメイン不要のWorkers.dev＋Worker単位Access版は [docs/WORKERS_DEV_DEPLOY.md](docs/WORKERS_DEV_DEPLOY.md) を参照。Accessの実設定・R2投入・iPhone実機確認は所有者のログインが必要です。

Cloudflare Workers + Access + **private R2** の個人研究サイト。2026-10-27現在はローカル実装・検証済み、Cloudflare未接続・未デプロイ。
既存 viewer / main / Discord / X / AI / 研究ワーカー / Sheets / Secrets / Render は一切変更しない。

## できること

8画面：ホーム、全国24場の結果検索、選手検索、モーター統計、水面研究、万舟研究、AI研究室（未取得表示）、データ管理。

- 公式205,269R / 1,231,614出走 / 1,794選手、2022-01-01〜2025-12-31。
- 当地・日付範囲・枠番/実進入別の1着率・2/3連率・平均ST。公式得点率「勝率」とは区別。
- 2026年10月の事前風波3,876件、モーター日次14,688行。第三者由来・公式未照合。
- 3,876レースの展示/直前オッズなどを必要時だけR2から取得。カテゴリごとに取得時刻・締切を保持。
- 主キーとUNIQUE制約、索引、事前集計、30件のカーソルページ分割。条件が疎な場合のR2検索は8日分までで継続カーソルを返す。
- 原本SQLiteはブラウザへ渡さない。検索用R2データも認証後のWorker Binding経由のみ。

## なぜR2を初期構成にしたか

D1は無料で1日100,000行書込。全データと索引の初期投入は保守的試算6,650,049書込（80,000ずつ84ファイル）になり、即日運用に不向き。R2検索索引は4,819オブジェクト/378,482,198 bytes、詳細3,876オブジェクト/58,179,413 bytesで計436,661,611 bytes。日別・選手別に読み、初回から全履歴を扱える。D1実装は任意の将来用として残す。

R2原本保管と検索用prefixを分離する。現在のコードに原本取得エンドポイントはない。R2 Public URL / r2.dev / Custom Domainは全て無効にする。

## ローカル再現（Node >=22.13 / Python 3）

データはユーザーの私有ファイルから取得し、リポジトリ外のディレクトリで扱う。以下のパスは取得した実ファイルへ置き換える。

```bash
python3 scripts/import_data.py --source /private/input/official_results_2022_2025.sqlite --preview /private/input/preview_research.sqlite --out /private/work/search.sqlite
python3 scripts/export_r2.py --db /private/work/search.sqlite --out /private/release/query
python3 scripts/export_details.py --preview /private/input/preview_research.sqlite --out /private/release/details
LAB_DB=/private/work/search.sqlite LAB_R2=/private/release node --test tests/*.test.mjs
DATA_BACKEND=r2 LAB_DB=/private/work/search.sqlite LAB_ARCHIVE=/private/release node scripts/local.mjs --preview
```

最後のコマンドは**127.0.0.1専用の画面確認ハーネス**。Cloudflare Accessを通らないため実運用・外部共有禁止。本番Workerにローカル用の認証回避コードはない。`--preview`を省くと未認証を403で拒否する。

デプロイは [docs/DEPLOY.md](docs/DEPLOY.md)、検証結果・制限は [docs/VALIDATION.md](docs/VALIDATION.md)。コードに原本・研究DB・メールアドレス・Secretsを含めない。
