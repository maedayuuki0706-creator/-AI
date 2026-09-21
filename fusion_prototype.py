"""Three-stream prototype for 2026-09-22.

Keeps Existing / Hiyori / Fusion separate.  Fusion is only emitted when the
Hiyori adapter provides race-specific per-combination probabilities; otherwise
the race is logged as hiyori_not_ready instead of pretending that the existing
model is a Hiyori prediction.
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import direct_discord_notify as existing
import kyoteibiyori_adapter as hiyori
from ticket_compression import compression_snapshot

JST = ZoneInfo("Asia/Tokyo")
LOG = Path("data/prototype_comparison_log.jsonl")
LEVELS = (20, 16, 12, 10, 8, 6, 4)


def _norm(rows):
    total = sum(max(0.0, float(r.get("probability") or 0)) for r in rows)
    if total <= 0:
        return {}
    return {r["combination"]: max(0.0, float(r.get("probability") or 0)) / total for r in rows}


def _rank(prob):
    return sorted(prob, key=lambda c: prob[c], reverse=True)


def fuse(existing_rows, hiyori_rows, existing_weight=0.55, hiyori_weight=0.45):
    """Blend two independently generated trifecta distributions."""
    a, b = _norm(existing_rows), _norm(hiyori_rows)
    if not a or not b:
        return []
    keys = set(a) | set(b)
    score = {k: existing_weight * a.get(k, 0.0) + hiyori_weight * b.get(k, 0.0) for k in keys}
    total = sum(score.values()) or 1.0
    return [{"combination": k, "probability": score[k] / total} for k in _rank(score)]


def head_distribution(rows):
    out = {str(i): 0.0 for i in range(1, 7)}
    for row in rows:
        c = str(row.get("combination", ""))
        if len(c) >= 1 and c[0] in out:
            out[c[0]] += float(row.get("probability") or 0)
    return out


def compress(rows):
    heads = head_distribution(rows)
    head = max(heads, key=heads.get) if rows else None
    fixed = [r["combination"] for r in rows if r["combination"].split("-")[0] == head]
    return {"head": int(head) if head else None,
            "levels": {str(n): fixed[:n] for n in LEVELS}}


def _append(row):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build_race(day, jcd, rno, now=None):
    now = (now or datetime.now(JST)).astimezone(JST)
    base = existing.analyze_official(day, str(jcd).zfill(2), int(rno))
    if not base:
        row = {"day": day, "jcd": str(jcd).zfill(2), "rno": int(rno),
               "captured_at": now.isoformat(), "status": "existing_unavailable"}
        _append(row)
        return row

    ex_rows = list(base.get("trifecta") or [])
    # race_model() is deliberately strict: until Hiyori yields independent
    # race-specific probabilities it returns ready=False.
    hy = hiyori.race_model(day, str(jcd).zfill(2), int(rno))
    hy_rows = list(hy.get("trifecta") or []) if hy.get("ready") else []
    fused = fuse(ex_rows, hy_rows) if hy_rows else []

    row = {
        "day": day, "jcd": str(jcd).zfill(2),
        "venue": existing.VENUES.get(str(jcd).zfill(2), str(jcd)),
        "rno": int(rno), "captured_at": now.isoformat(),
        "status": "ready" if fused else "hiyori_not_ready",
        "existing": {
            "model_version": base.get("model_version"),
            "heads": base.get("heads"),
            "top20": [r["combination"] for r in ex_rows[:20]],
            "compression": compression_snapshot(base),
            "inputs": base.get("inputs"),
            "preview": base.get("preview"),
        },
        "hiyori": {
            "source_url": hy.get("source_url"),
            "ready": bool(hy.get("ready")),
            "reason": hy.get("reason"),
            "signals": hy.get("signals"),
            "heads": head_distribution(hy_rows) if hy_rows else None,
            "top20": [r["combination"] for r in hy_rows[:20]],
            "compression": compress(hy_rows) if hy_rows else None,
        },
        "fusion": {
            "weights": {"existing": 0.55, "hiyori": 0.45},
            "heads": head_distribution(fused) if fused else None,
            "top20": [r["combination"] for r in fused[:20]],
            "compression": compress(fused) if fused else None,
        },
    }
    _append(row)
    return row


def evaluate(row, result, payout=None, popularity=None):
    """Attach result survival diagnostics without overwriting the raw snapshot."""
    winner = "-".join(map(str, result))
    def check(stream):
        s = row.get(stream) or {}
        comp = s.get("compression") or {}
        levels = comp.get("levels") or {}
        survival = {n: winner in levels.get(str(n), []) for n in LEVELS}
        first_drop = next((n for n in LEVELS if not survival[n]), None)
        top20 = s.get("top20") or []
        result_set = set(map(str, result))
        return {
            "head_hit": bool(comp.get("head") == int(result[0])),
            "same_three_in_top20": any(set(c.split("-")) == result_set for c in top20),
            "full_hit_top20": winner in top20,
            "survival": survival,
            "first_drop_level": first_drop,
        }
    return {
        "winner": winner, "payout": payout, "popularity": popularity,
        "manshu": bool(payout is not None and payout >= 10000),
        "existing": check("existing"),
        "hiyori": check("hiyori"),
        "fusion": check("fusion"),
    }
