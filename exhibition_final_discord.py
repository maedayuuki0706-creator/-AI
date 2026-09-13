"""Final-only Discord gate for serious all-race predictions.

This entry point disables the morning batch and waits for each race's complete
exhibition data plus current published trifecta odds before handing control to
the existing detailed notifier.
"""
from __future__ import annotations

import sys

import detailed_discord_notify as app

base = app.base
_original_analyze = base.analyze_official


def required_venue(policy, day, jcd):
    # Every venue discovered from today's official schedule is a prediction target.
    return True


def due_phase(policy, now, jcd, deadline, delivered, rno):
    # One final prediction per race only. No preliminary/morning predictions.
    day = now.strftime("%Y%m%d")
    lead = base.minutes_until(now, deadline)
    if lead < policy["final_min_lead_minutes"] or lead > policy["final_max_lead_minutes"]:
        return None
    return None if (day, jcd, rno, "final") in delivered else "final"


def analyze_after_exhibition(day, jcd, rno):
    analysis = _original_analyze(day, jcd, rno)
    if not analysis:
        return None
    preview = analysis.get("preview") or {}
    boats = analysis.get("inputs") or []
    if len(boats) != 6:
        return None
    reasons = []
    if preview.get("exhibition_count") != 6 or any(boat.get("exhibition_time") is None for boat in boats):
        reasons.append('展示6艇が未確認のため判断保留。')
    # Require a substantially complete live odds board rather than guessing.
    odds_count = sum(1 for row in analysis.get("trifecta", []) if row.get("odds") is not None)
    if odds_count < 100:
        reasons.append(f'公開オッズの確認待ち（{odds_count}/120通り）。')
    analysis['delivery_wait_reasons'] = reasons
    return analysis


class _NoMorningBatch:
    @staticmethod
    def run_once():
        return 0


def main():
    base.required_venue = required_venue
    base.due_phase = due_phase
    base.analyze_official = analyze_after_exhibition
    app.morning = _NoMorningBatch()
    return app.main()


if __name__ == "__main__":
    sys.exit(main())
