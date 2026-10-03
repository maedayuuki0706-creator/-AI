"""Select up to ten high-value non-1-head races per day for X.

The selector uses only pre-race prototype predictions already committed to the
repository. It never consults race results when deciding what to post.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path

from direct_discord_notify import JST
import x_delivery_store as outbox
import x_post_delivery as xpost

PT12_DIR = Path("data/prototype12_delivery/predictions")
PT3_DIR = Path("data/prototype3_delivery/predictions")
FEATURE_SOURCES = {"AI重なり本線", "配当期待本線"}
MAX_DAILY_POSTS = 10
MIN_LEAD_SECONDS = 11 * 60
MAX_LEAD_SECONDS = 40 * 60
MIN_VALUE_ODDS = 25.0
MAX_VALUE_ODDS = 180.0
MAIN_POINTS = 10
COVER_POINTS = 8
MIN_ALT_HEAD_PROB = 0.01


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _race_key(day: str, jcd: str, rno: int) -> str:
    return f"{day}:{str(jcd).zfill(2)}:{int(rno)}"


def _deadline(day: str, text: str) -> datetime | None:
    try:
        return datetime.strptime(f"{day} {text}", "%Y%m%d %H:%M").replace(tzinfo=JST)
    except (TypeError, ValueError):
        return None


def _model(name: str, raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    heads = {}
    for lane, value in (raw.get("heads") or {}).items():
        try:
            heads[str(int(lane))] = float(value)
        except (TypeError, ValueError):
            continue
    main = [str(x) for x in (raw.get("main_picks") or []) if isinstance(x, str)]
    tri = {}
    for row in raw.get("trifecta") or []:
        if not isinstance(row, dict):
            continue
        combo = str(row.get("combination") or "")
        if not combo:
            continue
        try:
            tri[combo] = {
                "odds": float(row.get("odds") or 0),
                "ev": float(row.get("expected_value") or 0),
                "prob": float(row.get("probability") or 0),
            }
        except (TypeError, ValueError):
            continue
    return {
        "name": name,
        "grade": str(raw.get("grade") or ""),
        "heads": heads,
        "main": main,
        "tri": tri,
        "race_shape": raw.get("race_shape") or {},
        "market_structure": raw.get("market_structure") or {},
    }


def _load_race(day: str, stem: str) -> dict | None:
    pt12 = _read(PT12_DIR / f"{stem}.json")
    pt3 = _read(PT3_DIR / f"{stem}.json")
    base = pt12 or pt3
    if not base:
        return None
    try:
        jcd = str(base.get("jcd") or "").zfill(2)
        rno = int(base.get("rno") or 0)
    except (TypeError, ValueError):
        return None
    deadline = str(base.get("deadline") or "")
    venue = str(base.get("venue") or jcd)

    models = []
    raw12 = pt12.get("models") if isinstance(pt12.get("models"), dict) else {}
    for name in ("prototype1", "prototype2"):
        item = _model(name, raw12.get(name))
        if item:
            models.append(item)
    item = _model("prototype3", pt3.get("model"))
    if item:
        models.append(item)
    if not models:
        return None
    return {
        "day": day,
        "jcd": jcd,
        "rno": rno,
        "venue": venue,
        "deadline": deadline,
        "models": models,
    }


def _odds_for(model: dict, combo: str) -> float:
    return float((model.get("tri") or {}).get(combo, {}).get("odds") or 0)


def _value_rows(model: dict, focus_heads: set[str] | None = None) -> list[tuple[str, dict]]:
    out = []
    for combo in model.get("main") or []:
        parts = combo.split("-")
        if len(parts) != 3 or parts[0] == "1":
            continue
        if focus_heads and parts[0] not in focus_heads:
            continue
        row = (model.get("tri") or {}).get(combo) or {}
        odds = float(row.get("odds") or 0)
        ev = float(row.get("ev") or 0)
        prob = float(row.get("prob") or 0)
        if MIN_VALUE_ODDS <= odds <= MAX_VALUE_ODDS and ev >= 0.90 and prob >= 0.008:
            out.append((combo, {"odds": odds, "ev": ev, "prob": prob}))
    out.sort(key=lambda item: (item[1]["prob"] * item[1]["ev"], item[1]["ev"], item[1]["odds"]), reverse=True)
    return out


def _aggregate_trifecta(models: list[dict]) -> dict[str, dict]:
    """Combine full trifecta tables without hiding low-frequency alternate heads."""
    combined: dict[str, dict] = {}
    for model in models:
        main = set(model.get("main") or [])
        for combo, row in (model.get("tri") or {}).items():
            parts = str(combo).split("-")
            if len(parts) != 3 or len(set(parts)) != 3 or any(part not in "123456" for part in parts):
                continue
            try:
                prob = float(row.get("prob") or 0)
                ev = float(row.get("ev") or 0)
                odds = float(row.get("odds") or 0)
            except (TypeError, ValueError):
                continue
            item = combined.setdefault(
                combo,
                {
                    "count": 0,
                    "prob_sum": 0.0,
                    "max_prob": 0.0,
                    "max_ev": 0.0,
                    "odds": 0.0,
                    "main_support": 0,
                },
            )
            item["count"] += 1
            item["prob_sum"] += prob
            item["max_prob"] = max(item["max_prob"], prob)
            item["max_ev"] = max(item["max_ev"], ev)
            item["odds"] = max(item["odds"], odds)
            if combo in main:
                item["main_support"] += 1
    for item in combined.values():
        item["avg_prob"] = item["prob_sum"] / max(1, item["count"])
    return combined


def _alt_head_probabilities(models: list[dict]) -> dict[str, float]:
    """Use the strongest live model signal so a >=1% alternate head is never hidden."""
    out = {}
    for lane in "23456":
        values = []
        for model in models:
            try:
                values.append(float((model.get("heads") or {}).get(lane) or 0))
            except (TypeError, ValueError):
                continue
        out[lane] = max(values, default=0.0)
    return out


def _main_rank(meta: dict) -> tuple:
    return (
        int(meta.get("main_support") or 0),
        float(meta.get("avg_prob") or 0),
        float(meta.get("max_prob") or 0),
        float(meta.get("max_ev") or 0),
        float(meta.get("odds") or 0),
    )


def _cover_rank(meta: dict) -> tuple:
    prob = float(meta.get("avg_prob") or 0)
    ev = max(0.25, min(float(meta.get("max_ev") or 0), 3.0))
    return (
        int(meta.get("main_support") or 0),
        prob * ev,
        prob,
        float(meta.get("max_ev") or 0),
        float(meta.get("odds") or 0),
    )


def _ticket_plan(race: dict) -> dict | None:
    """Build 10 main + up to 8 covers after exhibition-based models are complete.

    Every 2-6 head with at least a 1% head probability in any live model gets
    at least one exact trifecta in the cover section. Remaining cover slots
    stay non-1-head whenever possible.
    """
    models = race.get("models") or []
    rows = _aggregate_trifecta(models)
    if not rows:
        return None

    ranked_main = sorted(rows, key=lambda combo: _main_rank(rows[combo]), reverse=True)
    main = ranked_main[:MAIN_POINTS]
    used = set(main)

    alt_heads = _alt_head_probabilities(models)
    eligible = [
        lane for lane, probability in sorted(
            alt_heads.items(), key=lambda item: item[1], reverse=True
        )
        if probability >= MIN_ALT_HEAD_PROB
    ]

    cover: list[str] = []
    for lane in eligible:
        lane_rows = [
            combo for combo in rows
            if combo.startswith(f"{lane}-") and combo not in used
        ]
        if not lane_rows:
            continue
        combo = max(lane_rows, key=lambda value: _cover_rank(rows[value]))
        cover.append(combo)
        used.add(combo)

    non1_rows = sorted(
        (
            combo for combo in rows
            if not combo.startswith("1-") and combo not in used
        ),
        key=lambda combo: _cover_rank(rows[combo]),
        reverse=True,
    )
    for combo in non1_rows:
        if len(cover) >= COVER_POINTS:
            break
        cover.append(combo)
        used.add(combo)

    if len(cover) < COVER_POINTS:
        for combo in ranked_main:
            if len(cover) >= COVER_POINTS:
                break
            if combo in used:
                continue
            cover.append(combo)
            used.add(combo)

    head_note = "・".join(
        f"{lane}={alt_heads[lane] * 100:.1f}%"
        for lane in eligible
    )
    return {
        "main": main,
        "cover": cover[:COVER_POINTS],
        "eligible_alt_heads": eligible,
        "alt_head_probabilities": alt_heads,
        "note": f"展示反映｜AI頭評価 {head_note}" if head_note else "展示反映",
    }


def _overlap_candidate(race: dict) -> dict | None:
    models = race["models"]
    combo_models: dict[str, list[dict]] = defaultdict(list)
    for model in models:
        for combo in model.get("main") or []:
            parts = combo.split("-")
            if len(parts) == 3 and parts[0] != "1":
                combo_models[combo].append(model)

    shared = []
    for combo, owners in combo_models.items():
        if len(owners) < 2:
            continue
        rows = [(owner.get("tri") or {}).get(combo) or {} for owner in owners]
        odds = max(float(row.get("odds") or 0) for row in rows)
        ev = max(float(row.get("ev") or 0) for row in rows)
        prob = max(float(row.get("prob") or 0) for row in rows)
        if MIN_VALUE_ODDS <= odds <= MAX_VALUE_ODDS and ev >= 0.90 and prob >= 0.008:
            shared.append((combo, len(owners), odds, ev, prob))

    top_heads = []
    for model in models:
        heads = model.get("heads") or {}
        if not heads:
            continue
        lane, prob = max(heads.items(), key=lambda item: item[1])
        if lane != "1" and prob >= 0.15:
            top_heads.append(lane)
    repeated_heads = {lane for lane, count in Counter(top_heads).items() if count >= 2}

    if not shared and not repeated_heads:
        return None

    if shared:
        shared.sort(key=lambda item: (item[1], item[4] * item[3], item[2]), reverse=True)
        picks = [item[0] for item in shared[:8]]
        heads = sorted({pick.split("-")[0] for pick in picks})
        support = max(item[1] for item in shared)
        best_ev = max(item[3] for item in shared)
        best_odds = max(item[2] for item in shared)
        score = 58 + support * 8 + min(best_ev, 3.0) * 5 + min(best_odds, 100.0) * 0.08
    else:
        heads = sorted(repeated_heads)
        rows = []
        for model in models:
            rows.extend((combo, meta, model["name"]) for combo, meta in _value_rows(model, set(heads)))
        by_combo = {}
        for combo, meta, name in rows:
            old = by_combo.get(combo)
            rank = (meta["prob"] * meta["ev"], meta["ev"], meta["odds"])
            if old is None or rank > old[0]:
                by_combo[combo] = (rank, meta, name)
        ranked = sorted(by_combo.items(), key=lambda item: item[1][0], reverse=True)
        picks = [combo for combo, _ in ranked[:8]]
        if not picks:
            return None
        score = 72 + len(repeated_heads) * 4

    if score < 74:
        return None
    head_text = "・".join(heads)
    return {
        "source": "AI重なり本線",
        "score": score,
        "picks": picks,
        "note": f"複数AIで{head_text}号艇頭が重なり＋中穴配当",
    }


def _confidence_candidate(race: dict) -> dict | None:
    best = None
    for model in race["models"]:
        heads = model.get("heads") or {}
        if not heads:
            continue
        p1 = float(heads.get("1") or 0)
        non1 = sorted(((lane, prob) for lane, prob in heads.items() if lane != "1"), key=lambda item: item[1], reverse=True)
        if not non1:
            continue
        focus = {non1[0][0]}
        if len(non1) > 1 and non1[1][1] >= 0.15 and non1[0][1] - non1[1][1] <= 0.10:
            focus.add(non1[1][0])
        rows = _value_rows(model, focus)
        if len(rows) < 2:
            continue
        best_non1 = non1[0][1]
        non1_total = max(0.0, 1.0 - p1)
        max_ev = max(meta["ev"] for _, meta in rows)
        attack = float((model.get("race_shape") or {}).get("attack_pressure") or 0)
        market_signal = float((model.get("market_structure") or {}).get("signal_score") or 0)
        grade = model.get("grade") or ""
        strong = (
            best_non1 >= 0.17
            and p1 <= 0.55
            and (grade in {"A", "B"} or max_ev >= 1.80 or non1_total >= 0.70)
        )
        if not strong:
            continue
        grade_bonus = 8 if grade == "A" else 5 if grade == "B" else 0
        score = (
            best_non1 * 100
            + non1_total * 35
            + min(max_ev, 3.0) * 7
            + grade_bonus
            + min(attack, 50.0) * 0.15
            + min(market_signal, 70.0) * 0.10
        )
        if score < 64:
            continue
        candidate = {
            "source": "配当期待本線",
            "score": score,
            "picks": [combo for combo, _ in rows[:8]],
            "note": f"{'・'.join(sorted(focus))}号艇の頭評価＋配当妙味",
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    return best


def _candidate(race: dict) -> dict | None:
    overlap = _overlap_candidate(race)
    confidence = _confidence_candidate(race)
    if overlap and confidence:
        # Prefer true cross-AI agreement when scores are close.
        if overlap["score"] + 4 >= confidence["score"]:
            return overlap
        return confidence
    return overlap or confidence


def _stems(day: str) -> set[str]:
    stems = set()
    for directory in (PT12_DIR, PT3_DIR):
        if not directory.exists():
            continue
        for path in directory.glob(f"{day}_*.json"):
            stems.add(path.stem)
    return stems


def run(now: datetime | None = None) -> int:
    now = (now or datetime.now(JST)).astimezone(JST)
    day = now.strftime("%Y%m%d")
    local = xpost._load(day)
    durable = outbox.load_state(day) if outbox.configured() else {}
    state = outbox.merge_state(durable, local)

    featured = list(map(str, state.get("x_featured_races") or []))
    if len(featured) >= MAX_DAILY_POSTS:
        print(f"X featured quota full: {len(featured)}/{MAX_DAILY_POSTS}", flush=True)
        return 0

    posted = set(map(str, state.get("x_posted_races") or []))
    used_modes = set((state.get("x_featured_modes") or {}).values())
    candidates = []
    for stem in sorted(_stems(day)):
        race = _load_race(day, stem)
        if not race:
            continue
        key = _race_key(day, race["jcd"], race["rno"])
        if key in posted or key in featured:
            continue
        close = _deadline(day, race["deadline"])
        if close is None:
            continue
        lead = (close - now).total_seconds()
        if lead < MIN_LEAD_SECONDS or lead > MAX_LEAD_SECONDS:
            continue
        pick = _candidate(race)
        if not pick:
            continue
        plan = _ticket_plan(race)
        if not plan or len(plan["main"]) < MAIN_POINTS:
            continue
        diversity_bonus = 4 if pick["source"] not in used_modes else 0
        pick = {
            **pick,
            "race": race,
            "key": key,
            "rank": pick["score"] + diversity_bonus,
            "main_picks": plan["main"],
            "cover_picks": plan["cover"],
            "picks": plan["main"] + plan["cover"],
            "note": plan["note"],
        }
        candidates.append(pick)

    candidates.sort(key=lambda item: (item["rank"], -int(item["race"]["rno"])), reverse=True)
    remaining = MAX_DAILY_POSTS - len(featured)
    sent = 0
    for item in candidates:
        if sent >= remaining:
            break
        race = item["race"]
        record = {
            "day": day,
            "jcd": race["jcd"],
            "rno": race["rno"],
            "venue": race["venue"],
            "deadline": race["deadline"],
        }
        try:
            xpost.send_featured_record(
                record,
                item["picks"],
                source=item["source"],
                note=item["note"],
                main_picks=item["main_picks"],
                cover_picks=item["cover_picks"],
            )
        except Exception as exc:
            print(f"X featured send failed {item['key']}: {type(exc).__name__}: {exc}", flush=True)
            continue

        latest = xpost._load(day)
        durable = outbox.load_state(day) if outbox.configured() else {}
        latest = outbox.merge_state(durable, latest)
        if item["key"] not in set(map(str, latest.get("x_posted_races") or [])):
            continue
        latest["x_featured_races"] = sorted(set(latest.get("x_featured_races") or []) | {item["key"]})
        latest.setdefault("x_featured_modes", {})[item["key"]] = item["source"]
        if outbox.configured():
            latest, _ = xpost._checkpoint(day, latest)
        else:
            xpost._save(day, latest)
        sent += 1
        used_modes.add(item["source"])
        print(
            f"X featured sent {item['key']} source={item['source']} score={item['score']:.1f} "
            f"picks={len(item['picks'])}",
            flush=True,
        )
    return sent


if __name__ == "__main__":
    print(f"X featured complete: posted={run()}", flush=True)
