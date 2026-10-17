"""Append-only availability, result comparison and daily research scoreboards.

No prediction generation, network access, spreadsheet writes or message sends.
Selection coverage is arithmetic; tactical causes require independent evidence.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timedelta
import io
import json
from pathlib import Path

from research.scenario_v2 import engine as scenario
from research.scenario_v2.collector import save_immutable
from .engine import VENUES, JST, digest
from .log_contract import SCHEMA, YUUKI, descriptor, read, validate_receipt

CATEGORIES = {
    "head_not_selected": "1着候補の選択ミス",
    "second_not_selected_given_head": "2着候補の選択ミス",
    "third_not_selected_given_head_and_second": "3着候補の選択ミス",
    "scenario_mismatch": "展開仮説の不一致",
    "data_insufficient": "データ不足",
    "exhibition_race_difference": "展示と本番の差異",
    "actual_tactics_unverified": "実際の戦術が確認できず判定不能",
}


def comparison(forecast, receipt, result):
    item = validate_receipt(forecast, receipt)
    key, picks = item["race_id"], item["picks"]
    if result.get("race_id") != key:
        raise ValueError("Official result belongs to another race")
    observed = result.get("observed_at")
    if not observed or scenario.aware(observed) < scenario.aware(item["deadline_at"]):
        raise ValueError("Result observation must be after deadline")
    payouts = result.get("payouts") or {}
    if any(c not in scenario.COMBINATIONS or isinstance(v, bool) or int(v) <= 0 for c, v in payouts.items()):
        raise ValueError("Invalid official trifecta payout")
    status = result.get("status")
    refunds = result.get("refund_lanes") or []
    if any(type(x) is not int or x not in range(1, 7) for x in refunds):
        raise ValueError("Invalid refund lanes")
    exclusion = ("incomplete_card" if not item["complete_card"] else
                 "refund" if refunds else status if status != "settled" else
                 "missing_payout" if not payouts else None)
    settled = exclusion is None
    winning = next(iter(payouts)).split("-") if len(payouts) == 1 else None
    head = {p.split("-")[0] for p in picks}
    pairs = {"-".join(p.split("-")[:2]) for p in picks}
    second = {p.split("-")[1] for p in picks}
    third = {p.split("-")[2] for p in picks}
    selection = None
    if winning and settled:
        combo = "-".join(winning)
        selection = ("hit" if combo in picks else "head_not_selected" if winning[0] not in head else
                     "second_not_selected_given_head" if "-".join(winning[:2]) not in pairs else
                     "third_not_selected_given_head_and_second")
    findings = [{"category": "actual_tactics_unverified", "classification": CATEGORIES["actual_tactics_unverified"],
                 "status": "unverified", "evidence": "No independently reviewed video/turn trajectories",
                 "causal_failure_proven": False}]
    if selection in CATEGORIES:
        findings.append({"category": selection, "classification": CATEGORIES[selection],
                         "status": "selection_difference_only", "evidence": sorted(payouts),
                         "causal_failure_proven": False})
    if any(x["fields"] for x in item["missing_fields"]):
        findings.append({"category": "data_insufficient", "classification": CATEGORIES["data_insufficient"],
                         "status": "input_limitation_not_proven_cause", "evidence": item["missing_fields"],
                         "causal_failure_proven": False})
    common = forecast if "meta" in forecast else forecast["common_v2"]
    details = result.get("details") or {}
    entrants = {x["lane"]: x["racer_id"] for x in common["lanes"]}
    finish = details.get("finish") or []
    if any(x.get("racer_id") and str(x["racer_id"]) != str(entrants.get(x.get("lane"))) for x in finish):
        raise ValueError("Official result entrant differs from forecast")
    entry_changes, st_changes = [], []
    by_lane = {x.get("lane"): x for x in finish}
    for lane in common["lanes"]:
        actual = by_lane.get(lane["lane"], {})
        if actual.get("course") is not None and actual["course"] != lane["predicted_course"]:
            entry_changes.append(lane["lane"])
        ex = lane.get("evidence", {}).get("exhibition_st")
        if ex is not None and actual.get("st") is not None:
            st_changes.append({"lane": lane["lane"], "exhibition_st": ex, "actual_st": actual["st"],
                               "difference_seconds": round(actual["st"] - ex, 5)})
    if entry_changes or st_changes:
        findings.append({"category": "exhibition_race_difference", "classification": CATEGORIES["exhibition_race_difference"],
                         "status": "observed_difference_not_proven_cause", "evidence": {
                             "entry_changed_lanes": entry_changes, "st_differences": st_changes},
                         "causal_failure_proven": False})
    method = details.get("method")
    method_covered = None
    if winning and method:
        winner = next(x for x in common["lanes"] if str(x["lane"]) == winning[0])
        method_covered = method in {h["tactic"] for h in winner["hypotheses"]}
        if not method_covered:
            findings.append({"category": "scenario_mismatch", "classification": CATEGORIES["scenario_mismatch"],
                             "status": "winner_method_only_other_turns_unverified", "evidence": method,
                             "causal_failure_proven": False})
    returned_tickets = [p for p in picks if set(map(int, p.split("-"))) & set(refunds)]
    cash_refund = len(returned_tickets) * 100 if refunds else len(picks) * 100 if status == "void" else 0
    returned = sum(int(v) for c, v in payouts.items() if c in picks) if settled else None
    out = {"schema": SCHEMA, **{k: item[k] for k in ("race_id", "ai_id", "day", "jcd", "venue", "version", "selection_policy")},
           "forecast_digest": forecast["digest"], "result_digest": digest(result), "code_sha": item["code_sha"],
           "confirmed_commit_sha": receipt["commit_sha"], "official_source_url": result.get("source_url"),
           "status": "graded" if settled else "excluded", "exclusion_reason": exclusion,
           "official_status": status, "refund_lanes": refunds,
           "official_trifectas": payouts, "selection": selection,
           "stake_yen": 1000 if settled else None, "return_yen": returned,
           "hit": any(c in picks for c in payouts) if settled else None,
           "roi_pct": round(returned / 10, 2) if returned is not None else None,
           "main_head_correct": str(picks[0][0]) == winning[0] if settled and winning else None,
           "selected_head_covered": winning[0] in head if settled and winning else None,
           "second_selected": winning[1] in second if settled and winning else None,
           "third_selected": winning[2] in third if settled and winning else None,
           "second_selected_given_head": "-".join(winning[:2]) in pairs if settled and winning and winning[0] in head else None,
           "third_selected_given_head_second": "-".join(winning) in picks if settled and winning and "-".join(winning[:2]) in pairs else None,
           "refund_cash_yen_excluded_from_comparison": cash_refund,
           "official_winner_method": method, "winner_method_in_hypotheses": method_covered,
           "actual_tactics_verified": False, "findings": findings,
           "unverifiable": ["Each boat's actual tactics/turn trajectory", "Causal reason for losing"],
           "rate_note": "Second/third membership is unconditional; prefix-conditioned rates have separate denominators"}
    out["digest"] = digest(out)
    return out


def inventory(root):
    """Newest observed schedule per day and venue; failures never become zero races."""
    expected, schedules, errors = {}, {}, {}
    for path in sorted((Path(root) / "schedules").glob("20*/*.json")):
        row = read(path)
        day = row["day"]
        for error in row.get("errors", []):
            errors[(day, error["venue"])] = error
        for code, times in row.get("schedules", {}).items():
            schedules[(day, code)] = times
            errors.pop((day, code), None)
    for (day, code), times in schedules.items():
        for rno, hhmm in enumerate(times, 1):
            key = f"{day}_{code}_{rno:02}"
            expected[key] = datetime.strptime(day + " " + hhmm, "%Y%m%d %H:%M").replace(tzinfo=JST)
    return expected, schedules, errors


def _reason(root, key, ai, forecast, receipt):
    if forecast and receipt:
        return "receipt_invalid_or_late"
    if forecast:
        return "remote_receipt_missing"
    if ai == YUUKI:
        partial = read(Path(root) / "yuuki/partial_reasons" / key[:8] / (key + ".json"))
        if partial:
            return partial["reason"]
        return "no_yuuki_forecast_or_frozen_baseline_saved"
    attempts = [read(p) for p in (Path(root) / "attempts" / key[:8]).glob(key + "_*.json")]
    if attempts:
        return attempts[-1].get("reason", "capture_failed")
    return "no_capture_attempt_recorded_cause_not_proven"


def _row(day, code, ai, scheduled, known, error):
    return {"day": day, "jcd": code, "venue": VENUES[code]["venue"], "ai_id": ai,
            "target_races": scheduled, "schedule_verified": known, "schedule_error": error,
            "predeadline_saved": 0, "automatic_saved": 0, "rescued_saved": 0,
            "missing": 0, "upcoming": 0, "invalid_originals": 0, "partial_scenarios": 0,
            "graded": 0, "hits": 0, "virtual_stake_yen": 0, "virtual_return_yen": 0,
            "result_pending": 0, "refund_races": 0, "void_races": 0, "data_insufficient_races": 0,
            "other_excluded_races": 0, "main_head_hits": 0, "main_head_n": 0,
            "second_selected_hits": 0, "second_selected_n": 0, "third_selected_hits": 0, "third_selected_n": 0,
            "conditional_second_hits": 0, "conditional_second_n": 0,
            "conditional_third_hits": 0, "conditional_third_n": 0,
            "selection_errors": {}, "findings": {}, "missing_reasons": {}, "model_versions": []}


def _finish(row):
    pct = lambda n, d: round(100 * n / d, 2) if d else None
    closed = row["predeadline_saved"] + row["missing"]
    row.update(save_rate_pct=pct(row["predeadline_saved"], closed), missing_rate_pct=pct(row["missing"], closed),
               hit_rate_pct=pct(row["hits"], row["graded"]), roi_pct=pct(row["virtual_return_yen"], row["virtual_stake_yen"]),
               main_head_accuracy_pct=pct(row["main_head_hits"], row["main_head_n"]),
               second_selected_rate_pct=pct(row["second_selected_hits"], row["second_selected_n"]),
               third_selected_rate_pct=pct(row["third_selected_hits"], row["third_selected_n"]),
               second_given_head_rate_pct=pct(row["conditional_second_hits"], row["conditional_second_n"]),
               third_given_pair_rate_pct=pct(row["conditional_third_hits"], row["conditional_third_n"]))
    return row


def build_report(root, *, now):
    root = Path(root)
    expected, schedules, errors = inventory(root)
    today = now.strftime("%Y%m%d")
    days = sorted(d for d in ({d for d, _ in schedules} | {d for d, _ in errors}) if d <= today)
    rows, events, experiments = {}, [], {}
    for day in days:
        for code, venue in VENUES.items():
            if day < venue["first_day"]:
                continue
            for ai in ("venue_" + code, YUUKI):
                rows[(day, code, ai)] = _row(day, code, ai, len(schedules.get((day, code), [])),
                                            (day, code) in schedules, errors.get((day, code)))
    for key, deadline in sorted(expected.items()):
        day, code, _ = key.split("_")
        if day > today:
            continue
        result = read(root / "results" / day / (key + ".json"))
        for ai, base in (("venue_" + code, root), (YUUKI, root / "yuuki")):
            row = rows[(day, code, ai)]
            f = read(base / "forecasts" / day / (key + ".json"))
            rec = read(base / "receipts" / day / (key + ".json"))
            if ai == YUUKI and (base / "partial_scenarios" / day / (key + ".json")).is_file():
                row["partial_scenarios"] += 1
            valid, reason = False, None
            if f:
                try:
                    item = validate_receipt(f, rec, read(base / "inputs" / day / (key + ".json")))
                    if item["race_id"] != key or not item["complete_card"]:
                        raise ValueError("Incomplete or mismatched original")
                    valid = True
                except (ValueError, KeyError, TypeError) as exc:
                    row["invalid_originals"] += 1
                    reason = str(exc)[:200]
            if valid:
                experiment_id = '|'.join(str(x or 'unknown') for x in (ai, code, item['version'], item['selection_policy'], item['code_sha']))
                experiment = experiments.setdefault(experiment_id, {
                    'ai_id': ai, 'jcd': code, 'version': item['version'], 'selection_policy': item['selection_policy'],
                    'code_sha': item['code_sha'], 'saved_records': 0, 'graded': 0, 'hits': 0,
                    'virtual_stake_yen': 0, 'virtual_return_yen': 0,
                    'scope_note': 'Saved-record cohort only; missing races cannot be assigned a retrospective code version'})
                experiment['saved_records'] += 1
                row["predeadline_saved"] += 1
                rescued = rec.get("origin") == "genuine_local_capture_preserved_without_regeneration"
                row["rescued_saved" if rescued else "automatic_saved"] += 1
                if item["version"] not in row["model_versions"]:
                    row["model_versions"].append(item["version"])
                if result:
                    analysis = comparison(f, rec, result)
                    dest = root / "phase1/analyses" / ai / day / (key + "_" + analysis["digest"] + ".json")
                    save_immutable(dest, analysis)
                    if analysis["status"] == "graded":
                        experiment['graded'] += 1
                        experiment['hits'] += int(analysis['hit'])
                        experiment['virtual_stake_yen'] += analysis['stake_yen']
                        experiment['virtual_return_yen'] += analysis['return_yen']
                        row["graded"] += 1
                        row["hits"] += int(analysis["hit"])
                        row["virtual_stake_yen"] += analysis["stake_yen"]
                        row["virtual_return_yen"] += analysis["return_yen"]
                        for field, label in (("main_head_correct", "main_head"), ("second_selected", "second_selected"),
                                             ("third_selected", "third_selected"), ("second_selected_given_head", "conditional_second"),
                                             ("third_selected_given_head_second", "conditional_third")):
                            if analysis[field] is not None:
                                row[label + "_n"] += 1
                                row[label + "_hits"] += int(analysis[field])
                        sel = analysis["selection"]
                        if sel in CATEGORIES:
                            row["selection_errors"][sel] = row["selection_errors"].get(sel, 0) + 1
                    else:
                        cat = analysis["exclusion_reason"]
                        column = "refund_races" if cat == "refund" else "void_races" if cat == "void" else "data_insufficient_races" if cat in ("missing_payout", "incomplete_card") else "other_excluded_races"
                        row[column] += 1
                    for finding in analysis["findings"]:
                        cat = finding["category"]
                        row["findings"][cat] = row["findings"].get(cat, 0) + 1
                else:
                    row["result_pending"] += 1
            elif now >= deadline:
                row["missing"] += 1
                reason = reason or _reason(root, key, ai, f, rec)
                row["missing_reasons"][reason] = row["missing_reasons"].get(reason, 0) + 1
                event = {"schema": SCHEMA, "race_id": key, "ai_id": ai, "deadline_at": deadline.isoformat(),
                         "detected_at": now.isoformat(), "status": "missing", "reason": reason,
                         "backfill_forecast_forbidden": True,
                         "schedule_source": "immutable_official_schedule_inventory"}
                dest = root / "phase1/missing" / ai / day / (key + ".json")
                if not dest.exists():
                    save_immutable(dest, event)
                first_event = read(dest)
                events.append({**first_event, "first_detection_reason": first_event["reason"], "reason": reason})
            else:
                row["upcoming"] += 1
    daily = [_finish(row) for row in rows.values()]
    # Aggregate from exact daily rows; do not combine cumulative numerators with
    # single-day availability, and retain denominators for every percentage.
    grouped = {}
    for row in daily:
        for grouping, identity in (("ai", row["ai_id"]), ("venue", row["jcd"]), ("day", row["day"]),
                                   ("ai_venue", row["ai_id"] + ":" + row["jcd"])):
            out = grouped.setdefault((grouping, identity), {"grouping": grouping, "id": identity})
            for k, v in row.items():
                if type(v) is int:
                    out[k] = out.get(k, 0) + v
                elif k in ("findings", "selection_errors", "missing_reasons"):
                    out[k] = dict(Counter(out.get(k, {})) + Counter(v))
    aggregates = [_finish(x) for x in grouped.values()]
    streak = []
    cursor = now.date() - timedelta(days=1)
    for _ in range(7):
        day = cursor.strftime("%Y%m%d")
        relevant = [r for r in daily if r["day"] == day]
        if not relevant or any(not r["schedule_verified"] or r["schedule_error"] or r["upcoming"] for r in relevant):
            break
        observed = [r for r in relevant if r["target_races"]]
        if not observed or any((r["save_rate_pct"] or 0) < 95 for r in observed):
            break
        streak.append(day)
        cursor -= timedelta(days=1)
    report = {"schema": SCHEMA, "through_day": today, "research_only": True,
              "scope": "Existing four-venue collector pilot; new Yuuki is evaluated on the same race set, not all 24 venues",
              "budget": {"points": 10, "unit_yen": 100, "incomplete_cards_excluded": True},
              "daily_ai_venue": daily, "aggregates": aggregates,
              "by_experiment": list(experiments.values()),
              "missing_races": [{k: e[k] for k in ("race_id", "ai_id", "reason")} for e in events],
              "seven_day_gate": {"required_daily_save_rate_pct": 95, "required_days": 7,
                                  "closed_complete_consecutive_days": list(reversed(streak)),
                                  "achieved": len(streak) >= 7,
                                  "all_active_ai_each_day_required": True,
                                  "current_day_not_counted_before_close": True},
              "failure_categories": CATEGORIES,
              "causal_warning": "Selection errors and observed input differences are not proven causes; unreviewed tactics remain unknown"}
    report["digest"] = digest(report)
    return report


def save_report(root, *, now):
    report = build_report(root, now=now)
    folder = Path(root) / "phase1/reports" / report["through_day"]
    base = folder / report["digest"]
    save_immutable(base.with_suffix(".json"), report)
    columns = ["day", "ai_id", "venue", "target_races", "predeadline_saved", "automatic_saved", "rescued_saved", "missing",
               "missing_rate_pct", "partial_scenarios", "graded", "hits", "hit_rate_pct", "virtual_stake_yen", "virtual_return_yen",
               "roi_pct", "main_head_accuracy_pct", "second_selected_rate_pct", "third_selected_rate_pct", "refund_races", "void_races",
               "data_insufficient_races", "result_pending", "findings", "selection_errors"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in report["daily_ai_venue"]:
        writer.writerow({k: json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, dict) else v for k, v in row.items()})
    csv_path = base.with_suffix(".csv")
    if not csv_path.exists():
        # Derived, deterministic export; never overwrite a previously published report.
        with csv_path.open("x", encoding="utf-8-sig", newline="") as out:
            out.write(stream.getvalue())
    return {"report_path": str(base.with_suffix(".json")), "digest": report["digest"],
            "daily": report["daily_ai_venue"], "seven_day_gate": report["seven_day_gate"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(json.dumps(save_report(args.out, now=datetime.now(JST)), ensure_ascii=False))


if __name__ == "__main__":
    main()
