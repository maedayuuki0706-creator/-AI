"""Isolated scheduled collector. All writes stay beneath --out; no dispatch calls."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timedelta
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import fusion_shadow as core


def now_jst():
    return datetime.now(core.JST)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _strategy(model, families, **extra):
    return core.card(model.get("picks"), label=model.get("label"), families=families,
                     selection_policy=model.get("selection_policy"), **extra)


def build_live(day, jcd, rno, deadline, *, prefetch=True):
    # Import prediction helpers only inside an isolated capture subprocess.
    import direct_discord_notify as official_source
    import detailed_discord_notify as cards
    import bridge_learning
    import four_way_prototype as trial
    import hiyori_source
    import hiyori_model
    import mid_value_selection
    import opportunity_alerts
    import pt2_sheet_db
    import pt2_strategy_cards
    import prediction_engine_v2
    import x_featured_selector as featured
    from market_structure import analyze_market_structure
    from manshu_shadow_watch import classify
    from ticket_compression import compression_snapshot

    captured = now_jst()
    # Fast exhibition gate: do not spend the capture budget on a race whose
    # official preview is still empty. All prefetches are GETs in this child;
    # the production modules/files and their delivery behavior are unchanged.
    if prefetch:
        preview_raw = official_source.fetch(official_source.official_url('beforeinfo', day, jcd, rno))
        if official_source.parse_beforeinfo(preview_raw).get('exhibition_count') != 6:
            raise ValueError("Six official exhibition records are not yet available")
        urls = [official_source.official_url(kind, day, jcd, n) for kind, n in
                (('racelist', rno), ('odds3t', rno), ('racelist', 1))]
        with ThreadPoolExecutor(max_workers=4) as pool:
            prefetched = [pool.submit(official_source.fetch, url) for url in dict.fromkeys(urls)]
            biyori_fetch = pool.submit(hiyori_source.fetch_race, day, jcd, rno)
            for future in prefetched:
                future.result()
            source = biyori_fetch.result()
    else:
        source = hiyori_source.fetch_race(day, jcd, rno)
    source["fetched_at"] = now_jst().isoformat()
    official = official_source.analyze_official(day, jcd, rno)
    if not official or official.get("preview", {}).get("exhibition_count") != 6:
        raise ValueError("Live official/exhibition data are not ready")
    hiyori = hiyori_model.analyze(official, source, day, jcd, rno)
    database = pt2_sheet_db.enhance_analysis(official, jcd)
    odds = {r["combination"]: r.get("odds") for r in official["trifecta"]}
    preview = official["preview"]
    knowledge = prediction_engine_v2.analyze_race_v2({
        "race": {"venue": official["venue"], **{k: preview.get(k) for k in
                 ("wind_speed", "wave_cm", "tide", "air_temp_c", "water_temp_c")}},
        "boats": official["inputs"], "trifecta_odds": odds})
    knowledge.update(inputs=deepcopy(official["inputs"]), preview=deepcopy(preview))
    request = {"day": day, "jcd": jcd, "rno": rno, "deadline": deadline,
               "captured_at": captured.isoformat(), "source_fetched_at": source["fetched_at"]}
    analyses = {"existing": official, "sheet_db": database, "knowledge_v2": knowledge, "hiyori": hiyori}
    core.validate_capture(request, analyses, now_jst())
    bundle = trial.build_bundle({**request, "official": official}, hiyori, source, now=now_jst())
    strategies = {}
    for name, analysis, families in (("main", official, ["official"]),
            ("hiyori", hiyori, ["hiyori"]), ("db_native", database, ["official"])):
        copied = deepcopy(analysis)
        selected = cards.displayed_picks_variable(copied, True)
        if name == "main":
            selected = bridge_learning._reallocate(copied, selected)
        strategies[name] = core.card(selected, label=name, families=families,
                                     selection_policy="native-live-rebuilt")
    strategies["main_selected"] = core.card(
        strategies["main"]["picks"] if official_source.selected_by_ai(official, official_source.load_policy()) else [],
        label="メイン厳選", families=["official"],
        selected=official_source.selected_by_ai(official, official_source.load_policy()))
    for name in ("existing", "hiyori", "prototype1", "prototype2", "prototype3"):
        families = ["official"] if name == "existing" else ["hiyori"] if name in ("hiyori", "prototype3") else ["official", "hiyori"]
        strategies[f"comparison_{name}"] = _strategy(bundle["models"][name], families)
    pt2 = pt2_strategy_cards.build_strategy_cards(database, bundle["models"]["prototype2"])
    for name, model in pt2["cards"].items():
        families = ["official", "hiyori"] if name == "balanced" else ["official"]
        strategies[f"pt2_{name}"] = _strategy(model, families, version=pt2["version"])
    mid_value_selection.install(opportunity_alerts)
    for kind in ("mid", "long"):
        payload = opportunity_alerts._build_payload(official["venue"], rno, deadline, official, kind)
        selected = opportunity_alerts._is_selected_mid(payload) if kind == "mid" else opportunity_alerts._is_selected_longshot(payload, official)
        candidates = core.picks(payload["picks"])
        strategies[kind] = core.card(candidates, label=f"{kind}候補", families=["official"],
                                     score=payload["score"], selection_policy=payload["score_version"])
        strategies[f"{kind}_selected"] = core.card(candidates if selected else [],
            label=f"{kind}厳選", families=["official"], selected=selected, score=payload["score"])
    featured_race = {"models": [featured._model(name, bundle["models"][name])
                                for name in ("prototype1", "prototype2", "prototype3")]}
    featured_plan = featured._ticket_plan(featured_race)
    if featured_plan:
        strategies["featured_plan"] = core.card(featured_plan["main"] + featured_plan["cover"],
            label="X用AI統合候補", families=["official", "hiyori"],
            main_picks=featured_plan["main"], cover_picks=featured_plan["cover"],
            selection_policy="featured-live-ticket-plan-without-daily-post-quota")
    for name, fn in (("featured_overlap", featured._overlap_candidate),
                     ("featured_value", featured._confidence_candidate)):
        candidate = fn(featured_race)
        strategies[name] = core.card(candidate["picks"] if candidate else [],
            label=name, families=["official", "hiyori"], selected=bool(candidate),
            score=candidate.get("score") if candidate else None)
    # Compression is another selector, not an independent probability model.
    strategies["main_compressed_10"] = core.card(
        compression_snapshot(official)["levels"]["10"],
        label="メイン頭固定10点", families=["official"])
    context_rows = [{**b, "wind_m": preview.get("wind_speed"), "wave_cm": preview.get("wave_cm"),
                     "exhibition_course": b.get("predicted_course")} for b in official["inputs"]]
    context = classify({**request, "venue": official["venue"], "rows": context_rows, "settled": False}, now_jst())
    provenance = {"source_url": source.get("source_url"), "hiyori_input_hash": core.digest(source),
                  "official_urls": {kind: official_source.official_url(kind, day, jcd, rno)
                                    for kind in ("racelist", "beforeinfo", "odds3t")},
                  "legacy_fusion_available": False,
                  "legacy_fusion_reason": "Original kyoteibiyori_adapter.race_model is explicitly not ready; real Hiyori model used instead.",
                  "learning": "Existing bridge policy retained; all_ai_learning is a report, not an independent engine.",
                  "delivery": "All native cards are rebuilt for research; they are not claims of delivered cards."}
    record = core.build_prediction(request, analyses, strategies, now_jst(), context=context, provenance=provenance)
    snapshot = {"request": request, "analyses": analyses, "hiyori_source": source,
                "comparison_bundle": bundle, "featured_plan": featured_plan}
    return record, snapshot


def capture_one(out, day, jcd, rno, deadline):
    root = Path(out)
    key = core.identity(day, jcd, rno)
    prediction_path = root / "predictions" / day / f"{key}.json"
    if prediction_path.exists():
        existing_version = load(prediction_path).get("version")
        return {"key":key, "status":"already_frozen" if existing_version == core.VERSION else "already_frozen_other_engine",
                "existing_engine_version":existing_version}
    record, snapshot = build_live(day, jcd, rno, deadline)
    if now_jst() > core.cutoff(day, deadline) - timedelta(seconds=core.MIN_LEAD_SECONDS):
        raise ValueError("Capture finished too late; nothing is frozen")
    snapshot_bytes = gzip.compress(json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                               allow_nan=False).encode(), mtime=0)
    snapshot_path = root / "snapshots" / day / f"{key}.json.gz"
    if not core.write_once(snapshot_path, snapshot_bytes) and snapshot_path.read_bytes() != snapshot_bytes:
        raise ValueError("A different frozen input snapshot already exists")
    record["provenance"]["snapshot_sha256"] = core.sha256(snapshot_bytes).hexdigest()
    record["digest"] = core.digest({k: v for k, v in record.items() if k != "digest"})
    stored = core.write_once(prediction_path, record)
    return {"key": key, "status": "frozen" if stored else "already_frozen", "digest": record["digest"]}


def collect_card(root, day):
    import direct_discord_notify as base
    path = Path(root) / "cards" / f"{day}.json"
    if path.exists():
        cached = load(path)
        if (now_jst() - core.aware(cached["observed_at"])).total_seconds() < 1800:
            return cached
    venues = base.discover_venues(day)
    card, errors = {}, {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        work = {pool.submit(base.deadlines, day, venue): venue for venue in venues}
        for future in as_completed(work):
            venue = work[future]
            try:
                deadlines = future.result()
                if not deadlines:
                    errors[venue] = "deadline_not_available"
                card[venue] = deadlines
            except Exception as exc:
                errors[venue] = f"{type(exc).__name__}: {exc}"
    value = {"day": day, "observed_at": now_jst().isoformat(), "venues": card, "errors": errors}
    core.write_report(path, value)
    return value


def _capture_child(root, race, timeout):
    command = [sys.executable, str(Path(__file__).resolve()), "--out", str(Path(root).resolve()),
               "--capture-one", race["day"], race["jcd"], str(race["rno"]), race["deadline"]]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=max(1, timeout))
        if proc.returncode:
            return {"key": race["key"], "status": "waiting", "reason": proc.stderr.strip()[-600:]}
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except subprocess.TimeoutExpired:
        return {"key": race["key"], "status": "budget_exceeded"}


def collect_results(root, end):
    import direct_discord_notify as base
    from daily_report import parse_payout
    root = Path(root)
    pending = []
    for path in sorted((root / "predictions").glob("*/*.json")):
        record = load(path)
        if record.get("version") != core.VERSION:
            continue
        evaluation_path = root / "evaluations" / path.parent.name / path.name
        existing = load(evaluation_path) if evaluation_path.exists() else None
        # Preserve the original observation. Later-published ST/finish/method
        # details are a separate append-only verification, never a new forecast.
        if existing and (existing.get("excluded_reason") or
                         (existing.get("official_result") or {}).get("race_details") or
                         (root / "official_verifications" / path.parent.name / path.name).exists()):
            continue
        retry_path = root / "details_retry" / path.parent.name / path.name
        if existing and retry_path.exists() and now_jst() < core.aware(load(retry_path)["next_attempt_at"]):
            continue
        deadline = core.aware(record["deadline_at"])
        checkpoint_path = root / "checkpoints" / record["day"] / path.name
        if now_jst() < deadline + timedelta(minutes=3) or not checkpoint_path.exists():
            continue
        checkpoint = load(checkpoint_path)
        if checkpoint["prediction_digest"] != record["digest"]:
            raise ValueError("Checkpoint prediction mismatch")
        if core.aware(checkpoint["prediction_committed_at"]) >= deadline:
            core.write_once(root / "evaluations" / record["day"] / path.name,
                            {"key": record["key"], "excluded_reason": "late_remote_checkpoint"})
            continue
        pending.append((record, checkpoint, path.name, existing))
    # New settlement has priority over optional late ST/method enrichment.
    pending.sort(key=lambda pair: (pair[3] is not None, pair[0]["deadline_at"]))

    def fetch_result(record, checkpoint, filename, existing):
        url = base.official_url("raceresult", record["day"], record["jcd"], record["rno"])
        raw = base.fetch(url)
        result = parse_payout(raw)
        try:
            from race_context import parse_result
            result["race_details"] = parse_result(raw, record["day"], record["jcd"], record["rno"])
        except ValueError as exc:
            result["race_details"] = None
            result["race_details_missing_reason"] = str(exc)
        result.update(key=record["key"], source_url=url, observed_at=now_jst().isoformat(),
                      response_sha256=core.sha256(raw.encode()).hexdigest(),
                      prediction_committed_at=checkpoint["prediction_committed_at"],
                      prediction_commit_sha=checkpoint["commit_sha"])
        if existing:
            prior = existing["official_result"]
            if (prior.get("status"), prior.get("payouts"), prior.get("refund_lanes")) != (
                    result.get("status"), result.get("payouts"), result.get("refund_lanes")):
                raise ValueError("Later official details do not match the original settled payout; held for review")
            if not result.get("race_details"):
                observed = now_jst()
                core.write_report(root / "details_retry" / record["day"] / filename,
                    {"key":record["key"], "last_attempt_at":observed.isoformat(),
                     "next_attempt_at":(observed+timedelta(minutes=20)).isoformat(),
                     "status":"official_finish_st_method_not_available",
                     "source_url":url, "missing_reason":result.get("race_details_missing_reason")})
                return record["key"], False
        outcome = core.evaluate(record, result, now_jst())
        if outcome:
            if existing:
                core.write_once(root / "official_verifications" / record["day"] / filename,
                    {"key":record["key"], "prediction_digest":record["digest"],
                     "original_evaluation_digest":core.digest(existing), "evaluation":outcome,
                     "note":"Append-only later official details; frozen forecast and first result observation retained"})
            else:
                core.write_once(root / "results" / record["day"] / filename, result)
                core.write_once(root / "evaluations" / record["day"] / filename, outcome)
        return record["key"], bool(outcome)

    settled, errors = 0, []
    # Batches prevent an old pending race from monopolizing this collector.
    for offset in range(0, len(pending), 4):
        if time.monotonic() >= end - 10:
            break
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(fetch_result, *pair) for pair in pending[offset:offset + 4]]
            for future in as_completed(futures):
                try:
                    _, success = future.result()
                    settled += int(success)
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
    return {"settled": settled, "errors": errors[:10]}


def checkpoint(root, commit_sha):
    """Called only AFTER a successful prediction push; receipts are a second commit."""
    root = Path(root).resolve()
    repository_root = Path(subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"], text=True).strip())
    observed = now_jst()
    written = 0
    for path in sorted((root / "predictions").glob("*/*.json")):
        receipt = root / "checkpoints" / path.parent.name / path.name
        if receipt.exists():
            continue
        relative = path.relative_to(repository_root).as_posix()
        stored = subprocess.check_output(["git", "-C", str(repository_root), "show",
                                          f"{commit_sha}:{relative}"], text=True)
        record = load(path)
        if core.digest(json.loads(stored)) != core.digest(record):
            raise ValueError("Checkpoint must refer to the pushed prediction")
        value = {"key": record["key"], "prediction_digest": record["digest"],
                 "commit_sha": commit_sha, "prediction_committed_at": observed.isoformat(),
                 "eligible_checkpoint": observed < core.aware(record["deadline_at"])}
        written += int(core.write_once(receipt, value))
    return written


def write_summary(root):
    root = Path(root)
    summary = core.summarize(root)
    summary["updated_at"] = now_jst().isoformat()
    core.write_report(root / "summary.json", summary)
    lines = ["# 全AI融合・ログ専用テスト", "", "Discord・Xへの配信や実際の購入は行いません。", "",
             f"更新: {summary['updated_at']}", "", f"未確定: {summary['pending_races']} レース", "",
             f"締切後の保存で除外: {summary['excluded_late_checkpoint_races']} レース", "",
             "| 比較対象 | 判定レース | 的中 | 的中率 | 投資額 | 払戻額 | 回収率 | 万舟的中 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, item in summary["models"].items():
        hit = f"{item['hit_rate_pct']:.1f}%" if item["hit_rate_pct"] is not None else "—"
        roi = f"{item['roi_pct']:.1f}%" if item["roi_pct"] is not None else "—"
        lines.append(f"| {name} | {item['eligible_races']} | {item['hits']} | {hit} | {item['stake_yen']:,}円 | {item['return_yen']:,}円 | {roi} | {item['manshu_hits']} |")
    if not summary["models"]:
        lines += ["", "テストを準備しました。締切前に固定した予想と公式結果が揃うと成績を表示します。"]
    lines += ["", "融合と control_*_10 は各レース1,000円。native_* は元の点数に応じた金額です。", "",
              "予想は predictions、保存確認は checkpoints、公式払戻は results、採点は evaluations。", "",
              "データ欠損・対象外・処理時間不足は coverage に記録し、外れとして数えません。"]
    text = "\n".join(lines) + "\n"
    (root / "summary.md").write_text(text, encoding="utf-8")
    return summary


def run(root, budget_seconds=125):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    start, now = time.monotonic(), now_jst()
    end = start + budget_seconds
    day = now.strftime("%Y%m%d")
    status = {"version": core.VERSION, "research_only": True, "started_at": now.isoformat(),
              "day": day, "captures": [], "status": "running"}
    if not 8 <= now.hour <= 23:
        status["status"] = "waiting_for_race_hours"
    else:
        try:
            schedule = collect_card(root, day)
            due, missed = [], []
            for jcd, deadlines in schedule["venues"].items():
                for rno, deadline in enumerate(deadlines, 1):
                    key = core.identity(day, jcd, rno)
                    previous_path = root / "predictions" / day / f"{key}.json"
                    if previous_path.exists():
                        previous_version = load(previous_path).get("version")
                        if previous_version != core.VERSION:
                            status.setdefault("other_engine_frozen_races", []).append(
                                {"key":key,"engine":previous_version,"status":"reference_only_preserved"})
                        continue
                    lead = (core.cutoff(day, deadline) - now_jst()).total_seconds()
                    race = {"key": key, "day": day, "jcd": jcd, "rno": rno, "deadline": deadline}
                    if 300 <= lead <= 1800:
                        due.append(race)
                    elif lead < 300:
                        missed.append({**race, "status": "not_captured_before_window_closed"})
            due.sort(key=lambda r: (r["deadline"], r["jcd"], r["rno"]))
            status.update(due_races=len(due), missing_races=missed, schedule_errors=schedule["errors"])
            # Three independent Python processes avoid production module/global patches leaking between races.
            for offset in range(0, len(due), 3):
                if time.monotonic() >= end - 25:
                    status["captures"] += [{"key": r["key"], "status": "deferred_by_budget"} for r in due[offset:]]
                    break
                timeout = min(90, end - time.monotonic() - 20)
                with ThreadPoolExecutor(max_workers=3) as pool:
                    futures = [pool.submit(_capture_child, root, r, timeout) for r in due[offset:offset + 3]]
                    for future in as_completed(futures):
                        status["captures"].append(future.result())
            status["status"] = "completed"
        except Exception as exc:
            status.update(status="collector_error", error=f"{type(exc).__name__}: {exc}")
    try:
        status["results"] = collect_results(root, end)
    except Exception as exc:
        status["results"] = {"settled": 0, "errors": [f"{type(exc).__name__}: {exc}"]}
        status["status"] = "collector_error"
    summary = write_summary(root)
    status.update(finished_at=now_jst().isoformat(), pending_races=summary["pending_races"])
    core.write_report(root / "heartbeat.json", status)
    core.write_once(root / "coverage" / day / f"{now.strftime('%H%M%S')}_{os.getenv('GITHUB_RUN_ID', 'local')}.json", status)
    print(json.dumps({"status": status["status"], "captures": status["captures"],
                      "settled": status["results"]["settled"], "pending": summary["pending_races"]}, ensure_ascii=False))
    return 1 if status["status"] == "collector_error" else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--budget-seconds", type=int, default=125)
    parser.add_argument("--capture-one", nargs=4, metavar=("DAY", "JCD", "RNO", "DEADLINE"))
    parser.add_argument("--checkpoint-commit")
    args = parser.parse_args()
    if args.checkpoint_commit:
        print(json.dumps({"checkpoints_written": checkpoint(args.out, args.checkpoint_commit)}))
        return 0
    if args.capture_one:
        day, jcd, rno, deadline = args.capture_one
        try:
            print(json.dumps(capture_one(args.out, day, f"{int(jcd):02d}", int(rno), deadline), ensure_ascii=False))
            return 0
        except Exception as exc:
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
    return run(args.out, args.budget_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
