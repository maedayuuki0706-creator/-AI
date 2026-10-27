"""Two-phase offline replay. Build all forecasts before opening outcome files."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import csv
import json
from pathlib import Path
import subprocess

from .adapters import from_fusion
from .engine import JST, POLICY, aware, digest, generate, review, verify
from .run import write_once
from research.scenario_v1.scenario_research_v1 import generate as generate_v1


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_git_source(repo, record, checkpoint):
    sha = checkpoint["commit_sha"]
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("Invalid checkpoint commit SHA")
    rel = f"data/fusion_shadow/predictions/{record['day']}/{record['key']}.json"
    committed = json.loads(subprocess.check_output(["git", "-C", str(repo), "show", f"{sha}:{rel}"]))
    verify(committed)
    if committed["digest"] != record["digest"]:
        raise ValueError("Saved source differs from pre-deadline Git object")
    when = subprocess.check_output(["git", "-C", str(repo), "show", "-s", "--format=%cI", sha], text=True).strip()
    # Git commit dates have whole-second precision; source JSON retains microseconds.
    if not aware(record["created_at"]).replace(microsecond=0) <= aware(when) < aware(record["deadline_at"]):
        raise ValueError("Git checkpoint commit not in the pre-race time window")


def build(root, out, repo):
    root, out = Path(root), Path(out)
    protocol = {"version": "scenario-v2-replay-protocol-1", "created_at": datetime.now(JST).isoformat(),
                "policy": POLICY, "mode": "retrospective_replay", "tuning_on_results": False,
                "known_context": "Existing aggregate results and a small case sample were known during design. No unseen holdout claim.",
                "normalization_revision": "-1/0 timing sentinels remain missing; Git dates compared at one-second precision. After the first evaluation, missing finishes were relabelled incomplete_finish instead of claiming an accident. No selection or membership changed.",
                "source_root": str(root), "git_source_verification": True,
                "code_hashes": {p.name: digest(p.read_text()) for p in Path(__file__).parent.glob("*.py")}}
    protocol["digest"] = digest(protocol)
    write_once(out/"protocol.json", protocol)
    receipts, rejected = [], []
    for path in sorted((root/"predictions").glob("*/*.json")):
        try:
            record = load(path)
            cp = load(root/"checkpoints"/path.parent.name/path.name)
            verify_git_source(repo, record, cp)
            data = from_fusion(record, cp)
            forecast = generate(data, mode="replay")
            write_once(out/"forecasts"/path.parent.name/path.name, forecast)
            receipts.append({"race_id": record["key"], "forecast_digest": forecast["digest"],
                             "source_digest": record["digest"], "source_commit": cp["commit_sha"]})
        except (ValueError, KeyError, TypeError, FileNotFoundError, subprocess.CalledProcessError) as exc:
            rejected.append({"file": path.name, "reason": str(exc)})
    receipt = {"status": "build_complete", "completed_at": datetime.now(JST).isoformat(),
               "protocol_digest": protocol["digest"], "forecast_count": len(receipts),
               "forecasts": receipts, "rejected": rejected}
    receipt["digest"] = digest(receipt)
    write_once(out/"build_receipt.json", receipt)
    return {"forecasts": len(receipts), "rejected": rejected}


def result_from_files(source, evaluation, exhibition_root):
    official = evaluation["official_result"]
    if evaluation.get("prediction_digest") != source["digest"]:
        raise ValueError("Evaluation/source digest mismatch")
    payouts = official.get("payouts") or {}
    status = official.get("status")
    observed = official.get("observed_at") or evaluation.get("evaluated_at")
    r = {"race_id": source["key"], "status": status, "observed_at": observed,
         "refund_lanes": official.get("refund_lanes") or [], "source_url": official.get("source_url")}
    if status != "settled" or r["refund_lanes"]:
        return r
    if len(payouts) != 1:
        return {**r, "status": "special"}
    r["trifecta"], r["payout_per_100"] = next(iter(payouts.items()))
    path = Path(exhibition_root)/source["day"]/f"{source['jcd']}_{int(source['rno']):02}.json"
    r["winning_method"] = (official.get("race_details") or {}).get("method")
    if path.exists():
        raw = load(path)
        if str(raw.get("day")) != source["day"] or int(raw.get("jcd")) != int(source["jcd"]) or int(raw.get("rno")) != int(source["rno"]):
            raise ValueError("Enriched exhibition identity mismatch")
        update = raw.get("settled_at") or raw.get("updated_at")
        if raw.get("settled") and update and aware(update) >= aware(source["deadline_at"]):
            rows = raw.get("rows", [])
            if any(not str(b.get("finish", "")).isdigit() for b in rows):
                return {**r, "status": "incomplete_finish",
                        "details_missing_reason": "A missing finish may be an abnormal result or a parse/data gap; do not infer an accident"}
            if len(rows) == 6:
                r["boats"] = [{"lane": b["lane"], "racer_id": b.get("racer_id"), "finish": b["finish"],
                               "actual_course": b.get("actual_course"), "actual_st": b.get("actual_st")} for b in rows]
                methods = {b.get("method") for b in rows if b.get("method")}
                if len(methods) > 1 or (methods and r["winning_method"] and r["winning_method"] not in methods):
                    raise ValueError("Conflicting winner methods")
                if methods:
                    r["winning_method"] = next(iter(methods))
                r["details_source"] = "Post-race enriched official exhibition log; never used in generation"
                r["details_observed_at"] = update
    if r["winning_method"] == "恵まれ":
        r["status"] = "accident"
    return r


def score(picks, result):
    return {"races": 1, "hits": int(result["trifecta"] in picks), "stake_yen": len(picks)*100,
            "return_yen": result["payout_per_100"] if result["trifecta"] in picks else 0}


def evaluate(root, out, exhibition_root):
    root, out = Path(root), Path(out)
    receipt = load(out/"build_receipt.json"); verify(receipt)
    protocol = load(out/"protocol.json"); verify(protocol)
    if protocol["digest"] != receipt["protocol_digest"]:
        raise ValueError("Protocol/build mismatch")
    current = {p.name: digest(p.read_text()) for p in Path(__file__).parent.glob("*.py")}
    if current != protocol["code_hashes"]:
        raise ValueError("Code changed after build; use a new versioned replay directory")
    totals, groups, excluded, races, boat_rows = {}, {}, [], [], []
    for item in receipt["forecasts"]:
        key = item["race_id"]; day = key[:8]
        f = load(out/"forecasts"/day/(key+".json")); verify(f)
        if f["digest"] != item["forecast_digest"]:
            raise ValueError("Forecast changed after build receipt")
        source = load(root/"predictions"/day/(key+".json")); verify(source)
        if source["digest"] != item["source_digest"]:
            raise ValueError("Source changed after build")
        evaluation = load(root/"evaluations"/day/(key+".json"))
        try:
            result = result_from_files(source, evaluation, exhibition_root)
            report = review(f, result)
        except (ValueError, TypeError, KeyError) as exc:
            excluded.append({"race_id": key, "reason": str(exc)}); continue
        write_once(out/"reviews"/day/(key+".json"), report)
        if report["status"] == "excluded":
            excluded.append({"race_id": key, "reason": report["reason"]}); continue
        v1 = generate_v1({"inputs": source["pre_race_boats"], "preview": source["pre_race_weather"]},
                         {"day": day, "jcd": source["jcd"], "rno": source["rno"],
                          "deadline": source["deadline"], "captured_at": source["created_at"]})
        v1_candidates = {c for l in v1["lanes"] for h in l["hypotheses"] for c in h["possible_trifectas"]}
        cards = {"new_yuuki_frozen_10": source["models"]["fusion"]["picks"],
                 "existing_frozen_10": source["models"]["control_existing_10"]["picks"],
                 "hiyori_frozen_10": source["models"]["control_hiyori_10"]["picks"],
                 "scenario_v2_replay_10": f["virtual_card"]["picks"]}
        weather = f["environment"]
        wind = weather.get("wind_speed")
        wind_band = "unknown" if wind is None else "0-3" if float(wind) <= 3 else "4-5" if float(wind) <= 5 else "6+"
        stat = {name: score(picks, result) for name, picks in cards.items()}
        for name, value in stat.items():
            for bucket in [totals, groups.setdefault("day:"+day, {}), groups.setdefault("venue:"+str(source.get("venue")), {}),
                           groups.setdefault("wind:"+wind_band, {}), groups.setdefault("method:"+str(result.get("winning_method")), {})]:
                sums = bucket.setdefault(name, Counter()); sums.update(value)
        row = {"race_id": key, "day": day, "venue": source.get("venue"), "actual": result["trifecta"],
               "winning_method": result.get("winning_method"), "wind_mps": wind,
               "wave_cm": weather.get("wave_cm"), "entry_changed": bool(report["entry_changed_lanes"]),
               "entry_verified": report["entry_verified"], "selection_error": report["selection_error"],
               "method_and_formation_covered": report["method_and_formation_covered"],
               "v1_candidate_count": len(v1_candidates), "v1_covered": result["trifecta"] in v1_candidates,
               "v2_candidate_count": f["formation_candidate_count"], "v2_covered": report["formation_covered"],
               "source_commit": item["source_commit"], "forecast_digest": f["digest"],
               "changed_ticket_count": len(set(cards["scenario_v2_replay_10"])-set(cards["new_yuuki_frozen_10"])),
               **{name+"_hit": v["hits"] for name, v in stat.items()},
               **{name+"_return_yen": v["return_yen"] for name, v in stat.items()}}
        races.append(row)
        for lane in report["lanes"]:
            pre = next(x for x in f["lanes"] if x["lane"] == lane["lane"])
            boat_rows.append({"race_id": key, "day": day, "venue": source.get("venue"), "lane": lane["lane"],
                              "racer_id": pre["racer_id"], "predicted_course": pre["predicted_course"],
                              "win_paths": json.dumps(lane["pre_win_paths"], ensure_ascii=False),
                              "loss_paths": json.dumps(lane["pre_loss_paths"], ensure_ascii=False),
                              "attack_origins": json.dumps([{ "tactic": h["tactic"], "origin_lane": h["attack_origin_lane"]} for h in pre["hypotheses"]], ensure_ascii=False),
                              "actual_finish": lane["actual_finish"], "winner_method": result.get("winning_method") if lane["winner"] else None,
                              "condition_checks": json.dumps(lane["condition_checks"], ensure_ascii=False),
                              "loss_cause": lane["loss_cause"], "missing_fields": "/".join(pre["missing_fields"]),
                              "forecast_digest": f["digest"], "result_source": result.get("source_url")})
    def rates(bucket):
        return {name: {**dict(v), "hit_rate_pct": 100*v["hits"]/v["races"],
                       "roi_pct": 100*v["return_yen"]/v["stake_yen"]} for name, v in bucket.items()}
    summary = {"status": "complete", "mode": "retrospective_replay", "protocol_digest": protocol["digest"],
               "built_forecasts": receipt["forecast_count"], "source_rejected": receipt["rejected"],
               "normal_paired_races": len(races), "excluded": excluded, "models": rates(totals),
               "groups": {k: rates(v) for k, v in groups.items()},
               "selection_errors": dict(Counter(r["selection_error"] for r in races)),
               "entry_verified_races": sum(r["entry_verified"] for r in races),
               "entry_changed_races": sum(r["entry_changed"] for r in races),
               "v1_formation_covered": sum(r["v1_covered"] for r in races),
               "v2_formation_covered": sum(r["v2_covered"] for r in races),
               "method_formation_assessable": sum(r["method_and_formation_covered"] is not None for r in races),
               "method_formation_covered": sum(r["method_and_formation_covered"] is True for r in races),
               "same_entry_method_formation_assessable": sum(r["entry_verified"] and not r["entry_changed"] and r["method_and_formation_covered"] is not None for r in races),
               "same_entry_method_formation_covered": sum(r["entry_verified"] and not r["entry_changed"] and r["method_and_formation_covered"] is True for r in races),
               "mean_v1_candidates": sum(r["v1_candidate_count"] for r in races)/len(races) if races else None,
               "mean_v2_candidates": sum(r["v2_candidate_count"] for r in races)/len(races) if races else None,
               "boat_log_rows": len(boat_rows), "prospective_v2_races": 0, "video_verified_races": 0,
               "note": "Source data were frozen before the races; the v2 predictions were created later. No claim of prospective gain or calibrated EV."}
    write_once(out/"summary.json", summary)
    for name, rows in [("race_log.csv", races), ("boat_log.csv", boat_rows)]:
        with (out/name).open("x", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["race_id"])
            writer.writeheader(); writer.writerows(rows)
    return {k: summary[k] for k in ["normal_paired_races", "excluded", "models", "boat_log_rows"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["build", "evaluate"])
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--repository")
    parser.add_argument("--exhibition-root")
    args = parser.parse_args()
    if args.action == "build" and not args.repository:
        parser.error("build requires --repository for read-only Git checkpoint verification")
    if args.action == "evaluate" and not args.exhibition_root:
        parser.error("evaluate requires --exhibition-root for post-race evidence")
    value = build(args.source_root, args.out, args.repository) if args.action == "build" else evaluate(args.source_root, args.out, args.exhibition_root)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
