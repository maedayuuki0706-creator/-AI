"""Independent calibration feeds for 中穴AI and 穴予想.

The normal prediction message and selection logic are left untouched. This
module observes the same final analysis, scores mid-odds and longshot
opportunities separately, sends them to dedicated webhooks, and journals the
calibration data for later threshold tuning.
"""
from __future__ import annotations

from datetime import datetime
import itertools
import json
import math
import os
import random
from pathlib import Path
import urllib.request

from discord_notification_policy import message_payload

LOG_PATH = Path("data/opportunity_alert_deliveries.jsonl")
_CACHE: dict[tuple, dict] = {}


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _scale(value, low, high):
    value = _num(value)
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def _confidence(score):
    score = int(score)
    if score >= 85:
        return "S"
    if score >= 75:
        return "A"
    if score >= 60:
        return "B"
    return "C"


def _ev(row):
    value = row.get("expected_value")
    if value is not None:
        return _num(value)
    odds = _num(row.get("odds"))
    probability = _num(row.get("probability"))
    return odds * probability if odds > 0 and probability > 0 else 0.0


def _candidate_rows(analysis, kind):
    rows = []
    for row in analysis.get("trifecta") or []:
        odds = _num(row.get("odds"))
        probability = _num(row.get("probability"))
        if odds <= 0 or probability <= 0:
            continue
        if kind == "mid":
            if not (12.0 <= odds < 80.0) or probability < 0.006:
                continue
            quality = probability * (0.65 + min(_ev(row), 2.8)) * (1.0 + min(odds, 80.0) / 180.0)
        else:
            if odds < 50.0 or probability < 0.003:
                continue
            quality = probability * (0.55 + min(_ev(row), 3.2)) * (1.0 + min(math.log10(max(odds, 10.0)), 3.0) / 2.5)
        item = dict(row)
        item["_quality"] = quality
        rows.append(item)
    rows.sort(key=lambda row: (row["_quality"], _ev(row), _num(row.get("probability"))), reverse=True)
    return rows


def _coherent_selection(candidates, kind, analysis=None):
    if not candidates:
        return []

    head_strength = {}
    for row in candidates:
        head = str(row.get("combination", "")).split("-")[0]
        head_strength[head] = head_strength.get(head, 0.0) + _num(row.get("_quality"))

    ranked_heads = sorted(head_strength, key=head_strength.get, reverse=True)
    chosen_heads = ranked_heads[:1]
    if len(ranked_heads) > 1 and head_strength[ranked_heads[1]] >= head_strength[ranked_heads[0]] * (0.72 if kind == "mid" else 0.78):
        chosen_heads.append(ranked_heads[1])

    balanced = bool((analysis or {}).get("balanced_head_mode")) and kind == "mid"
    if balanced and len(ranked_heads) > 1:
        # Hit-rate first. G1 is not enough by itself: only diversify when the
        # model's supported head scenarios are genuinely close.
        top_strength = head_strength[ranked_heads[0]]
        second_strength = head_strength[ranked_heads[1]]
        if top_strength > 0 and second_strength >= top_strength * 0.72:
            chosen_heads = ranked_heads[:2]
            if len(ranked_heads) >= 3 and head_strength[ranked_heads[2]] >= top_strength * 0.62:
                chosen_heads.append(ranked_heads[2])
        else:
            balanced = False

    limit = 12 if kind == "mid" else 10
    if balanced:
        buckets = {head: [] for head in chosen_heads}
        for row in candidates:
            head = str(row.get("combination", "")).split("-")[0]
            if head in buckets:
                buckets[head].append(row)
        selected = []
        seen_balanced = set()
        # Seed two tickets per supported head, then fill by quality with a cap.
        for head in chosen_heads:
            for row in buckets[head][:2]:
                combo = row.get("combination")
                if combo and combo not in seen_balanced:
                    selected.append(row); seen_balanced.add(combo)
        cap = max(4, (limit + 1) // 2)
        counts = {head: sum(1 for row in selected if str(row.get("combination", "")).startswith(head + "-")) for head in chosen_heads}
        for row in candidates:
            combo = row.get("combination")
            head = str(combo or "").split("-")[0]
            if not combo or combo in seen_balanced or head not in counts or counts[head] >= cap:
                continue
            selected.append(row); seen_balanced.add(combo); counts[head] += 1
            if len(selected) >= limit:
                break
        selected = selected[:limit]
    else:
        selected = [row for row in candidates if str(row.get("combination", "")).split("-")[0] in chosen_heads][:limit]

    # Keep a strong 1-escape longshot scenario alive even when another head
    # narrowly wins the aggregate longshot score.
    if kind == "long":
        escape = [
            row for row in candidates
            if str(row.get("combination", "")).startswith("1-")
            and _num(row.get("odds")) >= 80
        ]
        if escape and not any(str(row.get("combination", "")).startswith("1-") for row in selected):
            selected = (selected[: max(0, limit - 2)] + escape[:2])[:limit]

    seen = set()
    out = []
    for row in selected:
        combo = row.get("combination")
        if combo and combo not in seen:
            seen.add(combo)
            out.append(row)
    return out


def _score(analysis, picks, kind):
    preview = analysis.get("preview") or {}
    if not picks:
        exhibition = 10 if int(preview.get("exhibition_count") or 0) >= 6 else 0
        return exhibition, {
            "candidate": 0,
            "ev": 0,
            "scenario": 0,
            "trigger": 0,
            "exhibition": exhibition,
            "odds": 0,
        }

    best_probability = max(_num(row.get("probability")) for row in picks)
    best_ev = max(_ev(row) for row in picks)
    total_probability = sum(_num(row.get("probability")) for row in picks)
    odds_values = [_num(row.get("odds")) for row in picks]
    best_odds = max(odds_values)
    median_odds = sorted(odds_values)[len(odds_values) // 2]

    if kind == "mid":
        candidate = 25 * _scale(best_probability, 0.008, 0.060)
        ev_component = 25 * _scale(best_ev, 0.95, 2.30)
        scenario = 20 * _scale(total_probability, 0.04, 0.22)
        trigger = 10 * _scale(len(picks), 2, 8)
        odds_component = 10 * (1.0 - min(1.0, abs(median_odds - 35.0) / 45.0))
    else:
        candidate = 25 * _scale(best_probability, 0.003, 0.030)
        ev_component = 25 * _scale(best_ev, 1.00, 2.80)
        scenario = 15 * _scale(total_probability, 0.018, 0.130)

        heads = analysis.get("heads") or {}
        non_one = max((_num(value) for lane, value in heads.items() if str(lane) != "1"), default=0.0)
        escape_longshot = any(
            str(row.get("combination", "")).startswith("1-")
            and _num(row.get("odds")) >= 80
            for row in picks
        )
        upset = _scale(non_one, 0.12, 0.28)
        escape = 1.0 if escape_longshot else 0.0
        trigger = 15 * max(upset, escape * 0.85)
        odds_component = 10 * _scale(best_odds, 50, 180)

    exhibition = 10 if int(preview.get("exhibition_count") or 0) >= 6 else 5 * _scale(preview.get("exhibition_count"), 0, 6)
    parts = {
        "candidate": round(candidate, 1),
        "ev": round(ev_component, 1),
        "scenario": round(scenario, 1),
        "trigger": round(trigger, 1),
        "exhibition": round(exhibition, 1),
        "odds": round(odds_component, 1),
    }
    return max(0, min(100, int(round(sum(parts.values()))))), parts


def _all_cross_pairs(a, b):
    return {(x, y) for x in a for y in b} | {(y, x) for x in a for y in b}


def _compress_head(head, pairs):
    remaining = set(pairs)
    lines = []

    # First prefer full cross reversals such as 1-25=36.
    involved = sorted({lane for pair in remaining for lane in pair})
    best = None
    for size_a in range(1, len(involved)):
        for a_tuple in itertools.combinations(involved, size_a):
            a = set(a_tuple)
            b = set(involved) - a
            if not b or min(a) > min(b):
                continue
            needed = _all_cross_pairs(a, b)
            if len(needed) < 4 or not needed.issubset(remaining):
                continue
            if best is None or len(needed) > len(best[2]):
                best = (a, b, needed)
    if best:
        a, b, needed = best
        lines.append(f"{head}-{''.join(map(str, sorted(a)))}={''.join(map(str, sorted(b)))}")
        remaining -= needed

    # Then symmetric same-pool pairs such as 1-56-56.
    while True:
        involved = sorted({lane for pair in remaining for lane in pair})
        found = False
        for size in range(min(3, len(involved)), 1, -1):
            for group_tuple in itertools.combinations(involved, size):
                group = set(group_tuple)
                needed = {(a, b) for a in group for b in group if a != b}
                if needed and needed.issubset(remaining):
                    digits = "".join(map(str, sorted(group)))
                    lines.append(f"{head}-{digits}-{digits}")
                    remaining -= needed
                    found = True
                    break
            if found:
                break
        if not found:
            break

    # Finally use only unambiguous same-second compression.
    by_second = {}
    for second, third in sorted(remaining):
        by_second.setdefault(second, []).append(third)
    for second, thirds in by_second.items():
        digits = "".join(map(str, sorted(set(thirds))))
        lines.append(f"{head}-{second}-{digits}")
    return lines


def _formation_lines(picks):
    combos = []
    for row in picks:
        combo = str(row.get("combination") or "")
        parts = combo.split("-")
        if len(parts) == 3 and len(set(parts)) == 3 and combo not in combos:
            combos.append(combo)

    by_head = {}
    for combo in combos:
        head, second, third = combo.split("-")
        by_head.setdefault(head, []).append((second, third))

    lines = []
    for head in by_head:
        lines.extend(_compress_head(head, by_head[head]))
    return lines, len(combos)


def _strategy_text(analysis, picks, kind):
    if not picks:
        return "該当する配当帯に有力候補なし。検証用に見送り判定を記録。"
    if kind == "mid" and analysis.get("balanced_head_mode"):
        return "多摩川G1の実力伯仲を考慮。1着軸を決め打ちせず、根拠の強い複数シナリオを組み合わせる。"

    first = str(picks[0].get("combination") or "")
    parts = first.split("-")
    head = parts[0] if len(parts) == 3 else "-"
    if head == "1":
        outer_support = any(
            any(int(x) >= 4 for x in str(row.get("combination") or "").split("-")[1:])
            for row in picks
            if len(str(row.get("combination") or "").split("-")) == 3
        )
        if kind == "long" and outer_support:
            return "①逃げ固定＋人気薄の2・3着食い込み。逃げ穴・逃げ万舟まで狙う。"
        return "①逃げ軸から相手荒れを狙う。人気薄の2・3着食い込みを重視。"

    contains_one = sum(
        1 for row in picks
        if "1" in str(row.get("combination") or "").split("-")[1:]
    ) >= max(1, len(picks) // 2)
    if contains_one:
        return f"{head}号艇の攻めを起点に、①残しまで含めた波乱シナリオ。"
    return f"{head}号艇頭を中心に、人気順とは違う決着シナリオを狙う。"


def _reason_lines(analysis, picks, kind):
    preview = analysis.get("preview") or {}
    heads = analysis.get("heads") or {}
    ranked_heads = sorted(heads.items(), key=lambda item: _num(item[1]), reverse=True)
    reasons = []
    if picks:
        odds = [_num(row.get("odds")) for row in picks]
        best = max(picks, key=lambda row: _ev(row))
        reasons.append(
            f"候補{len(picks)}点 / 配当帯 {min(odds):.1f}〜{max(odds):.1f}倍 / 最大EV {_ev(best):.2f}"
        )
    else:
        label = "12〜80倍" if kind == "mid" else "50倍以上"
        reasons.append(f"{label}で確率条件を満たす候補なし")
    if ranked_heads:
        top = ranked_heads[0]
        text = f"頭評価：{top[0]}号艇 {_num(top[1]) * 100:.1f}%"
        if len(ranked_heads) > 1:
            text += f" / 対抗{ranked_heads[1][0]}号艇 {_num(ranked_heads[1][1]) * 100:.1f}%"
        reasons.append(text)
    wind = preview.get("wind_speed")
    wind_text = f"{wind}m" if wind is not None else "未取得"
    reasons.append(f"展示 {int(preview.get('exhibition_count') or 0)}/6艇 / 風速 {wind_text}")
    return reasons[:3]


def _message(venue, rno, deadline, analysis, picks, kind, score, breakdown):
    icon = "🔥" if kind == "mid" else "💣"
    name = "中穴予想" if kind == "mid" else "穴予想"
    main_count = min(len(picks), 4 if kind == "mid" else 3)
    main = picks[:main_count]
    cover = picks[main_count:]
    main_lines, main_points = _formation_lines(main)
    cover_lines, cover_points = _formation_lines(cover)
    all_odds = [_num(row.get("odds")) for row in picks if _num(row.get("odds")) > 0]

    lines = [
        f"{icon} **{name}｜{venue} {rno}R**",
        f"期待度 **{score}/100｜自信度 {_confidence(score)}**",
        f"締切 **{deadline}**",
        "検証期間｜現在は全レース採点中",
        "",
        "**狙い**",
        _strategy_text(analysis, picks, kind),
        "",
        f"**本線（{main_points}点）**",
    ]
    lines += [f"`{line}`" for line in main_lines] or ["候補なし"]
    lines += ["", f"**抑え（{cover_points}点）**"]
    lines += [f"`{line}`" for line in cover_lines] or ["なし"]
    lines += ["", f"**計{len(picks)}点**", "", "**想定配当**"]
    if all_odds:
        lines.append(f"{min(all_odds):.1f}〜{max(all_odds):.1f}倍")
    else:
        lines.append("候補なし")
    lines += ["", "**根拠**"]
    lines += [f"・{reason}" for reason in _reason_lines(analysis, picks, kind)]
    lines += ["", "**ひとこと**"]
    if score >= 75:
        lines.append("現時点では勝負候補。検証データを貯めて配信ラインを最適化する。")
    elif score >= 60:
        lines.append("候補には残るが、まだ勝負ライン確定前。結果と照合して精査する。")
    else:
        lines.append("現状は見送り寄り。配信ライン決定用の検証データとして記録。")
    return "\n".join(lines)


def _build_payload(venue, rno, deadline, analysis, kind):
    candidates = _candidate_rows(analysis, kind)
    picks = _coherent_selection(candidates, kind, analysis)
    score, breakdown = _score(analysis, picks, kind)
    return {
        "kind": kind,
        "score": score,
        "confidence": _confidence(score),
        "breakdown": breakdown,
        "picks": [
            {
                "combination": row.get("combination"),
                "odds": row.get("odds"),
                "probability": row.get("probability"),
                "expected_value": row.get("expected_value"),
            }
            for row in picks
        ],
        "message": _message(venue, rno, deadline, analysis, picks, kind, score, breakdown),
        "mode": "calibration_all_races",
        "score_version": "opportunity-score-v1",
    }


def _is_selected_mid(payload):
    picks = payload.get("picks") or []
    if int(payload.get("score") or 0) < 75:
        return False
    if not picks or len(picks) > 12:
        return False
    best_ev = 0.0
    for row in picks:
        ev = row.get("expected_value")
        if ev is None:
            ev = _num(row.get("odds")) * _num(row.get("probability"))
        best_ev = max(best_ev, _num(ev))
    return best_ev >= 1.05


def _selected_mid_message(message):
    intros = (
        "僕が選んだ、今日の勝負レース！",
        "いっぱい見た中から、僕はここを選んだよ！",
        "条件が揃ったよ。僕の勝負レース！",
        "このレース、僕は狙ってみたいな！",
        "中穴狙いなら、僕はここ！",
        "ここ、ちょっと気になる！僕の厳選レースだよ！",
        "僕の目に止まったのはこのレース！",
        "今日はここに注目してるよ！",
        "これなら勝負してみたい！僕の一押し！",
        "迷ったけど、最後に選んだのはここ！",
        "僕ならこのレースから狙ってみるよ！",
        "条件を見比べて、今日はここに決めた！",
        "ちょっとワクワクする一戦。僕はここ！",
        "この中穴、僕は見逃したくないな！",
        "ここは僕の出番かも！勝負候補に選んだよ！",
        "たくさん見たけど、今日はこのレースが気になる！",
        "僕の厳選チェックを通った一戦だよ！",
        "ここなら狙ってみたい。僕の勝負レース！",
        "今日の中穴候補から、僕はこれを選んだよ！",
        "よし、決めた！僕の勝負レースはここ！",
    )
    body = str(message).replace(
        "🔥 **中穴予想｜",
        "🚨 **厳選中穴予想｜",
        1,
    )
    return f"{random.choice(intros)}\n\n{body}"


def _send(env_name, content):
    url = os.getenv(env_name, "").strip()
    if not url:
        raise RuntimeError(f"{env_name} is missing")
    payload = json.dumps(
        message_payload(content, notify_everyone=env_name == "DISCORD_WEBHOOK_MID_ODDS_SELECTED"),
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Boat-AI-Navi/opportunity-v1"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status not in (200, 204):
            raise RuntimeError(f"Discord HTTP {response.status}")


def _append_log(record):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def smoke_test():
    now = datetime.now().astimezone().isoformat()
    _send(
        "DISCORD_WEBHOOK_MID_ODDS",
        "🔥 **中穴AI 接続テスト**\n別チャンネル配信・期待度表示の準備OK。\n" + now,
    )
    _send(
        "DISCORD_WEBHOOK_LONGSHOT",
        "💣 **穴予想 接続テスト**\n逃げ穴・1飛び穴を含む別ロジックの準備OK。\n" + now,
    )


def install(app):
    """Observe the final analysis without changing the normal prediction."""
    original_message = app.analysis_message_with_virtual
    original_log = app.log_prediction_with_virtual

    def capture_message(day, jcd, rno, deadline, phase, analysis, rows, required):
        normal_message = original_message(day, jcd, rno, deadline, phase, analysis, rows, required)
        if phase == "final" and int((analysis.get("preview") or {}).get("exhibition_count") or 0) >= 6:
            key = (str(day), str(jcd), int(rno), str(phase))
            venue = app.base.VENUES.get(str(jcd), str(jcd))
            _CACHE[key] = {
                "mid": _build_payload(venue, rno, deadline, analysis, "mid"),
                "long": _build_payload(venue, rno, deadline, analysis, "long"),
            }
        return normal_message

    def send_after_normal(record):
        result = original_log(record)
        if record.get("phase") != "final":
            return result

        key = (
            str(record.get("day")),
            str(record.get("jcd")),
            int(record.get("rno", 0)),
            str(record.get("phase", "final")),
        )
        cached = _CACHE.pop(key, None)
        if not cached:
            return result

        sent_at = datetime.now(app.base.JST).isoformat()
        for label, env_name in (
            ("mid", "DISCORD_WEBHOOK_MID_ODDS"),
            ("long", "DISCORD_WEBHOOK_LONGSHOT"),
        ):
            payload = cached[label]
            selected_mid = label == "mid" and _is_selected_mid(payload)
            target_env = "DISCORD_WEBHOOK_MID_ODDS_SELECTED" if selected_mid else env_name
            message = _selected_mid_message(payload["message"]) if selected_mid else payload["message"]
            try:
                _send(target_env, message)
                _append_log({
                    "day": record.get("day"),
                    "jcd": record.get("jcd"),
                    "venue": record.get("venue"),
                    "rno": record.get("rno"),
                    "deadline": record.get("deadline"),
                    "sent_at": sent_at,
                    "stream": "mid_odds" if label == "mid" else "longshot",
                    "selected": bool(selected_mid),
                    "delivery_env": target_env,
                    "score": payload["score"],
                    "confidence": payload["confidence"],
                    "score_breakdown": payload["breakdown"],
                    "picks": payload["picks"],
                    "point_count": len(payload["picks"]),
                    "mode": payload["mode"],
                    "score_version": payload["score_version"],
                })
            except Exception as exc:
                print(
                    f"opportunity alert failed {label} {record.get('jcd')} {record.get('rno')}R: "
                    f"{type(exc).__name__}",
                    flush=True,
                )
        return result

    app.analysis_message_with_virtual = capture_message
    app.log_prediction_with_virtual = send_after_normal
