"""Mine conservative betting/skip rules from settled pre-close predictions.

Rules are descriptive candidates until they survive an out-of-time validation
window with enough samples. The script never promotes a one-day hot streak.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
import json
from pathlib import Path
from typing import Callable

from daily_report import latest_predictions, read_jsonl

REPORT_DIR = Path("data/daily_reports")
PREDICTION_LOG = Path("data/prediction_log.jsonl")
OUTPUT_DIR = Path("data/strategy_rules")
HIYORI_REQUEST_DIR = Path("data/hiyori/requests")

MIN_TRAIN = 40
MIN_VALID = 24
MIN_VALID_DAYS = 2
MAX_RULES = 20


def _band(value, cuts, labels):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return "unknown"
    for cut, label in zip(cuts, labels):
        if x < cut:
            return label
    return labels[-1]


def _head_features(row):
    heads = row.get("heads") or {}
    ranked = sorted((float(v or 0), str(k)) for k, v in heads.items())
    ranked.reverse()
    top = ranked[0][0] if ranked else 0.0
    second = ranked[1][0] if len(ranked) > 1 else 0.0
    return top, max(0.0, top - second)


def _tactical_features(pred: dict) -> dict:
    """Compact exhibition/slit features for out-of-time rule mining.

    These are descriptive only. They do not change production weights directly;
    a condition still has to clear the normal train/validation guardrails.
    """
    preview = pred.get("preview") or {}
    raw_boats = list(pred.get("tactical_inputs") or [])
    if not raw_boats:
        pboats = preview.get("boats") or {}
        if isinstance(pboats, dict):
            for lane, row in pboats.items():
                if not isinstance(row, dict):
                    continue
                item = dict(row)
                item.setdefault("lane", lane)
                raw_boats.append(item)

    boats = {}
    for row in raw_boats:
        try:
            lane = int(row.get("lane"))
        except (TypeError, ValueError):
            continue
        if not 1 <= lane <= 6:
            continue
        boats[lane] = row

    st = {}
    flying = set()
    for lane, row in boats.items():
        if row.get("exhibition_flying"):
            flying.add(lane)
        value = row.get("exhibition_st")
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if 0 <= value <= 1:
            st[lane] = value

    outer_fast = [
        lane for lane in (3, 4, 5, 6)
        if lane in st and st[lane] <= 0.10
    ]
    candidates = []
    for lane in (3, 4, 5, 6):
        if lane not in st or (lane - 1) not in st:
            continue
        gap = st[lane - 1] - st[lane]
        if st[lane] <= 0.12 and gap >= 0.05:
            candidates.append((gap, lane))

    candidates.sort(reverse=True)
    attack_lane = str(candidates[0][1]) if candidates else "none"
    attack_gap = candidates[0][0] if candidates else None

    spread = None
    if len(st) >= 4:
        spread = max(st.values()) - min(st.values())

    if candidates and attack_gap is not None and attack_gap >= 0.10:
        slit_shape = f"strong_outer_attack_{attack_lane}"
    elif candidates:
        slit_shape = f"outer_attack_{attack_lane}"
    elif outer_fast:
        slit_shape = "outer_pressure"
    elif len(st) >= 4:
        slit_shape = "flat_or_inner"
    else:
        slit_shape = "unknown"

    return {
        "slit_shape": slit_shape,
        "attack_lane": attack_lane,
        "attack_gap": (
            _band(attack_gap, [0.05, 0.10, 0.15], ["<5pt", "5-9pt", "10-14pt", "15pt+"])
            if attack_gap is not None else "unknown"
        ),
        "st_spread": (
            _band(spread, [0.05, 0.10, 0.15], ["<5pt", "5-9pt", "10-14pt", "15pt+"])
            if spread is not None else "unknown"
        ),
        "outer_fast": "yes" if outer_fast else ("no" if len(st) >= 4 else "unknown"),
        "lane1_flying": "yes" if 1 in flying else ("no" if boats else "unknown"),
    }


def _observation_features(pred: dict, report_row: dict) -> dict:
    top, gap = _head_features(pred)
    preview = pred.get("preview") or {}
    tactical = _tactical_features(pred)
    score = int(pred.get("selection_score") or 0)
    points = len(report_row.get("picks") or pred.get("all_picks") or [])
    return {
        "venue": str(report_row.get("venue") or pred.get("venue") or "unknown"),
        "grade": str(pred.get("grade") or report_row.get("grade") or "unknown"),
        "event": str(pred.get("event_grade") or "normal"),
        "score": _band(score, [60, 75, 85], ["<60", "60-74", "75-84", "85+"]),
        "points": _band(points, [11, 13, 15], ["<=10", "11-12", "13-14", "15+"]),
        "head_top": _band(top, [.25, .35, .45], ["<25%", "25-34%", "35-44%", "45%+"]),
        "head_gap": _band(gap, [.05, .10, .20], ["<5pt", "5-9pt", "10-19pt", "20pt+"]),
        "wind": _band(preview.get("wind_speed"), [2, 4], ["0-1m", "2-3m", "4m+"]),
        "wave": _band(preview.get("wave_cm"), [3, 7], ["0-2cm", "3-6cm", "7cm+"]),
        **tactical,
        "selected": "yes" if score >= 75 and pred.get("virtual_status") == "bet" else "no",
    }


def _hiyori_feature_context(day: str, key: str) -> dict:
    try:
        jcd, rno = key.split(":", 1)
        path = HIYORI_REQUEST_DIR / f"{day}_{str(jcd).zfill(2)}_{int(rno):02d}.json"
    except (TypeError, ValueError):
        return {}
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    official = data.get("official") or {}
    return official if isinstance(official, dict) else {}


def load_observations() -> list[dict]:
    predictions = read_jsonl(PREDICTION_LOG)
    out = []
    for path in sorted(REPORT_DIR.glob("20*.json")):
        day = path.stem
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        latest, _ = latest_predictions(predictions, day)
        for rr in report.get("races") or []:
            if rr.get("status") != "settled" or not rr.get("hit_eligible"):
                continue
            key = f"{str(rr.get('jcd')).zfill(2)}:{int(rr.get('rno') or 0)}"
            pred = latest.get(key)
            if not pred:
                continue
            uniform = rr.get("uniform") or {}
            stake = int(uniform.get("stake_yen") or 0)
            ret = int(uniform.get("return_yen") or 0)
            if stake <= 0:
                continue
            out.append({
                "day": day,
                "key": key,
                "hit": bool(rr.get("prediction_hit")),
                "stake": stake,
                "return": ret,
                "profit": ret - stake,
                "features": _observation_features(
                    {
                        **_hiyori_feature_context(day, key),
                        **pred,
                        "preview": pred.get("preview") or _hiyori_feature_context(day, key).get("preview") or {},
                        "tactical_inputs": (
                            pred.get("tactical_inputs")
                            or _hiyori_feature_context(day, key).get("inputs")
                            or []
                        ),
                    },
                    rr,
                ),
            })
    return out


def summary(rows: list[dict]) -> dict:
    n = len(rows)
    stake = sum(r["stake"] for r in rows)
    ret = sum(r["return"] for r in rows)
    hits = sum(1 for r in rows if r["hit"])
    days = len({r["day"] for r in rows})
    return {
        "samples": n,
        "days": days,
        "hits": hits,
        "hit_rate": round(hits / n * 100, 1) if n else None,
        "stake_yen": stake,
        "return_yen": ret,
        "profit_yen": ret - stake,
        "roi": round(ret / stake * 100, 1) if stake else None,
    }


def _time_split(rows: list[dict]):
    days = sorted({r["day"] for r in rows})
    if len(days) < 3:
        return rows, []
    cut = max(1, int(len(days) * .70))
    if cut >= len(days):
        cut = len(days) - 1
    train_days = set(days[:cut])
    valid_days = set(days[cut:])
    return (
        [r for r in rows if r["day"] in train_days],
        [r for r in rows if r["day"] in valid_days],
    )


def _matches(row, conds):
    f = row["features"]
    return all(f.get(k) == v for k, v in conds)


def mine(rows: list[dict]) -> dict:
    train, valid = _time_split(rows)
    feature_names = [
        "venue", "grade", "event", "score", "points", "head_top", "head_gap",
        "wind", "wave", "slit_shape", "attack_lane", "attack_gap", "st_spread",
        "outer_fast", "lane1_flying", "selected",
    ]
    values = {
        name: sorted({r["features"].get(name) or "unknown" for r in train})
        for name in feature_names
    }

    conditions = []
    for name in feature_names:
        for value in values[name]:
            if value != "unknown":
                conditions.append(((name, value),))

    pair_fields = [
        ("grade", "head_gap"), ("score", "head_gap"), ("points", "head_gap"),
        ("venue", "grade"), ("venue", "head_gap"), ("event", "head_gap"),
        ("selected", "points"), ("head_top", "head_gap"),
        ("venue", "wind"), ("venue", "wave"), ("venue", "slit_shape"),
        ("venue", "attack_lane"), ("head_gap", "slit_shape"),
        ("outer_fast", "head_gap"), ("attack_gap", "head_gap"),
    ]
    for a, b in pair_fields:
        for av in values[a]:
            for bv in values[b]:
                if av != "unknown" and bv != "unknown":
                    conditions.append(((a, av), (b, bv)))

    candidates = []
    for cond in conditions:
        tr = [r for r in train if _matches(r, cond)]
        va = [r for r in valid if _matches(r, cond)]
        ts, vs = summary(tr), summary(va)
        enough = ts["samples"] >= MIN_TRAIN and vs["samples"] >= MIN_VALID and vs["days"] >= MIN_VALID_DAYS
        status = "insufficient"
        if enough and ts["roi"] is not None and vs["roi"] is not None:
            # Positive rules need to work in both periods, not just average out.
            if ts["roi"] >= 105 and vs["roi"] >= 100 and vs["profit_yen"] > 0:
                status = "positive"
            # Skip rules are deliberately stricter to avoid throwing away useful races.
            elif ts["roi"] <= 75 and vs["roi"] <= 75:
                status = "avoid"
            else:
                status = "neutral"

        if status in {"positive", "avoid"}:
            candidates.append({
                "conditions": {k: v for k, v in cond},
                "status": status,
                "train": ts,
                "validation": vs,
            })

    positives = sorted(
        [x for x in candidates if x["status"] == "positive"],
        key=lambda x: (x["validation"]["roi"], x["validation"]["samples"]),
        reverse=True,
    )[:MAX_RULES]
    avoids = sorted(
        [x for x in candidates if x["status"] == "avoid"],
        key=lambda x: (x["validation"]["roi"], -x["validation"]["samples"]),
    )[:MAX_RULES]

    return {
        "version": "strategy-rule-miner-v2-tactical",
        "definition": "settled pre-close predictions; flat 100 yen per displayed pick",
        "guardrails": {
            "min_train_samples": MIN_TRAIN,
            "min_validation_samples": MIN_VALID,
            "min_validation_days": MIN_VALID_DAYS,
            "time_split": "oldest 70% days train / newest 30% days validation",
            "no_one_day_promotion": True,
            "no_martingale": True,
        },
        "days": sorted({r["day"] for r in rows}),
        "baseline": summary(rows),
        "train_baseline": summary(train),
        "validation_baseline": summary(valid),
        "validated_positive_rules": positives,
        "validated_avoid_rules": avoids,
        "note": "No rule is guaranteed. Only out-of-time validated rules are eligible for future production review.",
    }


def markdown(result: dict) -> str:
    b = result["baseline"]
    lines = [
        "# 勝ちルール探索レポート",
        "",
        f"対象 {b['samples']}R / {b['days']}日 / 的中率 {b['hit_rate']}% / 回収率 {b['roi']}% / 収支 {b['profit_yen']:+,}円",
        "",
        "## 運用ルール",
        "",
        "- 1日だけの好成績は採用しない",
        "- 古い70%で発見し、新しい30%で再現した条件だけ候補にする",
        f"- 最低サンプル: 学習{MIN_TRAIN}R / 検証{MIN_VALID}R / 検証{MIN_VALID_DAYS}日",
        "- マーチン・負け追いは勝ちルールとして扱わない",
        "",
        "## 検証済みプラス候補",
        "",
    ]
    positives = result["validated_positive_rules"]
    if not positives:
        lines.append("まだなし。サンプル不足または再現性不足。")
    for x in positives:
        c = " / ".join(f"{k}={v}" for k, v in x["conditions"].items())
        lines.append(f"- {c}: 検証 {x['validation']['samples']}R / 的中{x['validation']['hit_rate']}% / ROI{x['validation']['roi']}%")
    lines += ["", "## 見送り候補", ""]
    avoids = result["validated_avoid_rules"]
    if not avoids:
        lines.append("まだなし。十分な再現性が出るまで見送り条件は固定しない。")
    for x in avoids:
        c = " / ".join(f"{k}={v}" for k, v in x["conditions"].items())
        lines.append(f"- {c}: 検証 {x['validation']['samples']}R / 的中{x['validation']['hit_rate']}% / ROI{x['validation']['roi']}%")
    return "\n".join(lines) + "\n"


def main():
    rows = load_observations()
    result = mine(rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    latest_json = OUTPUT_DIR / "latest.json"
    latest_md = OUTPUT_DIR / "latest.md"
    latest_json.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    latest_md.write_text(markdown(result), encoding="utf-8")
    if result["days"]:
        day = result["days"][-1]
        (OUTPUT_DIR / f"{day}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (OUTPUT_DIR / f"{day}.md").write_text(markdown(result), encoding="utf-8")
    print(markdown(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
