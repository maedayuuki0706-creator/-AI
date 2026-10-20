"""Independent 120-way trifecta ranking sidecar for research models.

Not a prediction generator. Scores from incomplete scenario evidence are
heuristic indices, not probabilities or expected values. No production I/O.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import json
import math
import os
from pathlib import Path

from research.scenario_v2 import engine as scenario

VERSION = "trifecta-120-index-research-v1"
JCD_NAMES = {"03": "江戸川くん", "06": "浜名湖くん",
             "16": "児島くん", "23": "唐津くん"}
TOP_BANDS = (1, 3, 5, 10, 20, 30, 60)
ALL = set(scenario.COMBINATIONS)


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Score must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Nonfinite score")
    return value


def _identity(record, kind):
    scenario.verify(record)
    if record.get("research_only") is False:
        raise ValueError("Production records are not a research sidecar input")
    if kind == "yuuki_v2":
        base = record
        code = str(base["meta"]["jcd"]).zfill(2)
        slug, name = "yuuki-v2", "新ゆうき"
        if not str(record.get("version", "")).startswith("yuuki-scenario-research-v2"):
            raise ValueError("Not a Yuuki scenario v2 record")
    elif kind == "venue_v1":
        base = record["common_v2"]
        scenario.verify(base)
        if record["common_v2_digest"] != base["digest"]:
            raise ValueError("Venue/common-v2 digest mismatch")
        code = str(record["jcd"]).zfill(2)
        if code not in JCD_NAMES or record.get("model") != JCD_NAMES[code]:
            raise ValueError("Invalid specialist venue/model")
        slug, name = "venue-v1-" + code, JCD_NAMES[code]
    elif kind == "venue_phase2":
        base = record
        code = str(base["meta"]["jcd"]).zfill(2)
        if code not in JCD_NAMES or record.get("venue_code") != code:
            raise ValueError("Invalid phase2 venue")
        variant = record.get("variant")
        if variant not in ("A", "B"):
            raise ValueError("Phase2 variant must be A or B")
        slug, name = "venue-phase2-" + code + "-" + variant, JCD_NAMES[code] + "-" + variant
    else:
        raise ValueError("Unknown research model kind")
    if code not in JCD_NAMES:
        raise ValueError("Not a four-venue research race")
    meta = base["meta"]
    expected = f'{meta["day"]}_{code}_{int(meta["rno"]):02d}'
    if meta.get("race_id") != expected:
        raise ValueError("Race identity mismatch")
    if kind == "venue_v1" and record.get("race_id") != expected:
        raise ValueError("Specialist race identity mismatch")
    if kind == "venue_phase2" and not str(record.get("version", "")).startswith("four-venue-phase2"):
        raise ValueError("Invalid phase2 model version")
    return base, meta, slug, name, code


def _scenario_evidence(base):
    evidence = defaultdict(list)
    for lane in base["lanes"]:
        for branch in lane["hypotheses"]:
            n = branch.get("supported_observations")
            if isinstance(n, bool) or not isinstance(n, int) or not (0 <= n <= 10):
                raise ValueError("Invalid pre-race supported observations")
            for formation in branch.get("formations", []):
                key = formation["combination"]
                if key not in ALL:
                    raise ValueError("Invalid tactical combination")
                evidence[key].append((str(branch["id"]), n))
    return evidence


def build_index(record, kind):
    """Build from an already frozen forecast; never reads a race result."""
    base, meta, slug, name, code = _identity(record, kind)
    scenario.reject_outcomes(record)
    evidence = _scenario_evidence(base)
    rows = []
    if kind == "venue_phase2":
        source = record["virtual_card"] + record["not_selected"]
        combos = [r["combination"] for r in source]
        if len(combos) != 120 or set(combos) != ALL:
            raise ValueError("Phase2 must supply exactly 120 native ranked combinations")
        for item in source:
            combo = item["combination"]
            rows.append({"combination": combo,
                         "raw_strength": _finite(item["historical_score"]),
                         "evidence_count": len(evidence.get(combo, [])),
                         "support_max": max((n for _, n in evidence.get(combo, [])), default=0),
                         "supporting_hypothesis_ids": sorted({i for i, _ in evidence.get(combo, [])})})
        # Preserve this venue-trained engine's native order, including variant B.
        score_kind = "native_phase2_historical_strength_uncalibrated"
        native_order = True
    else:
        audits = {int(x["lane"]): _finite(x["score"])
                  for x in record.get("lane_audits", [])} if kind == "venue_v1" else {}
        if kind == "venue_v1" and set(audits) != set(range(1, 7)):
            raise ValueError("Six venue audit scores required")
        for combo in sorted(ALL):
            hyps = evidence.get(combo, [])
            support = max((n for _, n in hyps), default=0)
            # Explicit, not-trained structural score. Repetition is diagnostic,
            # never an empirical hit frequency. No weight is called a probability.
            raw = 10.0 * support + min(len(hyps), 5)
            if audits:
                raw += audits[int(combo[0])]
            rows.append({"combination": combo, "raw_strength": round(raw, 8),
                         "evidence_count": len(hyps), "support_max": support,
                         "supporting_hypothesis_ids": sorted({i for i, _ in hyps})})
        rows.sort(key=lambda r: (-r["raw_strength"], r["combination"]))
        score_kind = "structural_pre_race_evidence_heuristic_uncalibrated"
        native_order = False

    assert len(rows) == 120 and {r["combination"] for r in rows} == ALL
    values = [r["raw_strength"] for r in rows]
    lo, hi = min(values), max(values)
    counts = {v: values.count(v) for v in set(values)}
    first_rank = {}
    for idx, row in enumerate(rows, 1):
        first_rank.setdefault(row["raw_strength"], idx)
        row["rank"] = idx
        row["index_0_100"] = round(100 * (row["raw_strength"] - lo) / (hi - lo), 4) if hi > lo else None
        row["tied_rank_start"] = first_rank[row["raw_strength"]]
        row["tied_count"] = counts[row["raw_strength"]]
        row["unscored_fallback"] = row["evidence_count"] == 0 if not native_order else False

    created = datetime.now(scenario.JST).isoformat()
    deadline = meta["deadline_at"]
    input_created = base.get("generated_at", record.get("created_at"))
    # A later report made from a historical forecast must never acquire a
    # fictitious earlier created_at or an automatic prospective receipt.
    out = {"version": VERSION, "research_only": True, "kind": kind,
           "model": name, "model_slug": slug, "venue_code": code,
           "race_id": meta["race_id"], "source_version": record["version"],
           "source_digest": record["digest"], "source_status": record.get("status", record.get("mode")),
           "source_generated_at": input_created, "source_captured_at": meta["captured_at"],
           "deadline_at": deadline, "index_generated_at": created,
           "source_generated_before_deadline": bool(input_created and
               scenario.aware(input_created) < scenario.aware(deadline)),
           "remote_predeadline_receipt_verified": False, "count_as_prospective": False,
           "score_kind": score_kind, "native_rank_preserved": native_order,
           "probabilities_calibrated": False, "expected_value_computed": False,
           "count": 120, "ranks": rows,
           "limitations": [
               "Rank 1..120 is relative ordering, NOT 1..120 percent likelihood.",
               "Index 0..100 is within-race relative strength, NOT hit probability or EV.",
               "Equal evidence scores use deterministic lexical tie-break; ranks inside ties are not evidence.",
               "Scenario-only outcomes without tactical formation are unscored fallbacks.",
               "Phase2 B native order may not be monotonic in historical_score because pre-race support is primary.",
               "A sidecar generated or saved after deadline is never retroactively a verified forecast.",
               "Only an independently verified pre-deadline remote receipt permits prospective evaluation.",
           ]}
    out["digest"] = scenario.digest(out)
    return out


def evaluate(index, official):
    """Separate result-stage assessment; does not change the frozen index."""
    scenario.verify(index)
    if index["version"] != VERSION or index["count"] != 120:
        raise ValueError("Unknown index version")
    ranks = index["ranks"]
    if len(ranks) != 120 or set(r["combination"] for r in ranks) != ALL or        [r["rank"] for r in ranks] != list(range(1, 121)):
        raise ValueError("Tampered 120-way ranking")
    if official.get("race_id") != index["race_id"]:
        raise ValueError("Result belongs to a different race")
    if scenario.aware(official["observed_at"]) < scenario.aware(index["deadline_at"]):
        raise ValueError("Result cannot be observed before deadline")
    valid = official.get("normal_verified") is True and official.get("refund_lanes") == []             and official.get("trifecta") in ALL
    result = {"version": VERSION + "-review", "race_id": index["race_id"],
              "model": index["model"], "index_digest": index["digest"],
              "result_digest": scenario.digest(official),
              "outcome": official.get("trifecta"), "evaluated_at": datetime.now(scenario.JST).isoformat(),
              "valid_normal_race": valid, "count_as_prospective": False}
    if valid:
        row = next(r for r in ranks if r["combination"] == official["trifecta"])
        result.update(actual_rank=row["rank"], actual_index_0_100=row["index_0_100"],
                      top_n_hit={str(n): row["rank"] <= n for n in TOP_BANDS},
                      actual_tie_size=row["tied_count"])
    else:
        result.update(actual_rank=None, actual_index_0_100=None, top_n_hit=None,
                      excluded_reason="Not a verified normal race, refund status unresolved or trifecta missing")
    result["digest"] = scenario.digest(result)
    return result


def save_once(document, destination):
    """Immutable independent JSON sidecar. Existing files can never be replaced."""
    destination = Path(destination)
    if destination.suffix != ".json":
        raise ValueError("JSON output required")
    scenario.verify(document)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as writer:
            json.dump(document, writer, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            writer.write("\n")
            writer.flush()
            os.fsync(writer.fileno())
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


def main():
    parser = argparse.ArgumentParser(description="Research-only offline 120-index sidecar")
    parser.add_argument("--kind", choices=["yuuki_v2", "venue_v1", "venue_phase2"])
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--official-result", type=Path)
    opts = parser.parse_args()
    record = json.loads(opts.record.read_text(encoding="utf-8"))
    if opts.official_result:
        index = record
        result = json.loads(opts.official_result.read_text(encoding="utf-8"))
        review = evaluate(index, result)
        path = opts.out_dir / "reviews" / index["model_slug"] / (index["race_id"] + ".json")
        save_once(review, path)
        print(json.dumps({"status": "local_review_only", "path": str(path),
                          "actual_rank": review["actual_rank"]}, ensure_ascii=False))
    else:
        if not opts.kind:
            parser.error("--kind required for index creation")
        index = build_index(record, opts.kind)
        path = opts.out_dir / "forecasts" / index["model_slug"] / (index["race_id"] + ".json")
        save_once(index, path)
        print(json.dumps({"status": "local_only_no_remote_receipt", "path": str(path),
                          "model": index["model"], "rank_count": index["count"]},
                         ensure_ascii=False))


if __name__ == "__main__":
    main()
