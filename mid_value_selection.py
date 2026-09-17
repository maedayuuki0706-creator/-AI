"""Evidence-first value policy for the 中穴 feed.

The rule is intentionally *not* "odds are split, therefore buy the favourite".
Prediction evidence comes first. Price/popularity is consulted only after a
combination already has enough model probability and EV support.

Two changes are additive:
1. Allow a small 6-12x value-favourite window when probability + EV are strong.
2. Keep the existing selected-mid gate, plus a looser value route that requires
   stronger EV, scenario mass and composite-odds support.

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
    original_is_selected_mid = opportunity_alerts_module._is_selected_mid

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
        # Existing high-confidence route remains intact.
        if original_is_selected_mid(payload):
            return True

        picks = list(payload.get("picks") or [])
        if not picks or len(picks) > 12:
            return False

        score = int(payload.get("score") or 0)
        if score < 68:
            return False

        best_ev = max((_ev(row) for row in picks), default=0.0)
        scenario_mass = sum(_num(row.get("probability")) for row in picks)
        composite = payload.get("composite_odds")
        composite = _num(composite, 0.0)

        # Looser *selection volume*, not looser reasoning:
        # below the old 75 line, demand stronger value and scenario support.
        return (
            best_ev >= 1.18
            and scenario_mass >= 0.10
            and composite >= 2.5
        )

    opportunity_alerts_module._candidate_rows = candidate_rows
    opportunity_alerts_module._is_selected_mid = is_selected_mid
    opportunity_alerts_module._mid_value_selection_installed = True
