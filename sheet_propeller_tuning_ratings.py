"""Auto-update player propeller tuning ratings (選手データ U/Y/AA).

Source of truth:
- 足回り推移 T:W = improvement deltas (+ means faster)
- 足回り推移 AV = propeller marker ("新" = explicit new propeller)
- 足回り推移 AW = engine-part replacement
- 足回り推移 AF = learning weight

Attribution rules:
1) Explicit "新" propeller is strong evidence.
2) Otherwise, a meeting is accepted as propeller-tuning evidence only when
   at least 3 valid no-part-replacement runs improve on the weighted metric.
3) Single-run improvement alone is not accepted.
4) Engine-part replacement rows are excluded from propeller improvement scoring.

This job only owns U (ペラ調整力), Y (ペラ改善値), AA (ペラサンプル数).
It does not import or modify prediction, Discord, X, or delivery code.
"""
import json
import math
import os
from collections import defaultdict

import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = os.getenv(
    "BOAT_SHEET_ID",
    "1dbUPyfxjIRaT-G8F_LlGMX7Ld_ZB951UmF4HpW_PYJo",
)

# 展示 / 一周 / 回り足 / 直線
WEIGHTS = (0.10, 0.25, 0.45, 0.20)


def num(v):
    if v is None:
        return None
    s = str(v).strip().replace("%", "")
    if not s:
        return None
    try:
        x = float(s)
        return x if math.isfinite(x) else None
    except ValueError:
        return None


def norm_date(v):
    return str(v or "").strip().replace("-", "/")


def rating_from_improvement(score, meets):
    # Keep the same 1.0-4.5 scale used by the weak-motor recovery job.
    if score >= 0.30:
        rating = 4.0
    elif score >= 0.15:
        rating = 3.5
    elif score >= 0.07:
        rating = 3.0
    elif score >= 0.02:
        rating = 2.5
    elif score >= -0.03:
        rating = 2.0
    elif score >= -0.10:
        rating = 1.5
    else:
        rating = 1.0

    # Multiple independent meetings at a top level are stronger evidence.
    if meets >= 2 and score >= 0.30:
        rating = 4.5
    return rating


def main():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON secret is required")

    info = json.loads(raw)
    creds = Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    book = gspread.authorize(creds).open_by_key(SPREADSHEET_ID)

    foot = book.worksheet("足回り推移").get_all_values()

    # Same venue + meeting + player + motor = one attribution unit.
    groups = defaultdict(list)
    for row_index, r in enumerate(foot[1:], start=2):
        if len(r) < 49:
            continue

        venue = (r[0] or "").strip()
        section = norm_date(r[1] if len(r) > 1 else "")
        reg = (r[4] if len(r) > 4 else "").strip()
        motor = (r[7] if len(r) > 7 else "").strip()
        if not venue or not section or not reg or not motor:
            continue

        deltas = [num(r[i]) if len(r) > i else None for i in (19, 20, 21, 22)]
        if any(v is None for v in deltas) or any(abs(v) > 2 for v in deltas):
            score = None
        else:
            learn_weight = num(r[31] if len(r) > 31 else None)
            if learn_weight is None:
                learn_weight = 1.0
            score = sum(v * w for v, w in zip(deltas, WEIGHTS)) * learn_weight

        propeller = (r[47] if len(r) > 47 else "").strip()
        parts = (r[48] if len(r) > 48 else "").strip()

        groups[(venue, section, reg, motor)].append(
            {
                "row_index": row_index,
                "score": score,
                "propeller": propeller,
                "parts": parts,
            }
        )

    assignments = []
    explicit_meets = 0
    inferred_meets = 0

    for (venue, section, reg, motor), rows in groups.items():
        rows.sort(key=lambda x: x["row_index"])

        explicit_positions = [
            i for i, r in enumerate(rows) if r["propeller"] == "新"
        ]
        explicit = bool(explicit_positions)

        no_part_valid = [
            r for r in rows if not r["parts"] and r["score"] is not None
        ]
        positive_count = sum(r["score"] > 0 for r in no_part_valid)
        inferred = positive_count >= 3

        if not explicit and not inferred:
            continue

        scoring_rows = no_part_valid
        if explicit:
            # For explicit replacement, do not credit pre-replacement runs.
            first_new_row = rows[explicit_positions[0]]["row_index"]
            scoring_rows = [
                r for r in scoring_rows if r["row_index"] >= first_new_row
            ]

        if not scoring_rows:
            continue

        avg = sum(r["score"] for r in scoring_rows) / len(scoring_rows)
        assignments.append(
            {
                "reg": reg,
                "runs": len(scoring_rows),
                "improvement": avg,
                "explicit": explicit,
            }
        )
        if explicit:
            explicit_meets += 1
        else:
            inferred_meets += 1

    # Aggregate across independent meetings. Weight improvement by valid run count,
    # but keep AA as the number of qualifying meetings (evidence samples).
    agg = defaultdict(lambda: {"sum": 0.0, "runs": 0, "meets": 0})
    for a in assignments:
        g = agg[a["reg"]]
        g["sum"] += a["improvement"] * a["runs"]
        g["runs"] += a["runs"]
        g["meets"] += 1

    ratings = {}
    for reg, a in agg.items():
        improvement = a["sum"] / a["runs"]
        ratings[reg] = (
            rating_from_improvement(improvement, a["meets"]),
            round(improvement, 4),
            a["meets"],
        )

    ws = book.worksheet("選手データ")
    players = ws.get_all_values()

    u_values = []
    y_values = []
    aa_values = []
    matched = 0

    for r in players[1:]:
        reg = (r[0] if r else "").strip()
        if reg in ratings:
            rating, improvement, samples = ratings[reg]
            u_values.append([rating])
            y_values.append([improvement])
            aa_values.append([samples])
            matched += 1
        else:
            u_values.append([""])
            y_values.append([""])
            aa_values.append([""])

    if u_values:
        last = len(u_values) + 1
        ws.update(u_values, range_name=f"U2:U{last}", value_input_option="RAW")
        ws.update(y_values, range_name=f"Y2:Y{last}", value_input_option="RAW")
        ws.update(aa_values, range_name=f"AA2:AA{last}", value_input_option="RAW")

    print(
        json.dumps(
            {
                "qualifying_meetings": len(assignments),
                "explicit_new_propeller_meetings": explicit_meets,
                "inferred_propeller_tuning_meetings": inferred_meets,
                "rated_players": len(ratings),
                "written": matched,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
