"""Read-only post-hoc replay of already-frozen fusion predictions.

No network, credentials, posting, production imports, or writes. Results are
used ONLY after deterministic ticket selection from the prediction snapshot.
Historical output is exploratory; it is not a prospective strategy result.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from hashlib import sha256
from itertools import permutations
import json
import math
from pathlib import Path

UNIT = 100
ALL_COMBOS = {"-".join(map(str, p)) for p in permutations(range(1, 7), 3)}
VARIANTS = ("fusion10", "existing10", "hiyori10", "fusion6", "fusion8",
            "fusion_ev100", "fusion_ev120", "skip_weak_ev")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def when(s: str) -> datetime:
    value = datetime.fromisoformat(s)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Missing timezone")
    return value


def check_unique(tickets: list) -> list[str]:
    if not isinstance(tickets, list) or len(set(tickets)) != len(tickets) or any(
        ticket not in ALL_COMBOS for ticket in tickets
    ):
        raise ValueError("Invalid or duplicate ticket")
    return tickets


def verify(key: str, record: dict, checkpoint: dict, result: dict, evaluation: dict) -> None:
    if any(value.get("key") != key for value in (record, checkpoint, result, evaluation)):
        raise ValueError("Mixed race identities")
    if record.get("mode") != "prospective_shadow" or not record.get("research_only"):
        raise ValueError("Not a frozen research prediction")
    content = {k: v for k, v in record.items() if k != "digest"}
    actual_hash = sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    if actual_hash != record.get("digest"):
        raise ValueError("Prediction tampered with")
    if checkpoint.get("prediction_digest") != actual_hash or not checkpoint.get("eligible_checkpoint"):
        raise ValueError("Unverified remote checkpoint")
    if evaluation.get("prediction_digest") != actual_hash:
        raise ValueError("Evaluation digest mismatch")
    saved = when(checkpoint["prediction_committed_at"])
    if not when(record["created_at"]) <= saved < when(record["deadline_at"]):
        raise ValueError("Prediction not fixed before deadline")
    if (result.get("prediction_commit_sha") != checkpoint.get("commit_sha") or
            when(result["prediction_committed_at"]) != saved):
        raise ValueError("Official result not bound to saved prediction")
    if when(result["observed_at"]) < when(record["deadline_at"]):
        raise ValueError("Result observed before the race deadline")
    if result.get("status") not in {"settled", "special", "void"}:
        raise ValueError("Unknown / pending official outcome")
    trifecta = record.get("trifecta") or []
    if len(trifecta) != 120 or {r.get("combination") for r in trifecta} != ALL_COMBOS:
        raise ValueError("Incomplete 120-combination pre-race probabilities")
    for r in trifecta:
        if r.get("expected_value") is not None and (
                type(r["expected_value"]) not in (int, float) or
                not math.isfinite(r["expected_value"]) or r["expected_value"] < 0):
            raise ValueError("Invalid frozen EV")
    for name in ("fusion", "control_existing_10", "control_hiyori_10"):
        check_unique(record["models"][name]["picks"])
    payouts = result.get("payouts") or {}
    if any(c not in ALL_COMBOS or not isinstance(v, int) or v <= 0 for c, v in payouts.items()):
        raise ValueError("Invalid official payout")
    if result["status"] == "settled" and not payouts:
        raise ValueError("Unsettled race marked settled")
    if any(str(l) not in {"1", "2", "3", "4", "5", "6"} for l in (result.get("refund_lanes") or [])):
        raise ValueError("Invalid refund lane")
    if result["status"] == "special" and (type(result.get("special_per_100")) is not int or
                                           result["special_per_100"] < 0):
        raise ValueError("Missing special payout")


def ticket_sets(record: dict) -> dict[str, list[str]]:
    fusion = check_unique(record["models"]["fusion"]["picks"])
    main = check_unique(record["models"]["fusion"]["main_picks"])
    if fusion[:6] != main or len(fusion) != 10 or len(main) != 6:
        raise ValueError("Unexpected frozen fusion ticket plan")
    lookup = {x["combination"]: x for x in record["trifecta"]}
    def filtered(floor: float) -> list[str]:
        return [t for t in fusion if lookup[t]["expected_value"] is not None and
                lookup[t]["expected_value"] >= floor]
    return {
        "fusion10": fusion,
        "existing10": check_unique(record["models"]["control_existing_10"]["picks"]),
        "hiyori10": check_unique(record["models"]["control_hiyori_10"]["picks"]),
        "fusion6": fusion[:6],
        "fusion8": fusion[:8],
        "fusion_ev100": filtered(1.0),
        "fusion_ev120": filtered(1.2),
        "skip_weak_ev": fusion if len(filtered(1.2)) >= 5 else [],
    }


def score(tickets: list[str], result: dict) -> dict:
    payouts = result.get("payouts") or {}
    refunded = {int(x) for x in result.get("refund_lanes") or []}
    returned, hit, cash_refund, highest = 0, False, 0, 0
    for ticket in tickets:
        if result["status"] == "void" or any(int(x) in refunded for x in ticket.split("-")):
            returned += UNIT
            cash_refund += UNIT
        elif result["status"] == "special":
            returned += result["special_per_100"]
        elif ticket in payouts:
            returned += payouts[ticket]
            highest = max(highest, payouts[ticket])
            hit = True
    stake = len(tickets) * UNIT
    return {"stake": stake, "returned": returned, "refund": cash_refund,
            "hit": hit, "active": result["status"] == "settled" and stake > cash_refund,
            "torigami": hit and returned < stake, "manshu": highest >= 10000}


def aggregate(root: Path) -> dict:
    if not (root / "predictions").is_dir():
        raise ValueError("Missing predictions directory: cannot report an empty replay")
    prediction_paths = sorted((root / "predictions").glob("*/*.json"))
    if not prediction_paths:
        raise ValueError("No prediction files: cannot report an empty replay")
    totals = {name: Counter() for name in VARIANTS}
    daily = {}
    skipped = Counter()
    for path in prediction_paths:
        key, day = path.stem, path.parent.name
        companions = [root / folder / day / path.name for folder in
                      ("checkpoints", "results", "evaluations")]
        if any(not x.is_file() for x in companions):
            skipped["missing_companion"] += 1
            continue
        try:
            record = read_json(path)
            checkpoint, result, evaluation = (read_json(x) for x in companions)
            verify(key, record, checkpoint, result, evaluation)
            selections = ticket_sets(record)
            baseline = score(selections["fusion10"], result)
            reported = evaluation["models"]["fusion"]
            if (baseline["stake"] != reported["stake_yen"] or
                    baseline["returned"] != reported["return_yen"] or
                    baseline["hit"] != reported["hit"]):
                raise ValueError("Official payout differs from original frozen evaluation")
            for name, picks in selections.items():
                row = score(picks, result)
                summary = totals[name]
                summary["races"] += 1
                summary["selected_races"] += bool(picks)
                summary["eligible_races"] += row["active"]
                summary["hits"] += row["hit"] and row["active"]
                summary["torigami"] += row["torigami"]
                summary["torigami_loss"] += max(0, row["stake"]-row["returned"]) if row["torigami"] else 0
                summary["manshu"] += row["manshu"]
                summary["stake_yen"] += row["stake"]
                summary["return_yen"] += row["returned"]
                summary["refund_yen"] += row["refund"]
                day_summary = daily.setdefault(day, {n: Counter() for n in VARIANTS})[name]
                day_summary.update({"races": 1, "eligible_races": int(row["active"]),
                    "selected_races": int(bool(picks)), "hits": int(row["hit"] and row["active"]),
                    "stake_yen": row["stake"], "return_yen": row["returned"]})
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            # A bad record is not silently counted as a losing race.
            skipped[type(exc).__name__+":"+str(exc)[:90]] += 1
    return {"label": "EXPLORATORY_REPLAY_NOT_PROSPECTIVE", "research_only": True,
            "source": str(root), "skipped": dict(skipped),
            "by_day": {day: {name: {**dict(s),
                        "roi_pct": round(100*s["return_yen"]/s["stake_yen"], 2)
                        if s["stake_yen"] else None,
                        "profit_yen": s["return_yen"]-s["stake_yen"]}
                        for name, s in models.items()} for day, models in daily.items()},
            "models": {name: {**dict(s), "hit_rate_pct": round(100*s["hits"]/s["eligible_races"],2)
                              if s["eligible_races"] else None,
                              "roi_pct": round(100*s["return_yen"]/s["stake_yen"],2)
                              if s["stake_yen"] else None,
                              "skip_rate_pct": round(100*(s["races"]-s["selected_races"])/s["races"],2)
                              if s["races"] else None,
                              "profit_yen": s["return_yen"] - s["stake_yen"]}
                       for name,s in totals.items()}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True,
                        help="LOCAL copy of research-fusion-shadow-state/data/fusion_shadow")
    args = parser.parse_args()
    print(json.dumps(aggregate(args.state_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

