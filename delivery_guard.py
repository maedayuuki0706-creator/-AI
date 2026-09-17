"""Last-chance delivery guard for Boat AI Navi.

The normal path still waits for all six exhibition records.  If the official
exhibition parser/data is still incomplete five minutes before the deadline,
we build one final prediction from all currently available official inputs
instead of silently letting the race expire.

The fallback is deliberately marked and is never eligible for the selected
mid-odds feed.  It exists to prevent a missing race, not to pretend incomplete
exhibition data is complete.
"""
from __future__ import annotations

from datetime import datetime


_FALLBACK_META = {}


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _insert_warning(message: str, actual_count: int) -> str:
    warning = (
        f"⚠️ **締切直前フォールバック｜展示 {actual_count}/6艇**\n"
        "展示データが締切直前まで揃わなかったため、取得済みの公式データで最終予想を配信。"
    )
    lines = str(message).splitlines()
    insert_at = 1 if lines else 0
    lines[insert_at:insert_at] = [warning]
    text = "\n".join(lines)
    # Control flow uses a synthetic 6/6 marker. Never show that synthetic value.
    text = text.replace("展示 6/6艇", f"展示 {actual_count}/6艇（取得不完全）")
    return text


def install(app, opportunity_module, full_analyze):
    """Install after notification_runner has installed its normal wrappers."""
    if getattr(app, "_delivery_guard_installed", False):
        return

    original_analyze = app.base.analyze_official
    original_message = app.analysis_message_with_virtual
    original_log = app.log_prediction_with_virtual
    original_opp_message = opportunity_module._message
    original_opp_score = opportunity_module._score
    original_opp_build = opportunity_module._build_payload
    original_is_selected_mid = opportunity_module._is_selected_mid

    def guarded_analyze(day, jcd, rno):
        analysis = original_analyze(day, jcd, rno)
        if not isinstance(analysis, dict):
            return analysis
        preview = analysis.get("preview") or {}
        actual_count = int(preview.get("exhibition_count") or 0)
        if actual_count >= 6:
            return analysis

        try:
            times = app.base.deadlines(day, jcd)
            deadline = times[int(rno) - 1]
            now = datetime.now(app.base.JST)
            lead = app.base.minutes_until(now, deadline)
            policy = app.base.load_policy()
            minimum = _num(policy.get("final_min_lead_minutes"), 1.0)
            fallback_lead = _num(policy.get("fallback_incomplete_exhibition_lead_minutes"), 5.0)
        except Exception:
            return analysis

        if lead < minimum or lead > fallback_lead:
            return analysis

        # The fast waiting path intentionally skips expensive odds/model work.
        # At the final guard window, run the complete analysis once.
        try:
            full = full_analyze(day, jcd, rno)
        except Exception:
            full = None
        if not isinstance(full, dict) or not (full.get("trifecta") or []):
            return analysis

        actual_count = int((full.get("preview") or {}).get("exhibition_count") or 0)
        if actual_count >= 6:
            return full

        guarded = dict(full)
        guarded_preview = dict(full.get("preview") or {})
        guarded["_delivery_guard_fallback"] = True
        guarded["_delivery_guard_exhibition_count"] = actual_count
        # direct_discord_notify waits whenever this value is < 6.  Set only the
        # control-flow copy to 6 and preserve the real count above for display/logs.
        guarded_preview["exhibition_count"] = 6
        guarded["preview"] = guarded_preview
        return guarded

    def guarded_opp_score(analysis, picks, kind):
        if analysis.get("_delivery_guard_fallback"):
            honest = dict(analysis)
            preview = dict(analysis.get("preview") or {})
            preview["exhibition_count"] = int(analysis.get("_delivery_guard_exhibition_count") or 0)
            honest["preview"] = preview
            return original_opp_score(honest, picks, kind)
        return original_opp_score(analysis, picks, kind)

    def guarded_opp_message(venue, rno, deadline, analysis, picks, kind, score, breakdown):
        text = original_opp_message(venue, rno, deadline, analysis, picks, kind, score, breakdown)
        if analysis.get("_delivery_guard_fallback"):
            return _insert_warning(text, int(analysis.get("_delivery_guard_exhibition_count") or 0))
        return text

    def guarded_opp_build(venue, rno, deadline, analysis, kind):
        payload = original_opp_build(venue, rno, deadline, analysis, kind)
        if analysis.get("_delivery_guard_fallback"):
            payload = dict(payload)
            payload["delivery_fallback"] = True
            payload["fallback_exhibition_count"] = int(analysis.get("_delivery_guard_exhibition_count") or 0)
        return payload

    def guarded_is_selected_mid(payload):
        # Incomplete exhibition may be useful as a last-chance normal card, but
        # it must never be promoted to a dedicated selected/value alert.
        if payload.get("delivery_fallback"):
            return False
        return original_is_selected_mid(payload)

    def guarded_message(day, jcd, rno, deadline, phase, analysis, rows, required):
        fallback = bool(analysis.get("_delivery_guard_fallback"))
        actual_count = int(analysis.get("_delivery_guard_exhibition_count") or 0)
        if fallback:
            _FALLBACK_META[(str(day), str(jcd), int(rno), str(phase))] = actual_count
        text = original_message(day, jcd, rno, deadline, phase, analysis, rows, required)
        return _insert_warning(text, actual_count) if fallback else text

    def guarded_log(record):
        key = (
            str(record.get("day")),
            str(record.get("jcd")),
            int(record.get("rno") or 0),
            str(record.get("phase") or "final"),
        )
        actual_count = _FALLBACK_META.pop(key, None)
        if actual_count is not None:
            record = dict(record)
            record["exhibition"] = False
            record["delivery_fallback"] = True
            record["fallback_exhibition_count"] = int(actual_count)
        return original_log(record)

    app.base.analyze_official = guarded_analyze
    app.analysis_message_with_virtual = guarded_message
    app.log_prediction_with_virtual = guarded_log
    opportunity_module._score = guarded_opp_score
    opportunity_module._message = guarded_opp_message
    opportunity_module._build_payload = guarded_opp_build
    opportunity_module._is_selected_mid = guarded_is_selected_mid
    app._delivery_guard_installed = True
