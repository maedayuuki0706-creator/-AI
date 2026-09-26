"""Independent 100-point score for selected Boat AI Navi races.

The existing A/B/C grade is intentionally unchanged. It describes the shape of
the likely winner. This module separately scores how attractive the race is as
a betting candidate. Selected delivery uses a conservative stability gate:
82+ total score, exhibition/ST component 12+, and EV component 13+.
85+ remains the strong-selected tier after the same stability gate.
"""

import random


SELECTED_THRESHOLD = 82
STRONG_SELECTED_THRESHOLD = 85
MIN_SELECTED_EXHIBITION_ST = 12.0
MIN_SELECTED_EV = 13.0


def passes_stability_gate(breakdown):
    """Evidence-backed delivery gate calibrated on the latest five-day sample."""
    breakdown = breakdown or {}
    return (
        float(breakdown.get("exhibition_st") or 0.0) >= MIN_SELECTED_EXHIBITION_ST
        and float(breakdown.get("ev") or 0.0) >= MIN_SELECTED_EV
    )


GENSEN_KUN_LINES = (
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
    "このレース、僕は見逃したくないな！",
    "ここは僕の出番かも！勝負候補に選んだよ！",
    "たくさん見たけど、今日はこのレースが気になる！",
    "僕の厳選チェックを通った一戦だよ！",
    "ここなら狙ってみたい。僕の勝負レース！",
    "今日の候補から、僕はこれを選んだよ！",
    "よし、決めた！僕の勝負レースはここ！",
)


def _scale(value, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def _inverse_scale(value, best, worst):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if worst <= best:
        return 0.0
    return max(0.0, min(1.0, (worst - value) / (worst - best)))


def _position_gap(analysis, position):
    totals = {lane: 0.0 for lane in range(1, 7)}
    for row in analysis.get("trifecta", []):
        try:
            lane = int(row["combination"].split("-")[position])
            totals[lane] += float(row.get("probability") or 0.0)
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    ranked = sorted(totals.values(), reverse=True)
    return ranked[0] - ranked[1] if len(ranked) >= 2 else 1.0


def race_score(analysis, allocation):
    """Return total 0-100 and a transparent component breakdown.

    Weights:
      head trust 25
      2nd/3rd readability 15
      exhibition/ST 15
      racer/course 15
      motor 10
      odds/EV 15
      conditions 5
    """
    heads = analysis.get("heads") or {}
    ranked_heads = sorted(heads.items(), key=lambda item: float(item[1]), reverse=True)
    if not ranked_heads:
        return 0, {}

    leader_lane = int(ranked_heads[0][0])
    top = float(ranked_heads[0][1])
    second = float(ranked_heads[1][1]) if len(ranked_heads) > 1 else 0.0
    gap = max(0.0, top - second)

    head = 12.0 + 7.0 * _scale(top, 0.25, 0.50) + 6.0 * _scale(gap, 0.05, 0.22)
    head = min(25.0, head)

    second_gap = _position_gap(analysis, 1)
    third_gap = _position_gap(analysis, 2)
    support = 5.0 + 5.0 * _scale(second_gap, 0.02, 0.12) + 5.0 * _scale(third_gap, 0.02, 0.10)
    support = min(15.0, support)

    boats = {
        int(boat.get("lane")): boat
        for boat in (analysis.get("inputs") or [])
        if boat.get("lane") is not None
    }
    leader = boats.get(leader_lane, {})
    preview = analysis.get("preview") or {}

    exhibition_count = int(preview.get("exhibition_count") or 0)
    if exhibition_count >= 6:
        ex_grade = float(leader.get("exhibition_grade") or 0.0)
        st = leader.get("exhibition_st")
        if st is None:
            st = leader.get("avg_st")
        exhibition_st = 6.0 + 5.0 * max(0.0, min(1.0, ex_grade))
        exhibition_st += 4.0 * _inverse_scale(st, 0.10, 0.24)
    else:
        exhibition_st = 6.0 * max(0.0, min(1.0, exhibition_count / 6.0))
    exhibition_st = min(15.0, exhibition_st)

    racer_course = 7.0 * _scale(leader.get("win_rate"), 4.0, 7.5)
    racer_course += 4.0 * _scale(leader.get("top2_rate"), 25.0, 55.0)
    course = int(leader.get("predicted_course") or leader.get("course") or leader_lane)
    racer_course += {1: 4.0, 2: 3.4, 3: 3.0, 4: 2.6, 5: 2.2, 6: 1.8}.get(course, 0.0)
    racer_course = min(15.0, racer_course)

    motor = 7.0 * _scale(leader.get("motor_top2_rate"), 20.0, 55.0)
    motor += 3.0 * _scale(leader.get("motor_top3_rate"), 30.0, 70.0)
    motor = min(10.0, motor)

    bets = list((allocation or {}).get("bets") or [])
    if (allocation or {}).get("status") == "bet" and bets:
        best_ev = max(float(bet.get("expected_value") or 0.0) for bet in bets)
        ev = 5.0 + 10.0 * _scale(best_ev, 1.05, 2.00)
    else:
        ev = 0.0
    ev = min(15.0, ev)

    wind = preview.get("wind_speed")
    wave = preview.get("wave_cm")
    if wind is None or wave is None:
        conditions = 2.5
    else:
        conditions = 3.0 * _inverse_scale(wind, 2.0, 6.0)
        conditions += 2.0 * _inverse_scale(wave, 2.0, 8.0)
    conditions = min(5.0, conditions)

    breakdown = {
        "head": round(head, 1),
        "support": round(support, 1),
        "exhibition_st": round(exhibition_st, 1),
        "racer_course": round(racer_course, 1),
        "motor": round(motor, 1),
        "ev": round(ev, 1),
        "conditions": round(conditions, 1),
    }
    total = int(round(sum(breakdown.values())))
    return max(0, min(100, total)), breakdown


def badge(score, breakdown=None):
    stable = passes_stability_gate(breakdown)
    if score >= STRONG_SELECTED_THRESHOLD and stable:
        return "🔥🔥強厳選"
    if score >= SELECTED_THRESHOLD and stable:
        return "🔥厳選"
    if score >= 75:
        return "候補｜精度ゲート見送り"
    return "通常"


def install(app):
    """Install scoring around the existing notifier without changing A/B/C."""
    original_message = app.analysis_message_with_virtual
    original_log = app.log_prediction_with_virtual
    score_cache = {}

    def scored_message(day, jcd, rno, deadline, phase, analysis, rows, required):
        message = original_message(day, jcd, rno, deadline, phase, analysis, rows, required)
        key = (day, str(jcd), int(rno), phase)
        allocation = app._VIRTUAL.get(key) or {}
        score, breakdown = race_score(analysis, allocation)
        score_cache[key] = {"score": score, "breakdown": breakdown}

        if phase == "final" and int((analysis.get("preview") or {}).get("exhibition_count") or 0) >= 6:
            score_line = f"**総合スコア {score}/100｜{badge(score, breakdown)}**"
            marker = "\n\n**仮想投票"
            if marker in message:
                candidate = message.replace(marker, "\n\n" + score_line + marker, 1)
            else:
                candidate = message + "\n\n" + score_line
            if len(candidate.encode("utf-16-le")) // 2 <= 2000:
                message = candidate
        return message

    def is_selected(record):
        return (
            record.get("phase") == "final"
            and bool(record.get("exhibition"))
            and int(record.get("selection_score") or 0) >= SELECTED_THRESHOLD
            and record.get("virtual_status") == "bet"
            and passes_stability_gate(record.get("selection_score_breakdown") or {})
        )

    def selected_message(record):
        score = int(record.get("selection_score") or 0)
        strong = score >= STRONG_SELECTED_THRESHOLD
        title = "🔥🔥 **厳選くんの勝負レース【強厳選】**" if strong else "🔥 **厳選くんの勝負レース**"
        intro = random.choice(GENSEN_KUN_LINES)

        heads = record.get("heads") or {}
        ranked = sorted(heads.items(), key=lambda item: float(item[1]), reverse=True)
        head_line = "取得なし"
        if ranked:
            head_line = f"{ranked[0][0]}号艇 {float(ranked[0][1]) * 100:.1f}%"
            if len(ranked) > 1:
                head_line += f" ｜ 対抗 {ranked[1][0]}号艇 {float(ranked[1][1]) * 100:.1f}%"

        main = list(record.get("main") or [])
        cover = list((record.get("cover") or [])[:6])
        virtual_bets = list(record.get("virtual_bets") or [])
        bets_by_combo = {
            str(bet.get("combination")): bet
            for bet in virtual_bets
            if bet.get("combination")
        }

        # 強厳選だけ、本線の中から確率・EV・並び順（展開一致）を合わせて
        # 1〜3点を「厚め」として自動抽出する。
        thick = []
        if strong and main:
            ranked_main = []
            denom = max(1, len(main) - 1)
            for index, pick in enumerate(main):
                bet = bets_by_combo.get(str(pick), {})
                ev = float(bet.get("expected_value") or 0.0)
                probability = float(bet.get("probability") or 0.0)
                alignment = 1.0 - (index / denom)
                thick_score = (ev * 0.55) + (probability * 10.0 * 0.30) + (alignment * 0.15)
                ranked_main.append((thick_score, index, pick))
            ranked_main.sort(key=lambda item: (-item[0], item[1]))
            thick_count = 3 if score >= 92 else 2 if score >= 88 else 1
            thick = [item[2] for item in ranked_main[:min(thick_count, len(ranked_main))]]

        regular_main = [pick for pick in main if pick not in thick]
        thick_text = "\n".join(f"`{pick}`" for pick in thick) or "なし"
        main_text = "\n".join(f"`{pick}`" for pick in regular_main) or ("厚めに集約" if thick else "なし")
        cover_text = "\n".join(f"`{pick}`" for pick in cover) or "なし"

        selected_bets = [
            bet for bet in virtual_bets
            if float(bet.get("expected_value") or 0) >= 1.15
            and float(bet.get("probability") or 0) >= 0.015
        ]
        ev_lines = [
            f"・{bet['combination']}｜{float(bet.get('odds') or 0):.1f}倍｜EV {float(bet.get('expected_value') or 0):.2f}"
            for bet in selected_bets[:3]
        ]
        ev_text = "\n".join(ev_lines) if ev_lines else "・仮想投票条件クリア"

        bd = record.get("selection_score_breakdown") or {}
        detail = (
            f"頭 {bd.get('head', 0)}/25 ｜ 相手 {bd.get('support', 0)}/15 ｜ 展示/ST {bd.get('exhibition_st', 0)}/15\n"
            f"選手/コース {bd.get('racer_course', 0)}/15 ｜ モーター {bd.get('motor', 0)}/10 ｜ EV {bd.get('ev', 0)}/15"
        )

        thick_section = ""
        if strong:
            thick_section = f"💥 **厚め（{len(thick)}点）**\n{thick_text}\n\n"

        point_heading = "💡 **強厳選になった理由**" if strong else "💡 **厳選ポイント**"
        threshold_text = (
            f"・総合スコア{STRONG_SELECTED_THRESHOLD}点以上"
            if strong else f"・総合スコア{SELECTED_THRESHOLD}点以上"
        )

        return (
            f"{intro}\n\n"
            f"{title}\n"
            f"**【{record.get('venue')} {record.get('rno')}R】**\n"
            f"⏰ 締切 **{record.get('deadline')}**　⭐ **{score}/100**　評価 **{record.get('grade')}**\n"
            f"━━━━━━━━━━━━\n"
            f"{thick_section}"
            f"🎯 **本線（{len(regular_main)}点）**\n{main_text}\n\n"
            f"🛡️ **押さえ（{len(cover)}点）**\n{cover_text}\n"
            f"━━━━━━━━━━━━\n"
            f"👀 **頭候補**\n{head_line}\n\n"
            f"{point_heading}\n"
            f"{threshold_text}\n"
            f"・展示6艇確認済み／展示・ST評価 {MIN_SELECTED_EXHIBITION_ST:.0f}/15以上\n"
            f"・EV評価 {MIN_SELECTED_EV:.0f}/15以上＋仮想投票条件クリア\n\n"
            f"📈 **期待値候補**\n{ev_text}\n\n"
            f"📊 **評価メモ**\n{detail}"
        )

    def scored_log(record):
        key = (
            record.get("day"),
            str(record.get("jcd")),
            int(record.get("rno", 0)),
            record.get("phase", "final"),
        )
        info = score_cache.get(key)
        if info is not None:
            record = dict(record)
            record["selection_score"] = info["score"]
            record["selection_score_breakdown"] = info["breakdown"]
            record["selection_score_version"] = "selected-score-v2-stability"
            record["selection_threshold"] = SELECTED_THRESHOLD
            record["strong_selection_threshold"] = STRONG_SELECTED_THRESHOLD
            record["selection_min_exhibition_st"] = MIN_SELECTED_EXHIBITION_ST
            record["selection_min_ev"] = MIN_SELECTED_EV
        return original_log(record)

    app.analysis_message_with_virtual = scored_message
    app.log_prediction_with_virtual = scored_log
    app._is_selected_record = is_selected
    app._selected_message = selected_message
