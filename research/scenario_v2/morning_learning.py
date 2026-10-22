"""Morning-study evidence gate for new Yuuki research. Never changes production predictions."""
from __future__ import annotations
from datetime import datetime
from math import isfinite

TOPICS = frozenset({"course", "exhibition_st", "motor", "weather_tide", "tactic",
                    "second_third", "odds_ev", "racer", "f_stability", "current_form"})
OUTCOME_FIELDS = frozenset({"result", "payout", "winning_method", "actual_st",
                            "actual_course", "finish", "settled"})

def apply_morning_learning(forecast: dict, studies: list[dict], *, as_of: str) -> dict:
    """Attach verifiable research evidence to Yuuki's frozen scenario, without invented coefficients.

    The caller must supply a pre-race forecast. Observational research is annotated,
    never used as a numerical prediction weight until prospective validation passes.
    """
    import copy
    at = datetime.fromisoformat(as_of)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    output = copy.deepcopy(forecast)
    accepted, excluded = [], []
    for study in studies:
        topic = study.get("topic")
        if topic not in TOPICS:
            excluded.append({"id": study.get("id"), "reason": "unknown_topic"})
            continue
        if any(k in study for k in OUTCOME_FIELDS):
            excluded.append({"id": study.get("id"), "reason": "outcome_leakage"})
            continue
        try:
            published = datetime.fromisoformat(study["published_at"])
            if published.tzinfo is None or published.utcoffset() is None or published > at:
                raise ValueError("future_or_naive_timestamp")
        except (KeyError, ValueError, TypeError):
            excluded.append({"id": study.get("id"), "reason": "invalid_publication_time"})
            continue
        if not study.get("source_url") or not study.get("method") or not study.get("sample_description"):
            excluded.append({"id": study.get("id"), "reason": "missing_provenance"})
            continue
        if study.get("promotional_picks") or study.get("future_data_used"):
            excluded.append({"id": study.get("id"), "reason": "unsuitable_evidence"})
            continue
        status = study.get("validation_status", "unvalidated")
        if status not in ("unvalidated", "out_of_sample_validated"):
            excluded.append({"id": study.get("id"), "reason": "invalid_validation_status"})
            continue
        gain = study.get("out_of_sample_gain")
        if status == "out_of_sample_validated" and (not isinstance(gain, (int, float)) or isinstance(gain, bool) or not isfinite(gain)):
            excluded.append({"id": study.get("id"), "reason": "missing_validation_metric"})
            continue
        accepted.append({"id": study.get("id"), "topic": topic,
                         "source_url": study["source_url"], "method": study["method"],
                         "sample_description": study["sample_description"],
                         "validation_status": status, "out_of_sample_gain": gain})
    output["morning_learning"] = {
        "applied_as_of": as_of, "accepted": accepted, "excluded": excluded,
        "prediction_weights_changed": False,
        "note": "Research annotations only. No calibrated coefficient or ROI claim."
    }
    return output
