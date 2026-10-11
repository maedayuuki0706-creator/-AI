"""Observable X-post volume, acknowledgement integrity and cost estimates.

All amounts are ESTIMATES based on durable, acknowledged X post IDs, not the
authoritative credit balance or invoice. Rejected and uncertain API calls may
incur charges that cannot be established from our receipt ledger alone.
"""
from __future__ import annotations

from .limits import (
    MAX_DAILY_X_PREDICTIONS,
    MAX_RESULTS_PER_PREDICTION,
    STANDARD_POST_CREATE_USD,
)


def daily_usage(state: dict) -> dict:
    prediction_ids = {
        race: str(post_id)
        for race, post_id in (state.get("x_post_ids") or {}).items()
        if str(post_id).isdigit()
    }
    result_ids = {
        race: str(post_id)
        for race, post_id in (state.get("x_result_post_ids") or {}).items()
        if str(post_id).isdigit()
    }
    total = len(prediction_ids) + len(result_ids)
    receipts = state.get("x_v2_receipts") or {}
    unresolved = [
        key for key, receipt in receipts.items()
        if receipt.get("status") in {"sending", "uncertain"}
    ]
    orphan_results = sorted(set(result_ids) - set(prediction_ids))
    alerts = []
    if len(prediction_ids) > MAX_DAILY_X_PREDICTIONS:
        alerts.append("prediction_cap_exceeded")
    if len(result_ids) > MAX_DAILY_X_PREDICTIONS * MAX_RESULTS_PER_PREDICTION:
        alerts.append("result_cap_exceeded")
    if orphan_results:
        alerts.append("result_missing_prediction")
    if unresolved:
        alerts.append("unresolved_api_attempts")
    estimated = round(total * STANDARD_POST_CREATE_USD, 3)
    full_day = round(
        MAX_DAILY_X_PREDICTIONS * (1 + MAX_RESULTS_PER_PREDICTION)
        * STANDARD_POST_CREATE_USD, 3
    )
    if estimated >= full_day * 0.8:
        alerts.append("near_full_daily_post_cost")
    return {
        "prediction_limit": MAX_DAILY_X_PREDICTIONS,
        "confirmed_predictions": len(prediction_ids),
        "confirmed_results": len(result_ids),
        "confirmed_post_total": total,
        "results_pending_or_unconfirmed": len(set(prediction_ids) - set(result_ids)),
        "remaining_prediction_slots": max(0, MAX_DAILY_X_PREDICTIONS - len(prediction_ids)),
        "result_without_prediction_count": len(orphan_results),
        "unresolved_api_attempt_count": len(unresolved),
        "estimated_confirmed_posts_cost_usd": estimated,
        "standard_post_create_unit_usd": STANDARD_POST_CREATE_USD,
        "full_day_cost_estimate_usd": full_day,
        "full_30_days_cost_estimate_usd": round(full_day * 30, 2),
        "cost_estimate_only_not_x_invoice": True,
        "alerts": alerts,
    }
