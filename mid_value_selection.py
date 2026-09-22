"""Evidence-first value policy for the 中穴 feed.

The rule is intentionally *not* "odds are split, therefore buy the favourite".
Prediction evidence comes first. Price/popularity is consulted only after a
combination already has enough model probability and EV support.

Two changes are additive:
1. Allow a small 6-12x value-favourite window when probability + EV are strong.
2. Make selected-mid a genuinely strict layer: fewer deliveries are preferred
   over weak selections. The selected feed must clear compactness, confidence,
   scenario-mass and EV gates together.

Longshot logic is untouched.
"""
from __future__ import annotations


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _ev(row):
    value = row.get("expected_value")
    if value is not None:
        return _num(value)
    odds = _num(row.get("odds"))
    probability = _num(row.get("probability"))
    return odds * probability if odds > 0 and probability > 0 else 0.0


def install(opportunity_alerts_module):
    if getattr(opportunity_alerts_module, "_mid_value_selection_installed", False):
        return

    original_candidate_rows = opportunity_alerts_module._candidate_rows

    def candidate_rows(analysis, kind):
        rows = list(original_candidate_rows(analysis, kind))
        if kind != "mid":
            return rows

        # Do not add short-priced combinations merely because the market is split.
        # A 6-12x candidate is admitted only when the model already likes the exact
        # combination and the offered price still clears a positive-EV threshold.
        seen = {str(row.get("combination") or "") for row in rows}
        for source in analysis.get("trifecta") or []:
            combo = str(source.get("combination") or "")
            if not combo or combo in seen:
                continue
            odds = _num(source.get("odds"))
            probability = _num(source.get("probability"))
            ev = _ev(source)
            if not (6.0 <= odds < 12.0):
                continue
            if probability < 0.018 or ev < 1.05:
                continue

            item = dict(source)
            item["_quality"] = (
                probability
                * (0.75 + min(ev, 2.8))
                * (1.0 + min(odds, 80.0) / 220.0)
            )
            item["_value_favourite"] = True
            rows.append(item)
            seen.add(combo)

        rows.sort(
            key=lambda row: (
                _num(row.get("_quality")),
                _ev(row),
                _num(row.get("probability")),
            ),
            reverse=True,
        )
        return rows

    def is_selected_mid(payload):
        """Strict selected-mid gate.

        2026-09-23 policy:
        - Prefer no alert to a weak alert.
        - Maximum 10 tickets.
        - Do not inherit the old score>=75 / EV>=1.05 automatic pass.
        - Require one of three evidence-backed routes below.

        This is intentionally stricter than the normal 中穴 feed. The goal is to
        make 厳選くん a small, actionable subset rather than another broad feed.
        """
        picks = list(payload.get("picks") or [])
        if not picks or len(picks) > 10:
            return False

        score = int(payload.get("score") or 0)
        best_ev = max((_ev(row) for row in picks), default=0.0)
        scenario_mass = sum(_num(row.get("probability")) for row in picks)
        composite = _num(payload.get("composite_odds"), 0.0)

        # A: genuinely high-confidence and compact.
        high_confidence = (
            score >= 82
            and best_ev >= 1.18
            and scenario_mass >= 0.14
            and composite >= 2.8
        )

        # B: slightly lower confidence is allowed only when the value case is
        # substantially stronger and the ticket set is tighter.
        strong_value = (
            score >= 78
            and len(picks) <= 9
            and best_ev >= 1.30
            and scenario_mass >= 0.12
            and composite >= 3.2
        )

        # C: exceptional EV can rescue a marginal score, but only with a very
        # compact set and enough modeled scenario coverage.
        elite_value = (
            score >= 75
            and len(picks) <= 8
            and best_ev >= 1.45
            and scenario_mass >= 0.11
            and composite >= 3.8
        )

        return high_confidence or strong_value or elite_value

    opportunity_alerts_module._candidate_rows = candidate_rows
    opportunity_alerts_module._is_selected_mid = is_selected_mid
    opportunity_alerts_module._mid_value_selection_installed = True
