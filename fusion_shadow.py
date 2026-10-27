"""Frozen, prospective all-AI fusion. Pure scoring/storage; no delivery APIs."""
from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from itertools import permutations
import json
from math import isfinite
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo
import fusion_shadow_scenarios as scenarios

JST = ZoneInfo("Asia/Tokyo")
VERSION = "new-yuuki-fusion-shadow-v2"
STATE_BRANCH = "research-fusion-shadow-state"
WEIGHTS = {"existing": .20, "sheet_db": .25, "knowledge_v2": .05, "hiyori": .50}
POINTS, UNIT_YEN, MIN_LEAD_SECONDS = 10, 100, 180
COMBINATIONS = frozenset("-".join(map(str, p)) for p in permutations(range(1, 7), 3))
CURRENT_OUTCOME_FIELDS = {"finish", "actual_st", "actual_course", "payout", "result"}


def aware(value):
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("A timezone-aware timestamp is required")
    return result.astimezone(JST)


def identity(day, jcd, rno):
    datetime.strptime(day, "%Y%m%d")
    if not 1 <= int(jcd) <= 24 or not 1 <= int(rno) <= 12:
        raise ValueError("Invalid race identity")
    return f"{day}_{int(jcd):02d}_{int(rno):02d}"


def cutoff(day, deadline):
    return datetime.strptime(f"{day} {deadline}", "%Y%m%d %H:%M").replace(tzinfo=JST)


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def distribution(rows):
    values = {}
    for row in rows:
        combo = row.get("combination")
        if combo not in COMBINATIONS or combo in values:
            raise ValueError("Invalid or duplicate trifecta")
        probability = float(row["probability"])
        if not isfinite(probability) or probability < 0:
            raise ValueError("Invalid probability")
        values[combo] = probability
    total = sum(values.values())
    if set(values) != COMBINATIONS or not isfinite(total) or total <= 0:
        raise ValueError("All 120 trifectas are required")
    return {c: values[c] / total for c in sorted(values)}


def picks(values):
    out = []
    for item in values or []:
        combo = item.get("combination") if isinstance(item, dict) else item
        if combo not in COMBINATIONS:
            raise ValueError("Invalid ticket")
        if combo not in out:
            out.append(combo)
    return out


def card(values, **extra):
    tickets = picks(values)
    return {"picks": tickets, "point_count": len(tickets),
            "stake_yen": len(tickets) * UNIT_YEN, **extra}


def _entrants(analysis):
    boats = analysis.get("inputs") or []
    lanes = [int(b["lane"]) for b in boats]
    if len(boats) != 6 or set(lanes) != set(range(1, 7)):
        raise ValueError("Six unique current entrants are required")
    if any(not str(b.get("racer_id") or "") for b in boats):
        raise ValueError("Current racer identities are required")
    if any(b.get(k) is not None for b in boats for k in CURRENT_OUTCOME_FIELDS):
        raise ValueError("Current-race outcome data cannot enter a prediction")
    return sorted((int(b["lane"]), str(b["racer_id"])) for b in boats)


def validate_capture(request, analyses, now):
    now = aware(now)
    day, deadline = request["day"], request["deadline"]
    identity(day, request["jcd"], request["rno"])
    captured, fetched = aware(request["captured_at"]), aware(request["source_fetched_at"])
    if now.strftime("%Y%m%d") != day or captured.strftime("%Y%m%d") != day:
        raise ValueError("Only today's live predictions are eligible")
    if not captured <= fetched <= now or (now - captured).total_seconds() > 180:
        raise ValueError("Sources must be recent and precede creation")
    if now > cutoff(day, deadline) - timedelta(seconds=MIN_LEAD_SECONDS):
        raise ValueError("Too late to freeze a prospective prediction")
    if request.get("settled"):
        raise ValueError("The race is already settled")
    if set(analyses) != set(WEIGHTS):
        raise ValueError("All four probability sources are mandatory; no silent fallback")
    official = analyses["existing"]
    expected = _entrants(official)
    if official.get("preview", {}).get("exhibition_count") != 6:
        raise ValueError("Six live exhibition records are required")
    for analysis in analyses.values():
        if _entrants(analysis) != expected:
            raise ValueError("Sources refer to different current entrants")
        distribution(analysis.get("trifecta") or [])
    if not any(f.get("used") for f in analyses["hiyori"].get("features", [])):
        raise ValueError("Actual Hiyori inputs are required")
    database = analyses["sheet_db"].get("sheet_database") or {}
    if not database.get("enabled") or not database.get("snapshot_at"):
        raise ValueError("A dated PT2 database snapshot is required")
    if aware(database["snapshot_at"]) > captured:
        raise ValueError("A future database snapshot cannot enter a prediction")
    return now


def rank_fusion(analyses, strategies, odds, context=None):
    """Correlated policy cards share one capped support bit per family."""
    probs = {name: distribution(a["trifecta"]) for name, a in analyses.items()}
    if set(probs) != set(WEIGHTS):
        raise ValueError("Missing fusion source")
    support = {"official": set(), "hiyori": set()}
    for strategy in strategies.values():
        families = strategy.get("families") or []
        if any(f not in support for f in families):
            raise ValueError("Unknown source family")
        for family in families:
            support[family].update(picks(strategy.get("picks")))
    upset = bool(context and "イン敗北警戒" in context.get("types", []))
    followers = bool(context and "ヒモ荒れ警戒" in context.get("types", []))
    rows = []
    for combo in sorted(COMBINATIONS):
        probability = sum(WEIGHTS[name] * probs[name][combo] for name in WEIGHTS)
        agreement = .10 * sum(combo in support[f] for f in support)
        odd = odds.get(combo)
        if odd is not None:
            odd = float(odd)
            if not isfinite(odd) or odd <= 0:
                odd = None
        ev = probability * odd if odd is not None else None
        score = probability * (1 + agreement)
        # Small, frozen modifiers; no outside-head bonus when the venue gate suppresses it.
        warning_bonus = .05 if upset and not combo.startswith("1-") else 0
        warning_bonus += .03 if followers and combo.startswith("1-") and any(
            lane in ("5", "6") for lane in combo.split("-")[1:]) else 0
        value_factor = max(.90, min(1.10, ev)) if ev is not None else 1.0
        rows.append({"combination": combo, "probability": probability, "odds": odd,
                     "expected_value": ev, "rank_score": score,
                     "cover_score": score * value_factor * (1 + warning_bonus),
                     "support_families": [f for f in support if combo in support[f]],
                     "context_bonus": warning_bonus})
    rows.sort(key=lambda r: (-r["rank_score"], r["combination"]))
    main = [r["combination"] for r in rows[:6]]
    cover_rows = sorted((r for r in rows if r["combination"] not in main),
                        key=lambda r: (-r["cover_score"], r["combination"]))
    cover = [r["combination"] for r in cover_rows[:4]]
    return rows, card(main + cover, main_picks=main, cover_picks=cover,
                      label="全AI融合・10点", selection_policy="family-capped-main6-cover4")


def build_prediction(request, analyses, strategies, now, *, context=None, provenance=None):
    now = validate_capture(request, analyses, now)
    odds = {r["combination"]: r.get("odds") for r in analyses["existing"]["trifecta"]}
    if context is not None:
        if context.get("key") != identity(request["day"], request["jcd"], request["rno"]):
            raise ValueError("Research context race mismatch")
        if not aware(request["captured_at"]) <= aware(context["observed_at"]) <= now:
            raise ValueError("Research context must come from this live capture")
        if context.get("outcome") is not None:
            raise ValueError("Settled research context is forbidden")
    rows, fusion = rank_fusion(analyses, strategies, odds, context)
    rows, main, cover, boat_scenarios, ticket_reasons = scenarios.rank(analyses, rows, context)
    fusion = card(main + cover, main_picks=main, cover_picks=cover,
                  label="新ゆうき・6艇展開融合10点", selection_policy=scenarios.VERSION)
    comparisons = {"fusion": fusion}
    # Same 1,000-yen budget and probability-only selector, alongside variable native policies.
    for name, analysis in analyses.items():
        prob = distribution(analysis["trifecta"])
        comparisons[f"control_{name}_10"] = card(
            sorted(prob, key=lambda c: (-prob[c], c))[:POINTS],
            label=f"{name}・同額10点", comparison_group="equal_budget")
    for name, strategy in strategies.items():
        comparisons[f"native_{name}"] = card(strategy.get("picks"),
            label=strategy.get("label", name), comparison_group="native_variable_budget",
            selected=strategy.get("selected"), families=strategy.get("families"),
            selection_policy=strategy.get("selection_policy"))
    official = analyses["existing"]
    record = {"version": VERSION, "mode": "prospective_shadow", "research_only": True,
              "key": identity(request["day"], request["jcd"], request["rno"]),
              "day": request["day"], "jcd": f"{int(request['jcd']):02d}", "rno": int(request["rno"]),
              "venue": official.get("venue"), "deadline": request["deadline"],
              "deadline_at": cutoff(request["day"], request["deadline"]).isoformat(),
              "captured_at": aware(request["captured_at"]).isoformat(),
              "source_fetched_at": aware(request["source_fetched_at"]).isoformat(),
              "created_at": now.isoformat(), "code_sha": os.getenv("GITHUB_SHA"),
              "weights": dict(WEIGHTS), "unit_yen": UNIT_YEN,
              "probabilities_are_calibrated": False,
              "scenario_version": scenarios.VERSION, "boat_scenarios": boat_scenarios,
              "head_probabilities": {str(s["lane"]): s["head_probability"] for s in boat_scenarios},
              "ticket_reasons": ticket_reasons,
              "scenario_coefficients_are_calibrated": False,
              "pre_race_boats": official["inputs"], "pre_race_weather": official.get("preview"),
              "source_versions": {name: a.get("model_version") for name, a in analyses.items()},
              "input_hashes": {name: digest(a) for name, a in analyses.items()},
              "database": analyses["sheet_db"]["sheet_database"],
              "hiyori_features": analyses["hiyori"]["features"],
              "research_context": context, "context_available": context is not None,
              "strategies": strategies, "models": comparisons, "trifecta": rows,
              "provenance": provenance or {}}
    record["digest"] = digest(record)
    return record


def write_once(path, payload):
    """Atomic complete write and exclusive publish; never replace an existing forecast."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = payload if isinstance(payload, bytes) else (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pending-", delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp_path, path)
        return True
    except FileExistsError:
        return False
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def write_report(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".report-", delete=False) as stream:
        temp_path = Path(stream.name)
        stream.write((json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp_path, path)


def _verify_record(record):
    unsigned = {k: v for k, v in record.items() if k != "digest"}
    if record.get("digest") != digest(unsigned):
        raise ValueError("Prediction digest mismatch")


def evaluate(record, result, now):
    _verify_record(record)
    now = aware(now)
    deadline = aware(record["deadline_at"])
    # A local file alone is not proof that a prediction was durably saved before the race.
    frozen_at = aware(result["prediction_committed_at"])
    if not aware(record["created_at"]) <= frozen_at < deadline:
        raise ValueError("No durable pre-deadline prediction checkpoint")
    if now < deadline + timedelta(minutes=3) or result.get("key") != record["key"]:
        raise ValueError("Result timing or identity mismatch")
    if aware(result["observed_at"]) > now or aware(result["observed_at"]) < deadline:
        raise ValueError("Result observation must follow the deadline")
    status = result.get("status")
    if status not in {"settled", "void", "special"}:
        return None
    payouts = result.get("payouts") or {}
    if any(c not in COMBINATIONS or not isinstance(v, int) or v <= 0 for c, v in payouts.items()):
        raise ValueError("Invalid official trifecta payout")
    if status == "settled" and not payouts:
        return None
    refunds = {int(lane) for lane in result.get("refund_lanes") or []}
    if not refunds <= set(range(1, 7)):
        raise ValueError("Unknown refund lanes")
    special = result.get("special_per_100")
    if status == "special" and (not isinstance(special, int) or special <= 0):
        raise ValueError("Unknown special payout")
    models = {}
    for name, model in record["models"].items():
        tickets = picks(model["picks"])
        returned, refund_yen, active, winners = 0, 0, [], []
        for ticket in tickets:
            if status == "void" or refunds.intersection(map(int, ticket.split("-"))):
                returned += UNIT_YEN
                refund_yen += UNIT_YEN
            else:
                active.append(ticket)
                if status == "special":
                    returned += special
                elif ticket in payouts:
                    returned += payouts[ticket]
                    winners.append(ticket)
        models[name] = {"stake_yen": len(tickets) * UNIT_YEN, "return_yen": returned,
                        "refund_yen": refund_yen, "net_stake_yen": len(active) * UNIT_YEN,
                        "hit": bool(winners), "winning_picks": winners,
                        "eligible_race": status == "settled" and bool(active),
                        "manshu_hit": any(payouts[t] >= 10000 for t in winners)}
    return {"version": record["version"], "mode": record["mode"], "key": record["key"],
            "day": record["day"], "venue": record.get("venue"),
            "prediction_digest": record["digest"], "prediction_committed_at": frozen_at.isoformat(),
            "official_result": result, "evaluated_at": now.isoformat(), "models": models,
            "scenario_review": scenarios.evaluate_hypotheses(record, result) if record.get("boat_scenarios") else None}


def summarize(root):
    root = Path(root)
    totals, per_day, pending, late, other_engines = {}, {}, 0, 0, 0
    for path in sorted((root / "predictions").glob("*/*.json")):
        record = json.loads(path.read_text())
        if record.get("mode") != "prospective_shadow":
            continue
        if record.get("version") != VERSION:
            other_engines += 1
            continue
        result_path = root / "evaluations" / record["day"] / path.name
        if not result_path.exists():
            pending += 1
            continue
        outcome = json.loads(result_path.read_text())
        if outcome.get("excluded_reason"):
            late += 1
            continue
        if outcome.get("prediction_digest") != record["digest"]:
            raise ValueError("Evaluation refers to a different prediction")
        for name, score in outcome["models"].items():
            for bucket in (totals, per_day.setdefault(record["day"], {})):
                item = bucket.setdefault(name, {"recorded_races": 0, "eligible_races": 0,
                                               "hits": 0, "manshu_hits": 0,
                                               "stake_yen": 0, "return_yen": 0, "refund_yen": 0})
                item["recorded_races"] += 1
                item["eligible_races"] += int(score["eligible_race"])
                item["hits"] += int(score["hit"] and score["eligible_race"])
                item["manshu_hits"] += int(score["manshu_hit"] and score["eligible_race"])
                for field in ("stake_yen", "return_yen", "refund_yen"):
                    item[field] += score[field]
    for bucket in [totals, *per_day.values()]:
        for item in bucket.values():
            item["hit_rate_pct"] = 100 * item["hits"] / item["eligible_races"] if item["eligible_races"] else None
            item["roi_pct"] = 100 * item["return_yen"] / item["stake_yen"] if item["stake_yen"] else None
    return {"version": VERSION, "mode": "prospective_shadow", "research_only": True,
            "pending_races": pending, "excluded_late_checkpoint_races": late,
            "excluded_other_engine_races": other_engines,
            "models": totals, "by_day": per_day,
            "note": "Native policy cards have different budgets. Compare equal-budget controls separately."}
