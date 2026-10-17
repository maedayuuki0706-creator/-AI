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


def progress(stage):
    # Fixed stage names only: never URLs, response bodies or Hiyori tokens.
    print(json.dumps({"capture_stage": stage, "at": now_jst().isoformat()}),
          file=sys.stderr, flush=True)


def _verify_original(record, key):
    if record.get("key") != key or record.get("digest") != core.digest(
            {k: v for k, v in record.items() if k != "digest"}):
        raise ValueError("Immutable prediction identity/digest mismatch")


def _eligible(day, deadline):
    now = now_jst()
    if now.strftime("%Y%m%d") != day or now >= core.cutoff(day, deadline) - timedelta(seconds=core.MIN_LEAD_SECONDS):
        raise ValueError("Capture cutoff closed; no generation or backfill")


def _observed(stage, function, *args):
    progress(stage + "_started")
    previous = sys.getprofile()
    def trace(frame, event, arg):
        if event not in {"call", "return"}:
            return
        module = frame.f_globals.get("__name__")
        name = frame.f_code.co_name
        label = None
        if module == "direct_discord_notify" and name == "fetch":
            # Only known endpoint labels; do not serialize request arguments.
            url = str(frame.f_locals.get("url", ""))
            label = next(("official_" + x for x in ("racelist", "beforeinfo", "odds3t")
                          if "/race/" + x + "?" in url), "official_get")
        elif module == "tide_context" and name == "_fetch":
            label = "tide_get"
        elif module == "hiyori_source" and name == "read":
            label = "hiyori_detail_request"
        if label:
            progress(label + ("_started" if event == "call" else "_returned"))
    sys.setprofile(trace)
    try:
        value = function(*args)
        progress(stage + "_ready")
        return value
    finally:
        sys.setprofile(previous)


def _strategy(model, families, **extra):
    return core.card(model.get("picks"), label=model.get("label"), families=families,
                     selection_policy=model.get("selection_policy"), **extra)


def build_live(day, jcd, rno, deadline):
    _eligible(day, deadline)
    progress("imports")
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
    progress("official_and_hiyori_fetch")
    # At most two source operations in ONE capture child. Preserve each native
    # parser/model; removing serial source waiting does not change coefficients.
    with ThreadPoolExecutor(max_workers=2) as pool:
        official_future = pool.submit(_observed, "official", official_source.analyze_official, day, jcd, rno)
        source_future = pool.submit(_observed, "hiyori", hiyori_source.fetch_race, day, jcd, rno)
        official = official_future.result()
        source = source_future.result()
    if not official or official.get("preview", {}).get("exhibition_count") != 6:
        raise ValueError("Live official/exhibition data are not ready")
    source["fetched_at"] = now_jst().isoformat()
    _eligible(day, deadline)
    progress("four_source_models")
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
    progress("comparison_bundle")
    bundle = trial.build_bundle({**request, "official": official}, hiyori, source, now=now_jst())
    progress("native_selectors")
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
                  "legacy_fusion_available": False,
                  "legacy_fusion_reason": "Original kyoteibiyori_adapter.race_model is explicitly not ready; real Hiyori model used instead.",
                  "learning": "Existing bridge policy retained; all_ai_learning is a report, not an independent engine.",
                  "delivery": "All native cards are rebuilt for research; they are not claims of delivered cards."}
    progress("fusion_prediction")
    record = core.build_prediction(request, analyses, strategies, now_jst(), context=context, provenance=provenance)
    snapshot = {"request": request, "analyses": analyses, "hiyori_source": source,
                "comparison_bundle": bundle, "featured_plan": featured_plan}
    return record, snapshot


def capture_one(out, day, jcd, rno, deadline):
    root = Path(out)
    key = core.identity(day, jcd, rno)
    prediction_path = root / "predictions" / day / f"{key}.json"
    if prediction_path.exists():
        _verify_original(load(prediction_path), key)
        return {"key": key, "status": "already_frozen"}
    _eligible(day, deadline)
    snapshot_path = root / "snapshots" / day / f"{key}.json.gz"
    if snapshot_path.exists():
        snapshot_bytes = snapshot_path.read_bytes()
        snapshot = json.loads(gzip.decompress(snapshot_bytes))
        record = snapshot.get("prediction_original")
        if not isinstance(record, dict):
            raise ValueError("Legacy orphan snapshot retained; prediction cannot be reconstructed")
        _verify_original(record, key)
        if record.get("day") != day or record.get("deadline") != deadline:
            raise ValueError("Orphan snapshot deadline mismatch")
        progress("recover_exact_original")
    else:
        record, snapshot = build_live(day, jcd, rno, deadline)
        _verify_original(record, key)
        # Crash recovery uses these exact bytes, never a newly calculated card.
        snapshot["prediction_original"] = deepcopy(record)
        snapshot_bytes = gzip.compress(json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                                   allow_nan=False).encode(), mtime=0)
        _eligible(day, deadline)
        if not core.write_once(snapshot_path, snapshot_bytes):
            raise ValueError("Concurrent snapshot publication; retry exact original")
    _eligible(day, deadline)
    record["provenance"]["snapshot_sha256"] = core.sha256(snapshot_bytes).hexdigest()
    record["digest"] = core.digest({k: v for k, v in record.items() if k != "digest"})
    stored = core.write_once(prediction_path, record)
    if not stored and load(prediction_path) != record:
        raise ValueError("Conflicting immutable prediction; overwrite refused")
    progress("original_saved_locally")
    return {"key": key, "status": "frozen" if stored else "already_frozen", "digest": record["digest"]}


def collect_card(root, day, only_venues=None):
    import direct_discord_notify as base
    path = Path(root) / "cards" / f"{day}.json"
    if path.exists():
        cached = load(path)
        scope = cached.get("requested_venues")
        covers = scope is None or (only_venues is not None and set(only_venues) <= set(scope))
        if covers and (now_jst() - core.aware(cached["observed_at"])).total_seconds() < 1800:
            return cached
    venues = base.discover_venues(day)
    if only_venues is not None:
        venues = [v for v in venues if v in only_venues]
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
    if only_venues is not None:
        value["requested_venues"] = sorted(only_venues)
        if set(only_venues) - set(venues):
            errors["requested_venue_not_discovered"] = sorted(set(only_venues) - set(venues))
    core.write_report(path, value)
    return value


def _capture_child(root, race, timeout):
    command = [sys.executable, str(Path(__file__).resolve()), "--out", str(Path(root).resolve()),
               "--capture-one", race["day"], race["jcd"], str(race["rno"]), race["deadline"]]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=max(1, timeout))
        stages = _stages(proc.stderr)
        if proc.returncode:
            return {"key": race["key"], "status": "waiting", "reason": proc.stderr.strip()[-600:], "stages": stages}
        return {**json.loads(proc.stdout.strip().splitlines()[-1]), "stages": stages}
    except subprocess.TimeoutExpired as exc:
        return {"key": race["key"], "status": "budget_exceeded", "timeout_seconds": timeout,
                "stages": _stages(exc.stderr), "reason": "capture_child_timeout_no_success_claim"}


def _stages(stderr):
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    values = []
    for line in (stderr or "").splitlines():
        try:
            value = json.loads(line)
            if set(value) == {"capture_stage", "at"}:
                values.append(value)
        except (ValueError, TypeError):
            pass
    return values[-20:]


def collect_results(root, end, max_fetch=None):
    import direct_discord_notify as base
    from daily_report import parse_payout
    root = Path(root)
    pending = []
    for path in sorted((root / "predictions").glob("*/*.json")):
        if (root / "evaluations" / path.parent.name / path.name).exists():
            continue
        record = load(path)
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
        pending.append((record, checkpoint))

    def fetch_result(record, checkpoint):
        url = base.official_url("raceresult", record["day"], record["jcd"], record["rno"])
        result_path = root / "results" / record["day"] / f"{record['key']}.json"
        if result_path.exists():
            result = load(result_path)
            if (result.get("key") != record["key"] or result.get("source_url") != url
                    or result.get("prediction_commit_sha") != checkpoint["commit_sha"]
                    or result.get("prediction_committed_at") != checkpoint["prediction_committed_at"]):
                raise ValueError("Saved result identity/checkpoint mismatch")
        else:
            result = parse_payout(base.fetch(url))
            result.update(key=record["key"], source_url=url, observed_at=now_jst().isoformat(),
                          prediction_committed_at=checkpoint["prediction_committed_at"],
                          prediction_commit_sha=checkpoint["commit_sha"])
        outcome = core.evaluate(record, result, now_jst())
        if outcome:
            outcome_path = root / "evaluations" / record["day"] / f"{record['key']}.json"
            if not core.write_once(result_path, result) and load(result_path) != result:
                raise ValueError("Conflicting immutable result")
            if not core.write_once(outcome_path, outcome) and load(outcome_path) != outcome:
                raise ValueError("Conflicting immutable evaluation")
        return record["key"], bool(outcome)

    settled, errors = 0, []
    # Batches prevent an old pending race from monopolizing this collector.
    pending = pending if max_fetch is None else pending[:max_fetch]
    for offset in range(0, len(pending), 2):
        if time.monotonic() >= end - 10:
            break
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(fetch_result, *pair) for pair in pending[offset:offset + 2]]
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
        record = load(path)
        _verify_original(record, record.get("key"))
        if receipt.exists():
            previous = load(receipt)
            if previous.get("key") != record["key"] or previous.get("prediction_digest") != record["digest"]:
                raise ValueError("Immutable checkpoint identity/digest mismatch")
            continue
        relative = path.relative_to(repository_root).as_posix()
        stored = subprocess.check_output(["git", "-C", str(repository_root), "show",
                                          f"{commit_sha}:{relative}"], text=True)
        if core.digest(json.loads(stored)) != core.digest(record):
            raise ValueError("Checkpoint must refer to the pushed prediction")
        snapshot_sha = record.get("provenance", {}).get("snapshot_sha256")
        if snapshot_sha:
            snapshot = root / "snapshots" / record["day"] / (record["key"] + ".json.gz")
            remote_snapshot = subprocess.check_output(["git", "-C", str(repository_root), "show",
                                                       f"{commit_sha}:{snapshot.relative_to(repository_root).as_posix()}"])
            if core.sha256(remote_snapshot).hexdigest() != snapshot_sha or snapshot.read_bytes() != remote_snapshot:
                raise ValueError("Remote snapshot does not match immutable prediction")
        value = {"key": record["key"], "prediction_digest": record["digest"],
                 "commit_sha": commit_sha, "prediction_committed_at": observed.isoformat(),
                 "snapshot_verified_at_remote_commit": bool(snapshot_sha),
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


def run(root, budget_seconds=85, *, only_venues=None, only_rnos=None, max_captures=1, skip_results=False):
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
            schedule = collect_card(root, day, only_venues=only_venues)
            due, missed = [], []
            for jcd, deadlines in schedule["venues"].items():
                if only_venues is not None and jcd not in only_venues:
                    continue
                for rno, deadline in enumerate(deadlines, 1):
                    if only_rnos is not None and rno not in only_rnos:
                        continue
                    key = core.identity(day, jcd, rno)
                    if (root / "predictions" / day / f"{key}.json").exists():
                        continue
                    lead = (core.cutoff(day, deadline) - now_jst()).total_seconds()
                    race = {"key": key, "day": day, "jcd": jcd, "rno": rno, "deadline": deadline}
                    if 300 <= lead <= 1800:
                        due.append(race)
                    elif lead < 300:
                        missed.append({**race, "status": "not_captured_before_window_closed"})
            due.sort(key=lambda r: (r["deadline"], r["jcd"], r["rno"]))
            status.update(due_races=len(due), missing_races=missed, schedule_errors=schedule["errors"])
            # One child, two source operations: below the previous three-child
            # network concurrency. A bounded pilot never expands to all venues.
            selected, deferred = due[:max_captures], due[max_captures:]
            status["captures"] += [{"key": r["key"], "status": "deferred_by_pilot_limit"} for r in deferred]
            for offset in range(len(selected)):
                if time.monotonic() >= end - 25:
                    status["captures"] += [{"key": r["key"], "status": "deferred_by_budget"} for r in selected[offset:]]
                    break
                timeout = min(55, end - time.monotonic() - 15)
                status["captures"].append(_capture_child(root, selected[offset], timeout))
            failures = [x for x in status["captures"] if x["status"] in {"waiting", "budget_exceeded", "deferred_by_budget"}]
            status["status"] = ("capture_incomplete" if failures or schedule["errors"] else
                                "completed" if selected else "no_due_races")
        except Exception as exc:
            status.update(status="collector_error", error=f"{type(exc).__name__}: {exc}")
    try:
        status["results"] = ({"settled": 0, "errors": [], "deferred_until_after_remote_save": True}
                             if skip_results else collect_results(root, end))
    except Exception as exc:
        status["results"] = {"settled": 0, "errors": [f"{type(exc).__name__}: {exc}"]}
        status["status"] = "collector_error"
    summary = write_summary(root)
    status.update(finished_at=now_jst().isoformat(), pending_races=summary["pending_races"])
    core.write_report(root / "heartbeat.json", status)
    core.write_once(root / "coverage" / day / f"{now.strftime('%H%M%S')}_{os.getenv('GITHUB_RUN_ID', 'local')}.json", status)
    print(json.dumps({"status": status["status"], "captures": status["captures"],
                      "settled": status["results"]["settled"], "pending": summary["pending_races"]}, ensure_ascii=False))
    return 1 if status["status"] in {"collector_error", "capture_incomplete"} else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--budget-seconds", type=int, default=85)
    parser.add_argument("--capture-one", nargs=4, metavar=("DAY", "JCD", "RNO", "DEADLINE"))
    parser.add_argument("--checkpoint-commit")
    parser.add_argument("--only-venues", nargs="+")
    parser.add_argument("--max-captures", type=int, default=1)
    parser.add_argument("--skip-results", action="store_true")
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
    if not 1 <= args.max_captures <= 3:
        parser.error("Research pilot permits 1-3 captures per invocation")
    if args.only_venues and not set(args.only_venues) <= {f"{i:02d}" for i in range(1, 25)}:
        parser.error("Invalid venue")
    return run(args.out, args.budget_seconds, only_venues=set(args.only_venues) if args.only_venues else None,
               max_captures=args.max_captures, skip_results=args.skip_results)


if __name__ == "__main__":
    raise SystemExit(main())
